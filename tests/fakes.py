"""Offline stand-ins for LLM providers, feeds and HTTP used across tests."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.config import Config

_ARTICLE = re.compile(r"### ARTICLE (\d+)\nTITLE: (.*)")


def response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def summary_for(title: str, **over) -> dict:
    base = {"headline": f"Summary: {title}", "bullets": ["point one", "point two"],
            "topic": "Markets", "sentiment": "bullish", "importance": 4,
            "instruments": ["DXY"]}
    base.update(over)
    return base


class FakeLLM:
    """Callable replacement for litellm.completion.

    Answers single-article and batch prompts with well-formed JSON. Per-model
    behaviour can be overridden: `errors[model]` is an exception (or list of
    them, consumed in order) to raise; `think=True` wraps output in <think>.
    """

    def __init__(self, errors: dict | None = None, think: bool = False,
                 drop_ids: set[int] | None = None) -> None:
        self.errors = errors or {}
        self.think = think
        self.drop_ids = drop_ids or set()
        self.calls: list[dict] = []

    def __call__(self, model: str, messages: list[dict], **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        err = self.errors.get(model)
        if isinstance(err, list):
            err = err.pop(0) if err else None
        if err is not None:
            raise err
        user = messages[1]["content"]
        found = _ARTICLE.findall(user)
        if found:
            body = {"items": [{"id": int(i), **summary_for(t)} for i, t in found
                              if int(i) not in self.drop_ids]}
        elif "top stories" in user:
            body = {"mood": "Risk-on as the dollar firms."}
        else:
            title = user.split("\n", 1)[0].removeprefix("TITLE: ")
            body = summary_for(title)
        text = json.dumps(body)
        if self.think:
            text = f"<think>\nreasoning about {{ the article }}\n</think>\n\n```json\n{text}\n```"
        return response(text)


def make_config(root: Path, **over) -> Config:
    cfg = Config(
        db_path=root / "test.db", site_dir=root / "site", site_title="Test Brief",
        llm_chain=["test/primary", "test/backup"], max_input_chars=6000,
        max_articles_per_run=0, feeds=[], summary_batch_size=3, llm_concurrency=2,
        summary_max_attempts=3, summary_max_age_days=7,
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class TempDir:
    def __enter__(self) -> Path:
        self._td = tempfile.TemporaryDirectory()
        return Path(self._td.name)

    def __exit__(self, *exc) -> None:
        self._td.cleanup()


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Fake</title>
{items}
</channel></rss>"""

ITEM = """<item><title>{title}</title><link>{link}</link>
<pubDate>{date}</pubDate><description>{desc}</description></item>"""


def rss(items: list[dict]) -> bytes:
    return RSS.format(items="\n".join(ITEM.format(**i) for i in items)).encode()


def http_response(content: bytes = b"", status: int = 200,
                  ctype: str = "application/rss+xml") -> SimpleNamespace:
    def raise_for_status():
        if status >= 400:
            import requests
            raise requests.HTTPError(f"{status} error")
    return SimpleNamespace(content=content, text=content.decode("utf-8", "replace"),
                           status_code=status, headers={"content-type": ctype},
                           raise_for_status=raise_for_status)
