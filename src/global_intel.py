"""Build the public RSS headline export alongside the static site."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

MAX_ITEMS = 500
MAX_AGE = timedelta(days=7)
MAX_TITLE = 512
MAX_SOURCE = 128
MAX_URL = 2048


def _is_https_url(url: str) -> bool:
    if len(url) > MAX_URL or any(c.isspace() or ord(c) < 32 or c in "\\\x7f" for c in url):
        return False
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == "https" and parsed.hostname
                    and parsed.username is None and parsed.port != 0)
    except ValueError:
        return False


def write_global_intel(rows: Iterable[sqlite3.Row], site_dir: Path, now: datetime) -> None:
    cutoff = now - MAX_AGE
    eligible = []
    for row in rows:
        title, source, url = row["title"], row["source"], row["url"]
        if (not title or not title.strip() or len(title) > MAX_TITLE
                or not source or not source.strip() or len(source) > MAX_SOURCE
                or not _is_https_url(url)):
            continue
        try:
            published = datetime.fromisoformat(row["published"] or "")
            if published.tzinfo is None:
                continue
            published = published.astimezone(UTC)
        except (ValueError, OverflowError):
            continue
        if not cutoff <= published <= now:
            continue
        item = {"title": title, "source": source, "url": url, "published": published.isoformat()}
        if row["language"] in {"en", "th"}:
            item["language"] = row["language"]
        eligible.append((published, item))

    eligible.sort(key=lambda pair: (pair[0], pair[1]["url"]), reverse=True)
    items = [item for _, item in eligible[:MAX_ITEMS]]
    canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = {"schema": 1, "editionId": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
               "generatedAt": now.isoformat(), "items": items}
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "global-intel.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8",
    )
