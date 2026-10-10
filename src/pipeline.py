"""End-to-end pipeline: ingest -> extract -> summarize -> render.

Usage:
    python -m src.pipeline                 # full run
    python -m src.pipeline --no-summarize  # ingest + render only (no LLM calls)
    python -m src.pipeline --render-only   # re-render site from existing DB
    python -m src.pipeline --strict        # exit 3 if no article could be summarized
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .config import Config, load_config
from .digest import generate_digest
from .extract import extract_text
from .ingest import ingest_all
from .models import compact_db, init_db
from .render import render_site
from .summarize import ProviderPool, summarize_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("pipeline")

THIN_TEXT = 400  # feed text shorter than this is a teaser — fetch the page


@dataclass
class SummaryStats:
    eligible: int = 0       # pending, within age window, under attempt cap
    selected: int = 0       # after MAX_ARTICLES_PER_RUN
    summarized: int = 0
    failed: int = 0         # tried and failed (attempts incremented)
    untried: int = 0        # skipped because every provider was exhausted
    exhausted: bool = False
    seconds: float = 0.0
    providers: str = ""
    by_model: dict[str, int] = field(default_factory=dict)


def stale_cutoff(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return (now - timedelta(days=cfg.summary_max_age_days)).isoformat()


def _prepare(row: dict, cfg: Config) -> tuple[dict, str | None]:
    """Article payload for the LLM; fetches full text for thin teasers.

    Runs in a worker thread (network only, no DB access). Returns the payload
    and the newly extracted text (to persist) if any.
    """
    text = (row["raw_text"] or "").strip()
    fetched = None
    if len(text) < THIN_TEXT:
        full = extract_text(row["url"])
        if full and len(full) > len(text):
            text = fetched = full
    text = text[: cfg.max_input_chars] or row["title"] or ""
    return ({"id": row["id"], "title": row["title"] or "", "text": text,
             "feed_topic": row["feed_topic"]}, fetched)


def _work(batch: list[dict], cfg: Config, pool: ProviderPool):
    if pool.exhausted:
        return batch, None, {}
    prepared = [_prepare(r, cfg) for r in batch]
    fetched = {p["id"]: f for p, f in prepared if f}
    results = summarize_batch([p for p, _ in prepared], pool)
    return batch, results, fetched


def summarize_pending(conn, cfg: Config, pool: ProviderPool | None = None) -> SummaryStats:
    """Summarize pending articles, newest first, in parallel batches.

    Newest-first keeps today's brief complete when a per-run cap applies.
    Articles older than SUMMARY_MAX_AGE_DAYS or that already failed
    SUMMARY_MAX_ATTEMPTS times are left alone (they render by title only).
    All DB writes happen on this thread; workers only do network I/O.
    """
    t0 = time.monotonic()
    pool = pool or ProviderPool(cfg.llm_chain)
    stats = SummaryStats()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, url, title, feed_topic, raw_text FROM articles "
        "WHERE summarized = 0 AND attempts < ? "
        "AND COALESCE(published, fetched_at) >= ? "
        "ORDER BY COALESCE(published, fetched_at) DESC, id DESC",
        (cfg.summary_max_attempts, stale_cutoff(cfg)),
    ).fetchall()]
    stats.eligible = len(rows)
    if cfg.max_articles_per_run > 0:
        rows = rows[: cfg.max_articles_per_run]
    stats.selected = len(rows)
    log.info("Summarizing %d of %d eligible articles (batch=%d, workers=%d, providers=%s)",
             len(rows), stats.eligible, cfg.summary_batch_size, cfg.llm_concurrency,
             pool.chain or "none")
    if pool.skipped:
        log.info("Skipping providers without credentials: %s", pool.skipped)
    if not rows:
        return stats
    if not pool.chain:
        log.error("No usable LLM provider (no API keys set). Chain=%s", cfg.llm_chain)
        stats.exhausted, stats.untried = True, len(rows)
        return stats

    size = cfg.summary_batch_size
    batches = [rows[i:i + size] for i in range(0, len(rows), size)]
    by_model: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=cfg.llm_concurrency) as ex:
        futures = [ex.submit(_work, b, cfg, pool) for b in batches]
        for fut in as_completed(futures):
            if fut.cancelled():
                continue
            try:
                batch, results, fetched = fut.result()
            except Exception as e:  # noqa: BLE001 — one bad batch must not kill the run
                log.error("Summarization worker crashed: %s", e)
                continue
            for aid, text in fetched.items():
                conn.execute("UPDATE articles SET raw_text = ? WHERE id = ?", (text, aid))
            if results is None:  # nothing left to try — don't count against article
                stats.untried += len(batch)
                continue
            for r in batch:
                res = results.get(r["id"])
                if res is None:
                    conn.execute("UPDATE articles SET attempts = attempts + 1 WHERE id = ?",
                                 (r["id"],))
                    stats.failed += 1
                    continue
                conn.execute(
                    """UPDATE articles
                       SET summarized = 1, headline = ?, bullets = ?, topic = ?,
                           sentiment = ?, importance = ?, instruments = ?,
                           llm_model = ?, raw_text = NULL
                       WHERE id = ?""",
                    (res["headline"], json.dumps(res["bullets"]), res["topic"],
                     res["sentiment"], res["importance"], json.dumps(res["instruments"]),
                     res["llm_model"], r["id"]),
                )
                by_model[res["llm_model"]] = by_model.get(res["llm_model"], 0) + 1
                stats.summarized += 1
            conn.commit()
            done = stats.summarized + stats.failed + stats.untried
            if len(batches) > 1 and done % (size * 10) < size:
                log.info("Progress: %d/%d (summarized %d)", done, len(rows), stats.summarized)
            if pool.exhausted and not stats.exhausted:
                stats.exhausted = True
                log.error("All LLM providers exhausted — stopping summarization. %s",
                          pool.report())
                for f in futures:
                    f.cancel()
    conn.commit()
    cancelled = len(rows) - (stats.summarized + stats.failed + stats.untried)
    stats.untried += cancelled
    stats.exhausted = stats.exhausted or pool.exhausted
    stats.seconds = time.monotonic() - t0
    stats.providers = pool.report()
    stats.by_model = by_model
    log.info("Summarized %d articles (%d failed, %d untried) in %.0fs. %s",
             stats.summarized, stats.failed, stats.untried, stats.seconds, stats.providers)
    return stats


def _write_step_summary(stats: SummaryStats) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "### Summarization",
        f"- eligible: {stats.eligible}, selected: {stats.selected}",
        f"- summarized: **{stats.summarized}**, failed: {stats.failed}, "
        f"untried: {stats.untried}, all providers exhausted: {stats.exhausted}",
        f"- time: {stats.seconds:.0f}s",
        f"- by model: {stats.by_model or '—'}",
        f"- providers: {stats.providers or '—'}",
    ]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily global-macro news pipeline")
    ap.add_argument("--no-summarize", action="store_true",
                    help="skip the LLM pass (ingest + render only)")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the site from the existing DB")
    ap.add_argument("--vacuum", action="store_true",
                    help="force a VACUUM of the DB at the end of the run")
    ap.add_argument("--strict", action="store_true",
                    help="exit with status 3 (after rendering) if articles were "
                         "pending but none could be summarized")
    args = ap.parse_args()

    cfg = load_config()
    conn = init_db(cfg.db_path)

    stats = None
    if not args.render_only:
        ingest_all(conn, cfg)
        if not args.no_summarize:
            pool = ProviderPool(cfg.llm_chain)
            stats = summarize_pending(conn, cfg, pool)
            _write_step_summary(stats)
            if not pool.exhausted:
                generate_digest(conn, cfg, pool)  # one mood line for the latest day

    render_site(conn, cfg)
    compact_db(conn, force_vacuum=args.vacuum, stale_before=stale_cutoff(cfg),
               max_attempts=cfg.summary_max_attempts)
    conn.close()
    log.info("Done. Open %s/index.html", cfg.site_dir)

    if args.strict and stats and stats.selected and not stats.summarized:
        log.error("Summarization outage: %d articles pending, 0 summarized.", stats.selected)
        sys.exit(3)


if __name__ == "__main__":
    main()
