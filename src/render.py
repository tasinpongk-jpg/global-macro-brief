"""Render the static reading site with Jinja2.

Layout: one page per day → cross-source stories clustered, grouped by topic,
sorted by importance. Each cluster: bold headline + key takeaways + an "also
covered by" list linking the other outlets that ran the same story.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .cluster import cluster
from .config import TOPIC_ORDER, Config

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _day_key(iso: str | None) -> str:
    if not iso:
        return "undated"
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return "undated"


def _row_to_story(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {
        "headline": r["headline"] or r["title"] or "(untitled)",
        "bullets": json.loads(r["bullets"]) if r["bullets"] else [],
        "topic": r["topic"] or r["feed_topic"] or "Other",
        "sentiment": r["sentiment"] or "neutral",
        "importance": (r["importance"] if "importance" in keys and r["importance"] else 3),
        "instruments": json.loads(r["instruments"]) if r["instruments"] else [],
        "url": r["url"],
        "source": r["source"],
        "published": r["published"],
    }


def _build_cluster(members: list[dict]) -> dict:
    """Pick a primary story for a cluster and attach the other sources."""
    # Primary = highest importance, then earliest published, then most bullets.
    primary = sorted(
        members,
        key=lambda s: (-s["importance"], s["published"] or "9999", -len(s["bullets"])),
    )[0]
    others = [m for m in members if m is not primary]
    # De-dup the "also covered by" list by source name.
    seen, also = set(), []
    for m in others:
        if m["source"] not in seen:
            seen.add(m["source"])
            also.append({"source": m["source"], "url": m["url"]})
    return {**primary, "also": also, "size": len(members),
            "max_importance": max(m["importance"] for m in members)}


def _cluster_text(s: dict) -> str:
    # Headline carries the event; instruments reinforce same-asset stories.
    return s["headline"] + " " + " ".join(s["instruments"])


def _topic_groups(stories: list[dict]):
    """Bucket the day's stories by topic, then cluster within each topic.

    Within-topic clustering keeps different angles of one mega-event apart
    (oil-down under Energy/Oil, stocks-up under Markets) while still merging
    near-duplicate reports of the same story from different outlets.
    """
    by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}
    for s in stories:
        by_topic.setdefault(s["topic"] if s["topic"] in by_topic else "Other", []).append(s)

    out = []
    for t in TOPIC_ORDER:
        bucket = by_topic.get(t)
        if not bucket:
            continue
        items = [_build_cluster(c) for c in cluster(bucket, _cluster_text)]
        # Stable two-pass: newest first, then by importance/cluster-size.
        items.sort(key=lambda c: c["published"] or "", reverse=True)
        items.sort(key=lambda c: (c["max_importance"], c["size"]), reverse=True)
        out.append((t, items))
    return out


def render_site(conn: sqlite3.Connection, cfg: Config, days: int = 14) -> None:
    cfg.site_dir.mkdir(parents=True, exist_ok=True)
    if STATIC.exists():
        shutil.copytree(STATIC, cfg.site_dir / "static", dirs_exist_ok=True)

    rows = conn.execute(
        """SELECT * FROM articles
           WHERE summarized = 1
           ORDER BY COALESCE(published, fetched_at) DESC"""
    ).fetchall()

    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[_day_key(r["published"] or r["fetched_at"])].append(_row_to_story(r))

    ordered_days = sorted((d for d in by_day if d != "undated"), reverse=True)[:days]
    if "undated" in by_day:
        ordered_days.append("undated")

    env = _env()
    day_tpl = env.get_template("day.html")
    index_tpl = env.get_template("index.html")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    index_days = []
    for day in ordered_days:
        stories = by_day[day]
        groups = _topic_groups(stories)
        n_clusters = sum(len(items) for _, items in groups)
        html = day_tpl.render(
            site_title=cfg.site_title,
            day=day,
            groups=groups,
            count=len(stories),
            clustered=n_clusters,
            generated=generated,
        )
        out = cfg.site_dir / (f"{day}.html" if day != "undated" else "undated.html")
        out.write_text(html, encoding="utf-8")
        index_days.append({"day": day, "count": len(stories),
                           "clustered": n_clusters, "file": out.name})

    index_html = index_tpl.render(
        site_title=cfg.site_title,
        days=index_days,
        generated=generated,
    )
    (cfg.site_dir / "index.html").write_text(index_html, encoding="utf-8")
    log.info("Rendered %d day pages -> %s", len(index_days), cfg.site_dir)
