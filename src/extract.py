"""Full-text extraction cascade: trafilatura -> readability-lxml.

newspaper4k / Playwright are documented as further fallbacks but kept out of
the default dependency set to stay light. Add them here if a source needs JS.
"""
from __future__ import annotations

import logging

import requests
import trafilatura
from readability import Document

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MacroBriefBot/1.0; "
        "+https://github.com/your/repo) personal-non-commercial"
    )
}
_TIMEOUT = 20


def _via_readability(html: str) -> str:
    try:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
        # crude tag strip — good enough for an LLM input
        text = trafilatura.extract(summary_html) or ""
        return text.strip()
    except Exception as e:  # noqa: BLE001
        log.debug("readability failed: %s", e)
        return ""


def extract_text(url: str) -> str:
    """Best-effort full article text. Returns '' on failure (never raises)."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False
            )
            if text and len(text.strip()) > 200:
                return text.strip()
            # fall through to readability on the same HTML
            rt = _via_readability(downloaded)
            if rt:
                return rt
    except Exception as e:  # noqa: BLE001
        log.debug("trafilatura fetch failed for %s: %s", url, e)

    # Last resort: plain requests + readability
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return _via_readability(resp.text)
    except Exception as e:  # noqa: BLE001
        log.debug("requests/readability failed for %s: %s", url, e)
        return ""
