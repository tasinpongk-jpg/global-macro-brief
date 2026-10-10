from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import litellm

from src import summarize as S
from tests.fakes import FakeLLM, response

RATE = litellm.RateLimitError("Rate limit exceeded", llm_provider="x", model="m")
DAILY = litellm.RateLimitError(
    "Quota exceeded for metric generate_requests_per_day: GenerateRequestsPerDay",
    llm_provider="gemini", model="m")
AUTH = litellm.AuthenticationError("bad key", llm_provider="x", model="m")
PAYMENT = litellm.APIError(402, "Payment required to access this resource",
                           llm_provider="cerebras", model="m")
MISSING = litellm.NotFoundError("model_not_found", model="m", llm_provider="groq")


def articles(n: int) -> list[dict]:
    return [{"id": i, "title": f"Story {i}", "text": f"Body {i}", "feed_topic": "Markets"}
            for i in range(1, n + 1)]


class ParseJsonTests(unittest.TestCase):
    def test_strips_think_block_and_fences(self) -> None:
        raw = '<think>\nplan {"no": 1}\n</think>\n```json\n{"a": 1}\n```'
        self.assertEqual(S.parse_json(raw), {"a": 1})

    def test_extracts_object_from_surrounding_prose(self) -> None:
        self.assertEqual(S.parse_json('Sure! {"a": [1, 2]} hope that helps'), {"a": [1, 2]})

    def test_unterminated_think_is_an_error(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            S.parse_json('<think>still reasoning {"a": 1}')


class ClassifyErrorTests(unittest.TestCase):
    def test_classification(self) -> None:
        self.assertEqual(S.classify_error(AUTH), "fatal")
        self.assertEqual(S.classify_error(PAYMENT), "fatal")
        self.assertEqual(S.classify_error(MISSING), "fatal")
        self.assertEqual(S.classify_error(DAILY), "fatal")
        self.assertEqual(S.classify_error(RATE), "rate")
        self.assertEqual(S.classify_error(RuntimeError("socket timeout")), "transient")
        self.assertEqual(S.classify_error(RuntimeError("[Errno 111] Connection refused")),
                         "fatal")


class ProviderPoolTests(unittest.TestCase):
    def test_skips_providers_without_credentials_and_ollama_on_ci(self) -> None:
        env = {"MINIMAX_API_KEY": "k", "CI": "true", "CLOUDFLARE_API_KEY": "k"}
        with patch.dict("os.environ", env, clear=True):
            pool = S.ProviderPool(["minimax/MiniMax-M2", "gemini/gemini-2.5-flash",
                                   "cloudflare/@cf/x", "ollama/qwen2.5"])
        self.assertEqual(pool.chain, ["minimax/MiniMax-M2"])
        self.assertEqual(len(pool.skipped), 3)  # cloudflare needs an account id too

    def test_rate_limits_cool_down_then_disable(self) -> None:
        sleeps: list[float] = []
        pool = S.ProviderPool(["test/a"], max_rate_strikes=3, sleep=sleeps.append)
        pool.failure("test/a", RATE)
        self.assertTrue(pool.is_cooling("test/a"))
        pool.failure("test/a", RATE)
        self.assertFalse(pool.exhausted)
        pool.failure("test/a", RATE)
        self.assertTrue(pool.exhausted)

    def test_success_resets_strikes(self) -> None:
        pool = S.ProviderPool(["test/a"], max_transient_strikes=2)
        pool.failure("test/a", RuntimeError("blip"))
        pool.success("test/a")
        pool.failure("test/a", RuntimeError("blip"))
        self.assertFalse(pool.exhausted)


class SummarizeTests(unittest.TestCase):
    def test_dead_provider_is_called_once_per_run(self) -> None:
        fake = FakeLLM(errors={"test/a": AUTH})
        pool = S.ProviderPool(["test/a", "test/b"])
        with patch.object(S.litellm, "completion", fake):
            for i in range(5):
                res = S.summarize(f"T{i}", "body", "Markets", pool=pool)
                self.assertEqual(res["llm_model"], "test/b")
        self.assertEqual([c["model"] for c in fake.calls].count("test/a"), 1)

    def test_raises_when_everything_is_exhausted(self) -> None:
        fake = FakeLLM(errors={"test/a": AUTH, "test/b": PAYMENT})
        pool = S.ProviderPool(["test/a", "test/b"])
        with patch.object(S.litellm, "completion", fake):
            with self.assertRaises(S.AllProvidersExhausted):
                S.summarize("T", "body", "Markets", pool=pool)
            self.assertIsNone(S.summarize_batch(articles(3), pool))
        self.assertEqual(len(fake.calls), 2)

    def test_bad_json_is_retried_once_on_same_provider(self) -> None:
        good = json.dumps({"headline": "H", "bullets": ["b"], "topic": "Markets"})
        replies = iter([response('{"headline": "cut off'), response(good)])
        pool = S.ProviderPool(["test/a", "test/b"])
        with patch.object(S.litellm, "completion", lambda **kw: next(replies)):
            res = S.summarize("T", "body", "Markets", pool=pool)
        self.assertEqual(res["headline"], "H")
        self.assertEqual(res["llm_model"], "test/a")

    def test_think_output_is_parsed(self) -> None:
        pool = S.ProviderPool(["test/a"])
        with patch.object(S.litellm, "completion", FakeLLM(think=True)):
            res = S.summarize("Oil up", "body", "Energy/Oil", pool=pool)
        self.assertEqual(res["headline"], "Summary: Oil up")

    def test_gemini_gets_thinking_disabled_and_minimax_reasoning_headroom(self) -> None:
        gem = S._call_kwargs("gemini/gemini-2.5-flash", 1000, 0.2)
        mm = S._call_kwargs("minimax/MiniMax-M2", 1000, 0.2)
        self.assertEqual(gem["reasoning_effort"], "disable")
        self.assertNotIn("reasoning_effort", mm)
        self.assertGreater(mm["max_tokens"], gem["max_tokens"])

    def test_batch_returns_partial_results_by_id(self) -> None:
        pool = S.ProviderPool(["test/a"])
        with patch.object(S.litellm, "completion", FakeLLM(drop_ids={2})):
            res = S.summarize_batch(articles(3), pool)
        self.assertEqual(sorted(res), [1, 3])
        self.assertEqual(res[3]["headline"], "Summary: Story 3")
        self.assertEqual(res[1]["llm_model"], "test/a")


if __name__ == "__main__":
    unittest.main()
