"""Daily "macro mood" line for the TL;DR hero.

Generates ONE LLM sentence per day summarizing the day's tone and stores it in
the `digests` table. The whole step is wrapped so any failure is non-fatal — the
hero then falls back to the mechanical top-5 list with no mood line.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import Config
from .render import _day_key
from .summarize import complete_json

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a markets editor. Given the day's top global-macro headlines, write "
    "ONE punchy sentence (<=140 chars) capturing the overall market mood and the "
    "one or two dominant drivers. No preamble, no hedging. "
    'Return STRICT JSON: {"mood": "..."}'
)


def _latest_day_stories(conn):
    """The most recent day's top summarized stories (by importance)."""
    rows = conn.execute(
        "SELECT published, fetched_at, headline, importance, sentiment "
        "FROM articles WHERE summarized = 1 "
        "ORDER BY COALESCE(published, fetched_at) DESC LIMIT 250"
    ).fetchall()
    if not rows:
        return None, []
    day = _day_key(rows[0]["published"] or rows[0]["fetched_at"])
    todays = [r for r in rows
              if _day_key(r["published"] or r["fetched_at"]) == day]
    todays.sort(key=lambda r: (r["importance"] or 3), reverse=True)
    return day, todays[:12]


def generate_digest(conn, cfg: Config) -> None:
    """Write the latest day's mood line if not already done. One LLM call/day."""
    try:
        day, stories = _latest_day_stories(conn)
        if not day or not stories:
            return
        if conn.execute("SELECT 1 FROM digests WHERE day = ?", (day,)).fetchone():
            return  # already generated for this day — cap at one call/day
        lines = "\n".join(
            f"- [{s['importance'] or 3}/5 {s['sentiment'] or 'neutral'}] {s['headline']}"
            for s in stories
        )
        result = complete_json(_SYSTEM, f"Date {day} top stories:\n{lines}",
                               cfg.llm_chain)
        mood = ((result or {}).get("mood") or "").strip()
        if not mood:
            log.warning("Digest: no mood produced for %s", day)
            return
        conn.execute(
            "INSERT OR REPLACE INTO digests (day, mood, generated_at) VALUES (?,?,?)",
            (day, mood[:200], datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        log.info("Digest mood for %s: %s", day, mood)
    except Exception as e:  # noqa: BLE001 — never break the pipeline
        log.error("Digest step failed (non-fatal): %s", e)
