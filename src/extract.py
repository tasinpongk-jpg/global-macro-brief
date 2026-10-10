"""Full-text extraction cascade: trafilatura -> readability-lxml.

Pages are fetched once with the project User-Agent and a hard timeout (see
`net.py`), and only when robots.txt allows it. newspaper4k / Playwright are
documented as further fallbacks but kept out of the default dependency set.
"""
from __future__ import annotations

import logging

import trafilatura
from readability import Document

from . import net

log = logging.getLogger(__name__)

MIN_CHARS = 200  # shorter than this is a teaser/paywall stub, not an article


def _via_trafilatura(html: str) -> str:
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        return (text or "").strip()
    except Exception as e:  # noqa: BLE001
        log.debug("trafilatura failed: %s", e)
        return ""


def _via_readability(html: str) -> str:
    try:
        summary_html = Document(html).summary(html_partial=True)
        return (trafilatura.extract(summary_html) or "").strip()
    except Exception as e:  # noqa: BLE001
        log.debug("readability failed: %s", e)
        return ""


def extract_text(url: str) -> str:
    """Best-effort full article text. Returns '' on failure (never raises)."""
    try:
        if not net.allowed(url):
            log.debug("robots.txt disallows %s", url)
            return ""
        html = net.get(url).text
    except Exception as e:  # noqa: BLE001
        log.debug("fetch failed for %s: %s", url, e)
        return ""

    text = _via_trafilatura(html)
    if len(text) > MIN_CHARS:
        return text
    return _via_readability(html) or text
