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
    "Energy/Oil",
    "Gold/Metals",
    "Central Banks",
    "Macro/Economy",
    "Geopolitics",
    "Markets",
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


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def load_config() -> Config:
    load_dotenv(ROOT / ".env")

    chain = [m.strip() for m in os.getenv(
        "LLM_CHAIN",
        "cerebras/gpt-oss-120b,groq/llama-3.1-8b-instant,"
        "gemini/gemini-2.5-flash,mistral/mistral-small-latest,ollama/qwen2.5",
    ).split(",") if m.strip()]

    feeds_file = ROOT / "config" / "feeds.yaml"
    raw = yaml.safe_load(feeds_file.read_text(encoding="utf-8"))
    feeds = [Feed(**f) for f in raw.get("feeds", [])]

    return Config(
        db_path=_resolve(os.getenv("DB_PATH", "news.db")),
        site_dir=_resolve(os.getenv("SITE_DIR", "site")),
        site_title=os.getenv("SITE_TITLE", "Daily Global-Macro Brief"),
        llm_chain=chain,
        max_input_chars=int(os.getenv("MAX_INPUT_CHARS", "6000")),
        max_articles_per_run=int(os.getenv("MAX_ARTICLES_PER_RUN", "0")),
        feeds=feeds,
    )
