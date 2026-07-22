from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.cluster import cluster
from src.config import Config
from src.ingest import _published_iso, normalize_title, url_hash
from src.models import init_db
from src.render import render_site
from src.summarize import _coerce, complete_json


class IngestTests(unittest.TestCase):
    def test_est_timestamp_is_converted_to_utc(self) -> None:
        entry = {"published": "Mon, 20 Jul 2026 09:00:00 EST"}
        self.assertEqual(_published_iso(entry), "2026-07-20T14:00:00+00:00")

    def test_edt_timestamp_is_converted_to_utc(self) -> None:
        entry = {"published": "Mon, 20 Jul 2026 09:00:00 EDT"}
        self.assertEqual(_published_iso(entry), "2026-07-20T13:00:00+00:00")

    def test_naive_timestamp_uses_deterministic_utc_fallback(self) -> None:
        entry = {"published": "2026-07-20 09:00:00"}
        self.assertEqual(_published_iso(entry), "2026-07-20T09:00:00+00:00")

    def test_title_normalization_and_hashing(self) -> None:
        self.assertEqual(normalize_title("Fed's Rate Decision!"), "fed s rate decision")
        self.assertEqual(url_hash("https://example.com"), url_hash("https://example.com"))


class TransformTests(unittest.TestCase):
    def test_cluster_groups_identical_headlines(self) -> None:
        items = [
            {"headline": "Oil prices rise after supply disruption"},
            {"headline": "Oil prices rise after supply disruption"},
            {"headline": "Bitcoin falls sharply"},
        ]
        groups = cluster(items, lambda item: item["headline"])
        self.assertEqual([len(group) for group in groups], [2, 1])

    def test_summary_values_are_coerced_to_supported_ranges(self) -> None:
        result = _coerce(
            {
                "headline": "Test",
                "bullets": "One",
                "topic": "invalid",
                "sentiment": "invalid",
                "importance": 99,
                "instruments": "WTI",
            },
            "Markets",
        )
        self.assertEqual(result["topic"], "Markets")
        self.assertEqual(result["sentiment"], "neutral")
        self.assertEqual(result["importance"], 5)
        self.assertEqual(result["bullets"], ["One"])
        self.assertEqual(result["instruments"], ["WTI"])

    @patch("src.summarize.litellm.completion")
    def test_completion_falls_back_to_the_next_provider(self, completion) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )
        completion.side_effect = [RuntimeError("first provider failed"), response]

        result = complete_json("system", "user", ["test/first", "test/second"])

        self.assertEqual(result, {"ok": True})
        self.assertEqual(completion.call_count, 2)


class RenderTests(unittest.TestCase):
    def test_summarized_article_renders_day_index_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = Config(
                db_path=root / "test.db",
                site_dir=root / "site",
                site_title="Test Brief",
                llm_chain=[],
                max_input_chars=6000,
                max_articles_per_run=0,
                feeds=[],
            )
            conn = init_db(cfg.db_path)
            conn.execute(
                """INSERT INTO articles
                   (url_hash, norm_title, url, title, source, feed_topic,
                    published, fetched_at, raw_text, summarized, headline,
                    bullets, topic, sentiment, instruments, importance, llm_model)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "abc",
                    "synthetic story",
                    "https://example.com/story",
                    "Synthetic Story",
                    "Test Feed",
                    "Markets",
                    "2026-07-22T01:00:00+00:00",
                    "2026-07-22T01:01:00+00:00",
                    "body",
                    1,
                    "Synthetic Macro Headline",
                    json.dumps(["First point"]),
                    "Markets",
                    "bullish",
                    json.dumps(["DXY"]),
                    4,
                    "test-model",
                ),
            )
            conn.commit()
            render_site(conn, cfg)
            conn.close()

            index = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
            day = (cfg.site_dir / "2026-07-22.html").read_text(encoding="utf-8")
            archive = (cfg.site_dir / "archive.html").read_text(encoding="utf-8")
            self.assertIn("Synthetic Macro Headline", index)
            self.assertIn("Synthetic Macro Headline", day)
            self.assertIn("2026-07-22.html", archive)


class DependencyTests(unittest.TestCase):
    def test_retry_dependency_is_installed(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("tenacity"))

    def test_litellm_is_installed(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("litellm"))


if __name__ == "__main__":
    unittest.main()
