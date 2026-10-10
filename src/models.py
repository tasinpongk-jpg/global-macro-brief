"""SQLite storage layer."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# VACUUM when at least this fraction of the file is free pages. Clearing
# raw_text leaves holes that SQLite only returns to the OS on VACUUM.
VACUUM_FREE_RATIO = 0.20

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash      TEXT UNIQUE NOT NULL,
    norm_title    TEXT,
    url           TEXT NOT NULL,
    title         TEXT,
    source        TEXT,
    feed_topic    TEXT,
    published     TEXT,            -- ISO8601
    fetched_at    TEXT NOT NULL,   -- ISO8601
    raw_text      TEXT,
    -- summary fields (populated after LLM pass) --
    summarized    INTEGER NOT NULL DEFAULT 0,
    headline      TEXT,
    bullets       TEXT,            -- JSON array
    topic         TEXT,
    sentiment     TEXT,
    instruments   TEXT,            -- JSON array
    importance    INTEGER DEFAULT 3,  -- 1 (minor) .. 5 (market-moving)
    llm_model     TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0  -- failed summarization tries
);
CREATE INDEX IF NOT EXISTS idx_articles_norm_title ON articles(norm_title);
CREATE INDEX IF NOT EXISTS idx_articles_published  ON articles(published);
CREATE INDEX IF NOT EXISTS idx_articles_summarized ON articles(summarized);

-- One row per day: the LLM-written "macro mood" sentence for the TL;DR hero.
CREATE TABLE IF NOT EXISTS digests (
    day          TEXT PRIMARY KEY,   -- YYYY-MM-DD (UTC)
    mood         TEXT,
    generated_at TEXT NOT NULL       -- ISO8601
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)  # wait up to 30s on a lock
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema version (idempotent)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
    if "importance" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN importance INTEGER DEFAULT 3")
        conn.commit()
    if "attempts" not in cols:
        conn.execute(
            "ALTER TABLE articles ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def compact_db(conn: sqlite3.Connection, force_vacuum: bool = False,
               stale_before: str | None = None,
               max_attempts: int | None = None) -> dict:
    """Keep the DB small enough to back up (GitHub rejects files > 100 MB).

    Full article text is only needed as LLM input, so it is dropped once an
    article has a summary — or has been given up on (older than `stale_before`
    or failed `max_attempts` times), since it will never be summarized then.
    The freed pages are reclaimed with VACUUM when they
    make up a meaningful share of the file (or when forced), and the WAL is
    checkpointed so the single news.db file is complete for the snapshot.
    """
    cond, params = ["summarized = 1"], []
    if stale_before:
        cond.append("COALESCE(published, fetched_at) < ?")
        params.append(stale_before)
    if max_attempts:
        cond.append("attempts >= ?")
        params.append(max_attempts)
    cleared = conn.execute(
        "UPDATE articles SET raw_text = NULL "
        f"WHERE raw_text IS NOT NULL AND ({' OR '.join(cond)})", params
    ).rowcount
    conn.commit()

    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    vacuumed = False
    if force_vacuum or (pages and free / pages >= VACUUM_FREE_RATIO):
        conn.execute("VACUUM")
        vacuumed = True
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    size = conn.execute("PRAGMA page_count").fetchone()[0] * page_size
    log.info("DB compact: cleared raw_text on %d rows, vacuum=%s, size=%.1f MB",
             cleared, vacuumed, size / 1e6)
    return {"cleared": cleared, "vacuumed": vacuumed, "size_bytes": size,
            "before_bytes": pages * page_size}
