"""SQLite storage layer."""
from __future__ import annotations

import sqlite3
from pathlib import Path

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
    llm_model     TEXT
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


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn
