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


def _pretty_date(day: str) -> str:
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except ValueError:
        return day


def _tally(groups) -> dict:
    counts = {"bullish": 0, "bearish": 0, "mixed": 0, "neutral": 0}
    for _, items in groups:
        for c in items:
            counts[c["sentiment"]] = counts.get(c["sentiment"], 0) + 1
    return counts


def _ticker(groups) -> list[dict]:
    """Top instruments of the day with their cluster sentiment, for the tape."""
    flat = [c for _, items in groups for c in items]
    flat.sort(key=lambda c: c["max_importance"], reverse=True)
    seen, out = set(), []
    for c in flat:
        for sym in c["instruments"]:
            k = sym.upper()
            if k in seen:
                continue
            seen.add(k)
            out.append({"sym": sym, "sentiment": c["sentiment"]})
            if len(out) >= 24:
                return out
    return out


def render_site(conn: sqlite3.Connection, cfg: Config, days: int = 21) -> None:
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

    # Every day in the DB gets its own page so Archive links always resolve.
    # The date picker, by contrast, only lists the most recent `days` so the
    # dropdown stays usable as history grows.
    all_days = sorted((d for d in by_day if d != "undated"), reverse=True)
    if "undated" in by_day:
        all_days.append("undated")

    day_data: dict[str, tuple] = {}
    for day in all_days:
        groups = _topic_groups(by_day[day])
        n_clusters = sum(len(items) for _, items in groups)
        fname = f"{day}.html" if day != "undated" else "undated.html"
        day_data[day] = (groups, n_clusters, len(by_day[day]), fname)

    recent = [d for d in all_days if d != "undated"][:days]
    if "undated" in by_day:
        recent.append("undated")
    days_meta = [{"day": d, "file": day_data[d][3], "count": day_data[d][1],
                  "display": _pretty_date(d)} for d in recent]

    env = _env()
    dash = env.get_template("dashboard.html")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def render_day(day: str) -> str:
        groups, n_clusters, n_stories, _ = day_data[day]
        return dash.render(
            site_title=cfg.site_title, day=day, day_display=_pretty_date(day),
            days=days_meta, groups=groups, ticker=_ticker(groups),
            tally=_tally(groups), total=n_clusters, count=n_stories,
            generated=generated,
        )

    for day in all_days:
        (cfg.site_dir / day_data[day][3]).write_text(render_day(day), encoding="utf-8")

    # index.html = the most recent day's dashboard (what opens by default).
    if all_days:
        (cfg.site_dir / "index.html").write_text(
            render_day(all_days[0]), encoding="utf-8")
    else:
        (cfg.site_dir / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>Daily Global-Macro Brief</title>"
            "<body style='font-family:sans-serif;padding:3rem'>No briefs yet.</body>",
            encoding="utf-8")

    _render_archive(env, cfg, all_days, day_data, generated)
    log.info("Rendered %d day pages + index + archive -> %s", len(all_days), cfg.site_dir)


def _render_archive(env, cfg, all_days, day_data, generated) -> None:
    """Write archive.html: every day in the DB, grouped by month (newest first)."""
    months: list[dict] = []
    cur_key = None
    for day in all_days:
        if day == "undated":
            key, label = "undated", "Undated"
        else:
            key, label = day[:7], datetime.strptime(day, "%Y-%m-%d").strftime("%B %Y")
        if key != cur_key:
            months.append({"label": label, "days": []})
            cur_key = key
        months[-1]["days"].append({"file": day_data[day][3],
                                   "display": _pretty_date(day),
                                   "count": day_data[day][1]})
    html = env.get_template("archive.html").render(
        site_title=cfg.site_title, months=months, generated=generated,
        total_days=len([d for d in all_days if d != "undated"]),
    )
    (cfg.site_dir / "archive.html").write_text(html, encoding="utf-8")
