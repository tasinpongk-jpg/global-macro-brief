"""End-to-end pipeline: ingest -> extract -> summarize -> render.

Usage:
    python -m src.pipeline                 # full run
    python -m src.pipeline --no-summarize  # ingest + render only (no LLM calls)
    python -m src.pipeline --render-only    # re-render site from existing DB
"""
from __future__ import annotations

import argparse
import json
import logging

from .config import load_config
from .digest import generate_digest
from .extract import extract_text
from .ingest import ingest_all
from .models import init_db
from .render import render_site
from .summarize import summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


def summarize_pending(conn, cfg) -> int:
    # Newest-first: when a per-run cap is set, today's brief must be summarized
    # before older backlog so the front page is always complete. Backlog from
    # newly-added feeds then fills in behind the current day instead of starving
    # it.
    rows = conn.execute(
        "SELECT * FROM articles WHERE summarized = 0 "
        "ORDER BY COALESCE(published, fetched_at) DESC, id DESC"
    ).fetchall()
    if cfg.max_articles_per_run > 0:
        rows = rows[: cfg.max_articles_per_run]
    log.info("Summarizing %d pending articles", len(rows))

    done = 0
    for r in rows:
        text = (r["raw_text"] or "").strip()
        if len(text) < 400:  # teaser too thin — fetch full text
            full = extract_text(r["url"])
            if full:
                text = full
                conn.execute(
                    "UPDATE articles SET raw_text = ? WHERE id = ?", (text, r["id"])
                )
        text = text[: cfg.max_input_chars]
        if not text:
            text = r["title"] or ""

        result = summarize(r["title"] or "", text, r["feed_topic"], cfg.llm_chain)
        if not result:
            continue
        conn.execute(
            """UPDATE articles
               SET summarized = 1, headline = ?, bullets = ?, topic = ?,
                   sentiment = ?, importance = ?, instruments = ?, llm_model = ?
               WHERE id = ?""",
            (result["headline"], json.dumps(result["bullets"]), result["topic"],
             result["sentiment"], result["importance"],
             json.dumps(result["instruments"]), result["llm_model"], r["id"]),
        )
        conn.commit()
        done += 1
    log.info("Summarized %d articles", done)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily global-macro news pipeline")
    ap.add_argument("--no-summarize", action="store_true",
                    help="skip the LLM pass (ingest + render only)")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the site from the existing DB")
    args = ap.parse_args()

    cfg = load_config()
    conn = init_db(cfg.db_path)

    if not args.render_only:
        ingest_all(conn, cfg)
        if not args.no_summarize:
            summarize_pending(conn, cfg)
            generate_digest(conn, cfg)  # one mood line for the latest day

    render_site(conn, cfg)
    conn.close()
    log.info("Done. Open %s/index.html", cfg.site_dir)


if __name__ == "__main__":
    main()
