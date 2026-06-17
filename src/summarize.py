"""LLM summarization via LiteLLM with a provider fallback chain.

Returns structured JSON: {headline, bullets[], topic, sentiment, instruments[]}.
Providers are tried in order; a provider with no API key configured is skipped.
"""
from __future__ import annotations

import json
import logging
import os
import re

import litellm

from .config import TOPIC_ORDER

log = logging.getLogger(__name__)
litellm.drop_params = True  # ignore params a given provider doesn't support

# Which env var must be present for a provider prefix to be usable.
_KEY_FOR_PREFIX = {
    "gemini/": "GEMINI_API_KEY",
    "groq/": "GROQ_API_KEY",
    "cerebras/": "CEREBRAS_API_KEY",
    "mistral/": "MISTRAL_API_KEY",
    "cloudflare/": "CLOUDFLARE_API_KEY",  # also needs CLOUDFLARE_ACCOUNT_ID
    "ollama/": None,  # local, no key needed
}

_SYSTEM = (
    "You are a financial-news editor producing a terse global-macro brief. "
    "Summarize the article as STRICT JSON with keys: "
    "headline (string, <=120 chars, neutral, no clickbait), "
    "bullets (array of 3-5 strings, each a concise key takeaway with the "
    "specific number/level where relevant), "
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
    "Return ONLY the JSON object, no prose, no markdown fences."
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _provider_available(model: str) -> bool:
    for prefix, env_key in _KEY_FOR_PREFIX.items():
        if model.startswith(prefix):
            return env_key is None or bool(os.getenv(env_key))
    return True  # unknown prefix — let LiteLLM decide


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


def complete_json(system: str, user: str, chain: list[str],
                  max_tokens: int = 300) -> dict | None:
    """Generic JSON completion over the provider fallback chain (used by digest).

    Returns the first successfully-parsed JSON object, or None if all fail.
    """
    for model in (m for m in chain if _provider_available(m)):
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=0.3, max_tokens=max_tokens,
                response_format={"type": "json_object"}, num_retries=2,
            )
            content = _FENCE.sub("", resp.choices[0].message.content or "").strip()
            return json.loads(content)
        except Exception as e:  # noqa: BLE001 — try next provider
            log.warning("complete_json %s failed: %s", model, e)
            continue
    return None


def summarize(title: str, text: str, feed_topic: str, chain: list[str]) -> dict | None:
    """Try each model in `chain`; return parsed summary + 'llm_model', or None."""
    prompt = (
        f"TITLE: {title}\n\nARTICLE:\n{text}\n\n"
        "Produce the JSON brief now."
    )
    usable = [m for m in chain if _provider_available(m)]
    if not usable:
        log.error("No usable LLM provider (no API keys set). Chain=%s", chain)
        return None

    for model in usable:
        try:
            resp = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=900,
                response_format={"type": "json_object"},
                # Retry transient rate-limit/timeout errors with backoff
                # (respects Retry-After) before falling through to the next
                # provider — free tiers have tight tokens-per-minute caps.
                num_retries=4,
            )
            content = resp.choices[0].message.content or ""
            content = _FENCE.sub("", content).strip()
            obj = json.loads(content)
            result = _coerce(obj, feed_topic)
            result["llm_model"] = model
            return result
        except json.JSONDecodeError as e:
            log.warning("Bad JSON from %s: %s", model, e)
            continue
        except Exception as e:  # noqa: BLE001 — quota/429/network → next provider
            log.warning("Provider %s failed: %s", model, e)
            continue

    log.error("All providers failed for: %s", title[:80])
    return None
