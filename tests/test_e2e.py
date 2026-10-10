"""Whole-pipeline tests with fake feeds, fake HTTP and a fake LLM provider."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

import litellm

from src import pipeline, summarize
from src.config import Feed
from src.digest import generate_digest
from src.ingest import ingest_all
from src.models import compact_db, init_db
from src.render import render_site
from src.summarize import ProviderPool
from tests.fakes import FakeLLM, TempDir, http_response, make_config, response, rss

NOW = datetime.now(UTC)


def _date(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


TITLES = ["Brent crude jumps on supply outage", "Fed signals patience on rates",
          "Gold hits record high", "Yen weakens past key level",
          "China exports beat forecasts", "Bitcoin ETF inflows slow",
          "Thai baht steadies after cut"]
FEED_ITEMS = [
    {"title": t, "link": f"https://example.com/story/{i}",
     "date": _date(i + 1), "desc": "Detailed body text. " * 40}  # long: no page fetch
    for i, t in enumerate(TITLES)
]
FEED_ITEMS.append({"title": "Old story", "link": "https://example.com/old",
                   "date": _date(24 * 30), "desc": "Ancient news. " * 60})


def fake_get(url, **kwargs):
    if url.endswith("/feed.xml"):
        return http_response(rss(FEED_ITEMS))
    if url.endswith("/broken.xml"):
        return http_response(b"<html>blocked</html>", status=429, ctype="text/html")
    raise AssertionError(f"unexpected fetch {url}")


class PipelineEndToEndTests(unittest.TestCase):
    def _run(self, root, llm, **cfg_over):
        cfg = make_config(root, feeds=[Feed("Fake", "https://f.test/feed.xml", "Energy/Oil"),
                                       Feed("Broken", "https://f.test/broken.xml")],
                          **cfg_over)
        conn = init_db(cfg.db_path)
        with patch("src.net._session.get", side_effect=fake_get), \
                patch.object(summarize.litellm, "completion", llm):
            added = ingest_all(conn, cfg)
            pool = ProviderPool(cfg.llm_chain)
            stats = pipeline.summarize_pending(conn, cfg, pool)
            if not pool.exhausted:
                generate_digest(conn, cfg, pool)
        render_site(conn, cfg)
        compact_db(conn, stale_before=pipeline.stale_cutoff(cfg),
                   max_attempts=cfg.summary_max_attempts)
        return cfg, conn, added, stats

    def test_happy_path_ingests_summarizes_renders(self) -> None:
        with TempDir() as root:
            llm = FakeLLM()
            cfg, conn, added, stats = self._run(root, llm)
            self.assertEqual(added, 8)
            self.assertEqual(stats.eligible, 7)  # the 30-day-old story is out of window
            self.assertEqual(stats.summarized, 7)
            self.assertFalse(stats.exhausted)
            # 7 articles in batches of 3 -> 3 requests, + 1 digest request
            self.assertEqual(len(llm.calls), 4)
            index = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Summary: Gold hits record high", index)
            self.assertIn("Risk-on as the dollar firms.", index)
            # raw text is dropped once summarized (and for the stale article)
            left = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE raw_text IS NOT NULL").fetchone()[0]
            self.assertEqual(left, 0)
            conn.close()

    def test_outage_stops_early_and_site_shows_titles(self) -> None:
        with TempDir() as root:
            auth = litellm.AuthenticationError("bad key", llm_provider="x", model="m")
            llm = FakeLLM(errors={"test/primary": auth, "test/backup": auth})
            cfg, conn, _, stats = self._run(root, llm, llm_concurrency=1)
            self.assertTrue(stats.exhausted)
            self.assertEqual(stats.summarized, 0)
            self.assertEqual(len(llm.calls), 2)  # one call per provider, then stop
            # untried articles are not penalised
            self.assertEqual(conn.execute(
                "SELECT MAX(attempts) FROM articles").fetchone()[0], 0)
            index = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Gold hits record high", index)
            self.assertIn("summary pending", index)
            conn.close()

    def test_failed_articles_hit_the_retry_cap(self) -> None:
        with TempDir() as root:
            cfg = make_config(root, summary_batch_size=1, llm_concurrency=1,
                              summary_max_attempts=2)
            conn = init_db(cfg.db_path)
            conn.execute(
                "INSERT INTO articles (url_hash, url, title, feed_topic, published, "
                "fetched_at, raw_text) VALUES ('h', 'https://e.com/a', 'A', 'Markets', ?, ?, ?)",
                (NOW.isoformat(), NOW.isoformat(), "text " * 200))
            conn.commit()
            with patch.object(summarize.litellm, "completion",
                              lambda **kw: response("not json")):
                for _ in range(3):
                    pipeline.summarize_pending(conn, cfg, ProviderPool(cfg.llm_chain))
            row = conn.execute("SELECT attempts, summarized FROM articles").fetchone()
            self.assertEqual((row["attempts"], row["summarized"]), (2, 0))
            conn.close()


class StrictExitTests(unittest.TestCase):
    def test_strict_exits_3_on_outage(self) -> None:
        with TempDir() as root:
            cfg = make_config(root)
            outage = pipeline.SummaryStats(selected=5, summarized=0, exhausted=True)
            with patch.object(pipeline, "load_config", return_value=cfg), \
                    patch.object(pipeline, "ingest_all"), \
                    patch.object(pipeline, "generate_digest"), \
                    patch.object(pipeline, "summarize_pending", return_value=outage), \
                    patch("sys.argv", ["pipeline", "--strict"]), \
                    self.assertRaises(SystemExit) as cm:
                pipeline.main()
            self.assertEqual(cm.exception.code, 3)
            self.assertTrue((cfg.site_dir / "index.html").exists())  # rendered first


if __name__ == "__main__":
    unittest.main()
