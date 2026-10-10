"""Shared HTTP helpers: one User-Agent, explicit timeouts, robots.txt checks."""
from __future__ import annotations

import logging
import threading
from urllib import robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; GlobalMacroBrief/1.0; "
    "+https://github.com/tasinpongk-jpg/global-macro-brief) personal-non-commercial"
)
ROBOTS_AGENT = "GlobalMacroBrief"
# (connect, read) seconds. Every network call in the pipeline goes through here,
# so one slow host can never hang the daily run.
TIMEOUT = (10, 20)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

_robots: dict[str, robotparser.RobotFileParser | None] = {}
_robots_lock = threading.Lock()


def get(url: str, **kwargs) -> requests.Response:
    """GET with the project User-Agent and a hard timeout. Raises on HTTP error."""
    kwargs.setdefault("timeout", TIMEOUT)
    resp = _session.get(url, **kwargs)
    resp.raise_for_status()
    return resp


def _load_robots(origin: str) -> robotparser.RobotFileParser | None:
    """Fetch and parse origin/robots.txt. None means "no rules" (allow all)."""
    try:
        resp = _session.get(f"{origin}/robots.txt", timeout=TIMEOUT)
    except requests.RequestException as e:
        log.debug("robots.txt unreachable for %s: %s", origin, e)
        return None
    if resp.status_code in (401, 403):
        rp = robotparser.RobotFileParser()
        rp.disallow_all = True  # per RFC 9309 an auth wall means "keep out"
        return rp
    if resp.status_code >= 400:
        return None
    rp = robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp


def allowed(url: str) -> bool:
    """True if robots.txt permits fetching `url` (cached per origin)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        cached = origin in _robots
        rp = _robots.get(origin)
    if not cached:
        rp = _load_robots(origin)
        with _robots_lock:
            _robots[origin] = rp
    return rp is None or rp.can_fetch(ROBOTS_AGENT, url)
