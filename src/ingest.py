"""Feed ingestion + dedup. Parses RSS/Atom, normalizes, stores new articles."""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timezone

import feedparser
from dateutil import parser as dateparser

from .config import Config, Feed

log = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = _PUNCT.sub(" ", title.lower())
    return _WS.sub(" ", t).strip()


def _published_iso(entry) -> str | None:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                return dateparser.parse(val).astimezone(timezone.utc).isoformat()
            except Exception:  # noqa: BLE001
                continue
    if entry.get("published_parsed"):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            pass
    return None


def _entry_text(entry) -> str:
    """Text already present in the feed (often a teaser/summary)."""
    if entry.get("content"):
        return entry["content"][0].get("value", "")
    return entry.get("summary", "") or ""


def _is_dup(conn: sqlite3.Connection, uh: str, norm_title: str) -> bool:
    cur = conn.execute("SELECT 1 FROM articles WHERE url_hash = ? LIMIT 1", (uh,))
    if cur.fetchone():
        return True
    if norm_title:
        cur = conn.execute(
            "SELECT 1 FROM articles WHERE norm_title = ? LIMIT 1", (norm_title,)
        )
        if cur.fetchone():
            return True
    return False


def ingest_feed(conn: sqlite3.Connection, feed: Feed) -> int:
    parsed = feedparser.parse(feed.url)
    if parsed.bozo and not parsed.entries:
        log.warning("Feed failed: %s (%s)", feed.name, getattr(parsed, "bozo_exception", ""))
        return 0

    added = 0
    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        uh = url_hash(url)
        title = (entry.get("title") or "").strip()
        norm = normalize_title(title)
        if _is_dup(conn, uh, norm):
            continue
        try:
            conn.execute(
                """INSERT INTO articles
                   (url_hash, norm_title, url, title, source, feed_topic,
                    published, fetched_at, raw_text, summarized)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (uh, norm, url, title, feed.name, feed.topic,
                 _published_iso(entry), _now_iso(), _entry_text(entry)),
            )
            added += 1
        except sqlite3.IntegrityError:
            continue  # raced unique constraint
    conn.commit()
    log.info("%-26s +%d new (%d in feed)", feed.name, added, len(parsed.entries))
    return added


def ingest_all(conn: sqlite3.Connection, cfg: Config) -> int:
    total = 0
    for feed in cfg.feeds:
        try:
            total += ingest_feed(conn, feed)
        except Exception as e:  # noqa: BLE001 — never hard-fail the run on one feed
            log.error("Feed crashed: %s: %s", feed.name, e)
    log.info("Ingest complete: %d new articles", total)
    return total
