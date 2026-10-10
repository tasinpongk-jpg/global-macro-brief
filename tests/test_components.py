"""Unit tests for extraction, feed fetching, clustering, digest, config, render."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import requests

from src import extract, net, summarize
from src.cluster import cluster
from src.config import Feed, _int_env
from src.digest import generate_digest
from src.ingest import ingest_feed
from src.models import init_db
from src.render import render_site
from src.summarize import ProviderPool
from tests.fakes import FakeLLM, TempDir, http_response, make_config, rss

ARTICLE_HTML = (
    "<html><head><title>T</title></head><body><nav>menu</nav><article><h1>Rates</h1>"
    + "".join(f"<p>The central bank kept its policy rate unchanged at meeting {i}, "
              "citing sticky services inflation and a resilient labour market.</p>"
              for i in range(12))
    + "</article><footer>footer</footer></body></html>"
)


class ExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        net._robots.clear()

    def test_extracts_article_text(self) -> None:
        with patch.object(net, "allowed", return_value=True), \
                patch.object(net, "get", return_value=http_response(ARTICLE_HTML.encode(),
                                                                     ctype="text/html")):
            text = extract.extract_text("https://news.test/a")
        self.assertIn("policy rate unchanged", text)
        self.assertNotIn("footer", text)

    def test_network_error_returns_empty(self) -> None:
        with patch.object(net, "allowed", return_value=True), \
                patch.object(net, "get", side_effect=requests.Timeout("slow")):
            self.assertEqual(extract.extract_text("https://news.test/a"), "")

    def test_respects_robots_txt(self) -> None:
        robots = http_response(b"User-agent: *\nDisallow: /private/\n", ctype="text/plain")
        with patch.object(net._session, "get", return_value=robots) as get:
            self.assertFalse(net.allowed("https://news.test/private/x"))
            self.assertTrue(net.allowed("https://news.test/public/y"))
            self.assertEqual(get.call_count, 1)  # cached per origin
        with patch.object(net, "get") as page:
            self.assertEqual(extract.extract_text("https://news.test/private/x"), "")
            page.assert_not_called()

    def test_missing_robots_allows_everything(self) -> None:
        with patch.object(net._session, "get", return_value=http_response(status=404)):
            self.assertTrue(net.allowed("https://other.test/anything"))

    def test_requests_use_timeout_and_user_agent(self) -> None:
        with patch.object(net._session, "get", return_value=http_response(b"ok")) as get:
            net.get("https://x.test/")
        self.assertEqual(get.call_args.kwargs["timeout"], net.TIMEOUT)
        self.assertIn("GlobalMacroBrief", net._session.headers["User-Agent"])


class IngestFetchTests(unittest.TestCase):
    def _conn(self, root):
        return init_db(root / "t.db")

    def test_bot_wall_counts_as_dead_feed(self) -> None:
        with TempDir() as root:
            conn = self._conn(root)
            wall = http_response(b"<html>Security Checkpoint</html>", status=429,
                                 ctype="text/html")
            with patch.object(net._session, "get", return_value=wall):
                self.assertEqual(ingest_feed(conn, Feed("VB", "https://vb.test/feed")), (0, 0))
            conn.close()

    def test_timeout_counts_as_dead_feed(self) -> None:
        with TempDir() as root:
            conn = self._conn(root)
            with patch.object(net._session, "get", side_effect=requests.Timeout("t")):
                self.assertEqual(ingest_feed(conn, Feed("X", "https://x.test/feed")), (0, 0))
            conn.close()

    def test_dedups_by_url_and_title(self) -> None:
        items = [
            {"title": "Fed holds", "link": "https://a.test/1",
             "date": "Mon, 05 Oct 2026 09:00:00 GMT", "desc": "d"},
            {"title": "Fed holds!", "link": "https://a.test/2",  # same normalized title
             "date": "Mon, 05 Oct 2026 09:00:00 GMT", "desc": "d"},
            {"title": "ECB cuts", "link": "https://a.test/3",
             "date": "Mon, 05 Oct 2026 10:00:00 EST", "desc": "d"},
        ]
        with TempDir() as root:
            conn = self._conn(root)
            with patch.object(net._session, "get", return_value=http_response(rss(items))):
                self.assertEqual(ingest_feed(conn, Feed("A", "https://a.test/rss")), (2, 3))
                self.assertEqual(ingest_feed(conn, Feed("A", "https://a.test/rss")), (0, 3))
            pub = conn.execute(
                "SELECT published FROM articles WHERE title = 'ECB cuts'").fetchone()[0]
            self.assertEqual(pub, "2026-10-05T15:00:00+00:00")
            conn.close()


class ClusterTests(unittest.TestCase):
    def test_paraphrased_headlines_merge_but_different_events_do_not(self) -> None:
        items = [
            "Oil prices jump after OPEC+ announces surprise output cut",
            "OPEC+ surprise output cut sends oil prices jumping",
            "Gold slips as dollar strengthens",
            "Bank of Japan holds rates steady",
        ]
        groups = cluster(items, lambda s: s)
        self.assertEqual(sorted(len(g) for g in groups), [1, 1, 2])

    def test_empty_and_stopword_only_text(self) -> None:
        self.assertEqual(cluster([], str), [])
        groups = cluster(["the and of", "", "the and of"], lambda s: s)
        self.assertEqual(len(groups), 3)  # no tokens -> never merged

    def test_threshold_controls_merging(self) -> None:
        items = ["Fed raises rates by 25bp", "Fed raises rates, signals pause"]
        self.assertEqual(len(cluster(items, str, threshold=0.99)), 2)
        self.assertEqual(len(cluster(items, str, threshold=0.3)), 1)


def _insert_summarized(conn, i, day="2026-10-09", importance=3):
    conn.execute(
        """INSERT INTO articles (url_hash, url, title, source, feed_topic, published,
               fetched_at, summarized, headline, bullets, topic, sentiment,
               importance, instruments)
           VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?)""",
        (f"h{i}", f"https://e.test/{i}", f"T{i}", "Src", "Markets",
         f"{day}T0{i % 10}:00:00+00:00", f"{day}T10:00:00+00:00",
         f"Unique headline number {i} about topic{i}", json.dumps(["b"]), "Markets",
         "bearish", importance, json.dumps([])),
    )


class DigestTests(unittest.TestCase):
    def test_one_mood_per_day(self) -> None:
        with TempDir() as root:
            cfg = make_config(root)
            conn = init_db(cfg.db_path)
            for i in range(3):
                _insert_summarized(conn, i)
            conn.commit()
            llm = FakeLLM()
            with patch.object(summarize.litellm, "completion", llm):
                generate_digest(conn, cfg, ProviderPool(cfg.llm_chain))
                generate_digest(conn, cfg, ProviderPool(cfg.llm_chain))
            self.assertEqual(len(llm.calls), 1)
            mood = conn.execute("SELECT mood FROM digests WHERE day='2026-10-09'").fetchone()
            self.assertEqual(mood[0], "Risk-on as the dollar firms.")
            conn.close()

    def test_failure_is_non_fatal(self) -> None:
        with TempDir() as root:
            cfg = make_config(root)
            conn = init_db(cfg.db_path)
            _insert_summarized(conn, 1)
            conn.commit()
            llm = FakeLLM(errors={"test/primary": RuntimeError("x"),
                                  "test/backup": RuntimeError("y")})
            with patch.object(summarize.litellm, "completion", llm):
                generate_digest(conn, cfg)  # must not raise
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0], 0)
            conn.close()


class RenderPendingTests(unittest.TestCase):
    def test_pending_items_render_by_title_and_never_lead(self) -> None:
        with TempDir() as root:
            cfg = make_config(root)
            conn = init_db(cfg.db_path)
            _insert_summarized(conn, 1, importance=2)
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO articles (url_hash, url, title, source, feed_topic, published, "
                "fetched_at) VALUES ('p', 'https://e.test/p', 'Raw feed title', 'Src', "
                "'Geopolitics', '2026-10-09T05:00:00+00:00', ?)", (now,))
            conn.commit()
            render_site(conn, cfg)
            day = (cfg.site_dir / "2026-10-09.html").read_text(encoding="utf-8")
            self.assertIn("Raw feed title", day)
            self.assertIn("summary pending", day)
            tldr = day.split('class="tldr-list"')[1].split("</ol>")[0]
            self.assertNotIn("Raw feed title", tldr)
            self.assertIn("Unique headline number 1", tldr)
            conn.close()


class ConfigTests(unittest.TestCase):
    def test_int_env_tolerates_blank_and_garbage(self) -> None:
        with patch.dict("os.environ", {"A": "", "B": "abc", "C": "12", "D": "-4"}):
            self.assertEqual(_int_env("A", 5), 5)
            self.assertEqual(_int_env("B", 5), 5)
            self.assertEqual(_int_env("C", 5), 12)
            self.assertEqual(_int_env("D", 5, minimum=1), 1)
            self.assertEqual(_int_env("MISSING", 7), 7)


if __name__ == "__main__":
    unittest.main()
