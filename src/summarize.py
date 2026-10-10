"""LLM summarization via LiteLLM with a provider fallback chain.

Returns structured JSON: {headline, bullets[], topic, sentiment, importance,
instruments[]}. Providers are tried in order; one with no credentials is
skipped. A per-run `ProviderPool` acts as a circuit breaker: providers that are
dead (auth/billing/missing model/daily quota) are dropped for the rest of the
run, rate-limited ones cool down, and once every provider is exhausted callers
stop instead of burning minutes on doomed retries.

Several articles can be summarized in one request (`summarize_batch`), which
multiplies throughput on request-capped free tiers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

import litellm

from .config import TOPIC_ORDER

log = logging.getLogger(__name__)
litellm.drop_params = True  # ignore params a given provider doesn't support
litellm.suppress_debug_info = True  # no "If you need to debug..." spam per error

# Env vars that must ALL be present for a provider prefix to be usable.
_KEYS_FOR_PREFIX: dict[str, tuple[str, ...]] = {
    "minimax/": ("MINIMAX_API_KEY",),
    "gemini/": ("GEMINI_API_KEY",),
    "mistral/": ("MISTRAL_API_KEY",),
    "groq/": ("GROQ_API_KEY",),
    "cerebras/": ("CEREBRAS_API_KEY",),
    "cloudflare/": ("CLOUDFLARE_API_KEY", "CLOUDFLARE_ACCOUNT_ID"),
    "ollama/": (),  # local, no key needed (skipped on CI, see below)
}

_RULES = (
    "headline (string, <=120 chars, neutral, no clickbait), "
    "bullets (array of 1-5 strings, each a concise key takeaway with the "
    "specific number/level where relevant; use fewer bullets when the text is "
    "short — never pad), "
    f"topic (EXACTLY one of: {', '.join(TOPIC_ORDER)} — classification rules: "
    "'Energy/Oil' = crude/WTI/Brent/natgas/OPEC; 'Gold/Metals' = gold/silver/"
    "copper/precious & base metals; 'Central Banks' = Fed/ECB/BoE/BoJ/rate "
    "decisions/monetary policy; 'Macro/Economy' = inflation/GDP/jobs/trade/"
    "tariffs/economic data; 'Geopolitics' = war/sanctions/elections/diplomacy; "
    "'Markets' = equity indices/bonds/FX/broad market moves; 'Crypto' = "
    "bitcoin/ethereum/stablecoins/digital assets/crypto regulation; 'Tech/AI' = "
    "AI/semiconductors/software/space/big-tech & technology developments; "
    "'Companies' = a single company's earnings/M&A/management/products (not a "
    "broad market move); 'Thai Markets' = Thailand/SET/THB; use 'Other' ONLY "
    "for genuinely off-topic items (sports/lifestyle/human-interest)), "
    "sentiment (one of: bullish, bearish, neutral, mixed — for the asset/market "
    "the story is about), "
    "importance (integer 1-5: 5 = market-moving/global; 4 = significant; "
    "3 = notable; 2 = routine; 1 = minor/filler), "
    "instruments (array of affected tickers/assets, e.g. WTI, Brent, XAU, DXY, "
    "US10Y, SET; empty array if none). "
    "Use ONLY facts stated in the given article text: never add outside "
    "knowledge or facts from any other article."
)

_SYSTEM = (
    "You are a financial-news editor producing a terse global-macro brief. "
    "Summarize the article as STRICT JSON with keys: " + _RULES +
    " Return ONLY the JSON object, no prose, no markdown fences."
)

_SYSTEM_BATCH = (
    "You are a financial-news editor producing a terse global-macro brief. "
    "You will receive several articles, each introduced by a line '### ARTICLE "
    "<id>'. Summarize EACH article independently. Return STRICT JSON of the form "
    '{"items": [{"id": <id>, ...}, ...]} with exactly one item per article, '
    "where every item has the integer id plus these keys: " + _RULES +
    " Return ONLY the JSON object, no prose, no markdown fences."
)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Per-article output budget, plus headroom for providers whose hidden
# reasoning tokens count against max_tokens (MiniMax-M2 always reasons).
_TOKENS_PER_ITEM = 450
_REASONING_HEADROOM = {"minimax/": 3000}


class AllProvidersExhausted(RuntimeError):
    """Every provider in the chain is dead for the rest of this run."""


# ── Provider availability & error classification ────────────────────────────

def _provider_available(model: str) -> bool:
    for prefix, env_keys in _KEYS_FOR_PREFIX.items():
        if model.startswith(prefix):
            if prefix == "ollama/" and os.getenv("CI") and not os.getenv("OLLAMA_API_BASE"):
                return False  # no Ollama daemon on CI runners
            return all(os.getenv(k) for k in env_keys)
    return True  # unknown prefix — let LiteLLM decide


# Messages that mean "this provider will not work again today".
_FATAL_MARKERS = (
    "payment required", "billing", "insufficient balance", "insufficient_quota",
    "model_not_found", "does not exist", "invalid api key", "api key not valid",
    "authentication", "unauthorized", "permission denied", "perday",
    "per day", "daily limit", "connection refused",
)


def classify_error(exc: BaseException) -> str:
    """'fatal' (drop provider for the run), 'rate' (cool down) or 'transient'."""
    if isinstance(exc, (litellm.AuthenticationError, litellm.NotFoundError,
                        litellm.PermissionDeniedError)):
        return "fatal"
    msg = str(exc).lower().replace("_", "").replace("-", "")
    if any(m.replace("_", "").replace("-", "") in msg for m in _FATAL_MARKERS):
        return "fatal"
    if isinstance(exc, litellm.RateLimitError) or "429" in msg or "rate limit" in msg:
        return "rate"
    return "transient"


class ProviderPool:
    """Per-run circuit breaker over the fallback chain. Thread-safe."""

    def __init__(self, chain: list[str], max_rate_strikes: int = 4,
                 max_transient_strikes: int = 3, base_cooldown: float = 20.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.chain = [m for m in chain if _provider_available(m)]
        self.skipped = [m for m in chain if m not in self.chain]
        self.max_rate_strikes = max_rate_strikes
        self.max_transient_strikes = max_transient_strikes
        self.base_cooldown = base_cooldown
        self._sleep = sleep
        self._lock = threading.Lock()
        self.dead: dict[str, str] = {}
        self._strikes: Counter[str] = Counter()
        self._cool_until: dict[str, float] = {}
        self.ok: Counter[str] = Counter()
        self.failed: Counter[str] = Counter()

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return all(m in self.dead for m in self.chain)

    def alive(self) -> list[str]:
        with self._lock:
            return [m for m in self.chain if m not in self.dead]

    def wait_if_cooling(self, model: str) -> None:
        with self._lock:
            delay = self._cool_until.get(model, 0.0) - time.monotonic()
        if delay > 0:
            self._sleep(delay)

    def is_cooling(self, model: str) -> bool:
        with self._lock:
            return self._cool_until.get(model, 0.0) > time.monotonic()

    def success(self, model: str) -> None:
        with self._lock:
            self._strikes[model] = 0
            self.ok[model] += 1

    def failure(self, model: str, exc: BaseException) -> str:
        kind = classify_error(exc)
        with self._lock:
            self.failed[model] += 1
            if model in self.dead:
                return kind
            self._strikes[model] += 1
            n = self._strikes[model]
            if kind == "fatal":
                self.dead[model] = str(exc)[:200]
            elif kind == "rate":
                if n >= self.max_rate_strikes:
                    self.dead[model] = f"rate-limited {n}x in a row"
                else:  # exponential cooldown: 20s, 40s, 80s ...
                    self._cool_until[model] = (time.monotonic()
                                               + self.base_cooldown * 2 ** (n - 1))
            elif n >= self.max_transient_strikes:
                self.dead[model] = f"{n} consecutive errors: {str(exc)[:150]}"
            if model in self.dead:
                log.warning("Provider %s disabled for this run (%s)", model,
                            self.dead[model])
        return kind

    def report(self) -> str:
        parts = [f"{m}: ok={self.ok[m]} failed={self.failed[m]}"
                 + (" [disabled]" if m in self.dead else "") for m in self.chain]
        return "; ".join(parts) or "no usable providers"


# ── Low-level completion with JSON parsing ──────────────────────────────────

def parse_json(content: str) -> Any:
    """Parse model output into JSON, tolerating <think> blocks and fences."""
    text = _THINK.sub("", content or "")
    if "<think>" in text.lower():  # unterminated reasoning = truncated output
        raise json.JSONDecodeError("unterminated <think> block", text, 0)
    text = _FENCE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _call_kwargs(model: str, max_tokens: int, temperature: float) -> dict:
    for prefix, extra in _REASONING_HEADROOM.items():
        if model.startswith(prefix):
            max_tokens += extra
    kw: dict[str, Any] = {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        # One quick in-provider retry for blips; sustained failures are handled
        # by the pool (cooldown / disable) rather than long internal backoff.
        "num_retries": 1,
        "timeout": 180,
    }
    if model.startswith("gemini/"):
        # Gemini 2.5 "thinking" tokens count against max_tokens and were
        # truncating the JSON mid-string. A summary does not need them.
        kw["reasoning_effort"] = "disable"
    return kw


def _complete(pool: ProviderPool, system: str, user: str, max_tokens: int,
              validate: Callable[[Any], Any], temperature: float = 0.2):
    """Run one request through the chain. Returns (value, model) or (None, None).

    `validate` turns parsed JSON into the result (raise ValueError to reject).
    A bad-JSON/invalid reply is retried once on the same provider before
    falling through. Raises AllProvidersExhausted if nothing is left to try.
    """
    if not pool.alive():
        raise AllProvidersExhausted(pool.report())
    for model in pool.alive():
        if pool.is_cooling(model) and any(not pool.is_cooling(m)
                                          for m in pool.alive() if m != model):
            continue  # a healthier provider is available right now
        pool.wait_if_cooling(model)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        for attempt in range(2):
            try:
                resp = litellm.completion(
                    model=model, messages=messages,
                    **_call_kwargs(model, max_tokens, temperature),
                )
            except Exception as e:  # noqa: BLE001 — quota/429/network → next
                kind = pool.failure(model, e)
                log.warning("Provider %s failed (%s): %s", model, kind,
                            str(e).splitlines()[0][:240])
                break
            content = resp.choices[0].message.content or ""
            try:
                value = validate(parse_json(content))
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                log.warning("Bad JSON from %s (attempt %d): %s", model,
                            attempt + 1, str(e)[:160])
                if attempt == 0:
                    messages = messages + [
                        {"role": "assistant", "content": content[-2000:]},
                        {"role": "user", "content":
                         "That was not valid/complete JSON. Reply again with "
                         "ONLY the complete JSON object."},
                    ]
                continue
            pool.success(model)
            return value, model
    if not pool.alive():
        raise AllProvidersExhausted(pool.report())
    return None, None


# ── Public API ──────────────────────────────────────────────────────────────

def _coerce(obj: dict, feed_topic: str) -> dict:
    bullets = obj.get("bullets") or []
    if isinstance(bullets, str):
        bullets = [bullets]
    topic = obj.get("topic") if obj.get("topic") in TOPIC_ORDER else (feed_topic or "Other")
    sentiment = (obj.get("sentiment") or "neutral").lower()
    if sentiment not in {"bullish", "bearish", "neutral", "mixed"}:
        sentiment = "neutral"
    instruments = obj.get("instruments") or []
    if isinstance(instruments, str):
        instruments = [instruments]
    try:
        importance = int(obj.get("importance", 3))
    except (TypeError, ValueError):
        importance = 3
    importance = max(1, min(5, importance))
    return {
        "headline": (obj.get("headline") or "").strip(),
        "bullets": [str(b).strip() for b in bullets if str(b).strip()][:5],
        "topic": topic,
        "sentiment": sentiment,
        "importance": importance,
        "instruments": [str(i).strip() for i in instruments if str(i).strip()][:8],
    }


def _check_summary(obj: Any, feed_topic: str) -> dict:
    if not isinstance(obj, dict):
        raise ValueError("summary is not a JSON object")
    result = _coerce(obj, feed_topic)
    if not result["headline"] and not result["bullets"]:
        raise ValueError("summary has neither headline nor bullets")
    return result


def _require_dict(obj: Any) -> dict:
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    return obj


def summarize_batch(articles: list[dict], pool: ProviderPool) -> dict[int, dict] | None:
    """Summarize several articles in one request.

    `articles`: dicts with id, title, text, feed_topic. Returns {id: result}
    (may be partial if the model skipped some), {} if every provider failed
    on this batch, or None if no provider was left to try. Each result carries
    'llm_model'.
    """
    if not articles:
        return {}
    if len(articles) == 1:
        a = articles[0]
        try:
            res = summarize(a["title"], a["text"], a["feed_topic"], pool=pool)
        except AllProvidersExhausted:
            return None
        return {a["id"]: res} if res else {}

    by_id = {int(a["id"]): a for a in articles}
    user = "\n\n".join(
        f"### ARTICLE {a['id']}\nTITLE: {a['title']}\n\n{a['text']}" for a in articles
    ) + f"\n\nProduce the JSON with {len(articles)} items now."

    def validate(obj: Any) -> dict[int, dict]:
        items = obj.get("items") if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            raise ValueError("no 'items' array")
        out: dict[int, dict] = {}
        for it in items:
            try:
                aid = int(it.get("id"))
            except (AttributeError, TypeError, ValueError):
                continue
            if aid in by_id and aid not in out:
                try:
                    out[aid] = _check_summary(it, by_id[aid]["feed_topic"])
                except ValueError:
                    continue
        if not out:
            raise ValueError("no usable items in batch reply")
        return out

    try:
        value, model = _complete(pool, _SYSTEM_BATCH, user,
                                 _TOKENS_PER_ITEM * len(articles) + 300, validate)
    except AllProvidersExhausted:
        return None
    if value is None:
        log.error("All providers failed for a batch of %d (first: %s)",
                  len(articles), articles[0]["title"][:60])
        return {}
    for res in value.values():
        res["llm_model"] = model
    return value


def summarize(title: str, text: str, feed_topic: str, chain: list[str] | None = None,
              pool: ProviderPool | None = None) -> dict | None:
    """Summarize one article; return parsed summary + 'llm_model', or None.

    Raises AllProvidersExhausted when a shared `pool` has nothing left.
    """
    if pool is None:
        pool = ProviderPool(chain or [])
        if not pool.chain:
            log.error("No usable LLM provider (no API keys set). Chain=%s", chain)
            return None
    prompt = f"TITLE: {title}\n\nARTICLE:\n{text}\n\nProduce the JSON brief now."
    value, model = _complete(pool, _SYSTEM, prompt, 1024,
                             lambda obj: _check_summary(obj, feed_topic))
    if value is None:
        log.error("All providers failed for: %s", title[:80])
        return None
    value["llm_model"] = model
    return value


def complete_json(system: str, user: str, chain: list[str] | None = None,
                  max_tokens: int = 300, pool: ProviderPool | None = None) -> dict | None:
    """Generic JSON completion over the provider fallback chain (used by digest).

    Returns the first successfully-parsed JSON object, or None if all fail.
    """
    pool = pool or ProviderPool(chain or [])
    try:
        value, _ = _complete(pool, system, user, max_tokens, _require_dict,
                             temperature=0.3)
    except AllProvidersExhausted:
        return None
    return value
