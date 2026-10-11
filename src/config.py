"""Configuration loading from .env and config/feeds.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Topic display order for the rendered site.
TOPIC_ORDER = [
    "Markets",
    "Macro/Economy",
    "Central Banks",
    "Energy/Oil",
    "Gold/Metals",
    "Crypto",
    "Geopolitics",
    "Tech/AI",
    "Companies",
    "Thai Markets",
    "Other",
]


@dataclass
class Feed:
    name: str
    url: str
    topic: str = "Other"


@dataclass
class Config:
    db_path: Path
    site_dir: Path
    site_title: str
    llm_chain: list[str]
    max_input_chars: int
    max_articles_per_run: int
    feeds: list[Feed] = field(default_factory=list)
    # Articles per LLM request (1 = one request per article).
    summary_batch_size: int = 5
    # Parallel LLM requests (each worker also does its own full-text fetches).
    llm_concurrency: int = 3
    # Give up on an article after this many failed summarization attempts...
    summary_max_attempts: int = 3
    # ...or once it is older than this; it is then shown by title only.
    summary_max_age_days: int = 7


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


# Default fallback chain, best first. MiniMax-M2 is the workhorse; Gemini Flash
# (thinking disabled) and Mistral are free-tier fallbacks; Ollama is local-only
# and skipped on CI. Providers without credentials are skipped automatically.
DEFAULT_LLM_CHAIN = (
    "minimax/MiniMax-M2,gemini/gemini-2.5-flash,"
    "mistral/mistral-small-latest,ollama/qwen2.5"
)


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    """Integer env var; blank/invalid values fall back to the default."""
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def load_config() -> Config:
    load_dotenv(ROOT / ".env")

    chain = [m.strip() for m in (os.getenv("LLM_CHAIN") or DEFAULT_LLM_CHAIN)
             .split(",") if m.strip()]

    feeds_file = ROOT / "config" / "feeds.yaml"
    raw = yaml.safe_load(feeds_file.read_text(encoding="utf-8"))
    feeds = [Feed(**f) for f in raw.get("feeds", [])]

    return Config(
        db_path=_resolve(os.getenv("DB_PATH") or "news.db"),
        site_dir=_resolve(os.getenv("SITE_DIR") or "site"),
        site_title=os.getenv("SITE_TITLE") or "Daily Global-Macro Brief",
        llm_chain=chain,
        max_input_chars=_int_env("MAX_INPUT_CHARS", 6000, minimum=500),
        max_articles_per_run=_int_env("MAX_ARTICLES_PER_RUN", 0),
        feeds=feeds,
        summary_batch_size=_int_env("SUMMARY_BATCH_SIZE", 5, minimum=1),
        llm_concurrency=_int_env("LLM_CONCURRENCY", 3, minimum=1),
        summary_max_attempts=_int_env("SUMMARY_MAX_ATTEMPTS", 3, minimum=1),
        summary_max_age_days=_int_env("SUMMARY_MAX_AGE_DAYS", 7, minimum=1),
    )
