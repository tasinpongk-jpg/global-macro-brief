"""Whole-pipeline tests with fake feeds, fake HTTP and a fake LLM provider."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch

import litellm

from src import pipeline, summarize
from src.config import Feed
from src.digest import generate_digest
from src.ingest import ingest_all, ingest_feed, url_hash
from src.models import compact_db, init_db
from src.render import render_site
from src.summarize import ProviderPool
from tests.fakes import FakeLLM, TempDir, http_response, make_config, response, rss

NOW = datetime.now(UTC)
FEED_DAY = NOW.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)


def _date(hours_ago: float) -> str:
    return format_datetime(FEED_DAY - timedelta(hours=hours_ago))


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
        return http_response(rss(FEED_ITEMS).replace(
            b"<title>Fake</title>", b"<title>Fake</title><language>en-US</language>",
        ))
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
            path = cfg.site_dir / "data/global-intel.json"
            first = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(first["items"], [
                {"title": t, "url": FEED_ITEMS[i]["link"], "source": "Fake", "language": "en",
                 "published": (FEED_DAY - timedelta(hours=i + 1)).isoformat()}
                for i, t in enumerate(TITLES)
            ])
            conn.execute("UPDATE articles SET headline = 'Different AI headline', importance = 1")
            render_site(conn, cfg)
            second = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(second["editionId"], first["editionId"])
            self.assertEqual(second["items"], first["items"])
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


class PublicationProvenanceTests(unittest.TestCase):
    def test_exports_only_full_original_publication_dates(self) -> None:
        timestamp = _date(1)
        atom_published = FEED_DAY - timedelta(hours=2)
        atom_timestamp = atom_published.astimezone(timezone(timedelta(hours=7))).isoformat()
        site_timestamp = atom_published.isoformat()
        old_display = (FEED_DAY - timedelta(hours=3)).isoformat()
        articles = [
            ("rss", f"<pubDate>{timestamp}</pubDate>"),
            ("iso", f"<published>{atom_timestamp}</published>"),
            ("updated", f"<updated>{atom_timestamp}</updated>"),
            ("created", f"<created>{atom_timestamp}</created>"),
            ("invalid", f"<pubDate>invalid</pubDate><updated>{atom_timestamp}</updated>"),
            ("impossible-day", "<pubDate>2026-11-31T00:00:00Z</pubDate>"
                               f"<updated>{atom_timestamp}</updated>"),
            ("partial", f"<pubDate>{FEED_DAY:%Y-%m-%d}</pubDate>"
                        f"<created>{atom_timestamp}</created>"),
            ("no-zone", f"<pubDate>{FEED_DAY:%Y-%m-%dT%H:%M:%S}</pubDate>"),
            ("unknown-zone", f"<pubDate>{FEED_DAY:%Y-%m-%dT%H:%M:%S}-00:00</pubDate>"),
            ("repeat", f"<pubDate>{timestamp}</pubDate>"),
            ("other-source", f"<pubDate>{timestamp}</pubDate>"),
            ("changed-title", f"<pubDate>{timestamp}</pubDate>"),
        ]
        entries = "".join(
            f"<item><title>{name}</title><link>https://a.test/{name}</link>{dates}</item>"
            for name, dates in articles
        )
        body = f"<rss version='2.0'><channel><title>Fake</title>{entries}</channel></rss>".encode()
        feed = Feed("Fake", "https://a.test/feed.xml")
        with TempDir() as root:
            cfg = make_config(root)
            conn = init_db(cfg.db_path)
            conn.executemany(
                "INSERT INTO articles (url_hash, url, title, source, published, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(url_hash(f"https://a.test/{name}"), f"https://a.test/{name}",
                  "earlier title" if name == "changed-title" else name, source,
                  old_display, old_display)
                 for name, source in [("repeat", "Fake"), ("other-source", "Different"),
                                      ("unobserved", "Fake"), ("changed-title", "Fake")]],
            )
            with patch("src.net._session.get", return_value=http_response(body)):
                self.assertEqual(ingest_feed(conn, feed), (9, 12))
            render_site(conn, cfg)
            path = cfg.site_dir / "data/global-intel.json"
            export = json.loads(path.read_text(encoding="utf-8"))
            timestamps = {item["title"]: item["published"] for item in export["items"]}
            self.assertEqual(timestamps, {
                "rss": (FEED_DAY - timedelta(hours=1)).isoformat(),
                "iso": site_timestamp,
                "repeat": (FEED_DAY - timedelta(hours=1)).isoformat(),
            })
            stored = dict(conn.execute("SELECT title, published FROM articles"))
            self.assertEqual(stored["updated"], site_timestamp)
            self.assertEqual(stored["created"], site_timestamp)
            self.assertEqual(stored["invalid"], site_timestamp)
            self.assertEqual(stored["repeat"], old_display)
            self.assertIsNotNone(stored["partial"])
            conn.close()


    def test_rejects_rfc_year_pivot_before_utc_conversion(self) -> None:
        items = [
            {"title": "Ancient publication", "link": "https://a.test/ancient",
             "date": "Sat, 28 Nov 0026 01:00:00 GMT", "desc": ""},
            {"title": "Valid year boundary", "link": "https://a.test/current",
             "date": "Fri, 01 Jan 2027 01:00:00 +0700", "desc": ""},
        ]
        feed = Feed("Fake", "https://a.test/feed.xml")
        with TempDir() as root:
            cfg = make_config(root)
            conn = init_db(cfg.db_path)
            with patch("src.net._session.get", return_value=http_response(rss(items))):
                self.assertEqual(ingest_feed(conn, feed), (2, 2))
            with patch("src.render.datetime", wraps=datetime) as clock:
                clock.now.return_value = datetime(2026, 11, 28, 2, tzinfo=UTC)
                render_site(conn, cfg)
                path = cfg.site_dir / "data/global-intel.json"
                november = json.loads(path.read_text(encoding="utf-8"))
                clock.now.return_value = datetime(2026, 12, 31, 20, tzinfo=UTC)
                render_site(conn, cfg)
                december = json.loads(path.read_text(encoding="utf-8"))
            conn.close()

        self.assertEqual(november["items"], [])
        self.assertEqual(december["items"], [
            {"title": "Valid year boundary", "source": "Fake", "url": "https://a.test/current",
             "published": "2026-12-31T18:00:00+00:00"},
        ])


class StrictExitTests(unittest.TestCase):
    def test_strict_exits_3_on_outage(self) -> None:
        with TempDir() as root:
            cfg = make_config(root, feeds=[Feed("Fake", "https://f.test/feed.xml")], llm_chain=[])
            with patch.object(pipeline, "load_config", return_value=cfg), \
                    patch("src.net._session.get", side_effect=fake_get), \
                    patch.object(summarize.litellm, "completion") as completion, \
                    patch("sys.argv", ["pipeline", "--strict"]), \
                    self.assertRaises(SystemExit) as cm:
                pipeline.main()
            self.assertEqual(cm.exception.code, 3)
            completion.assert_not_called()
            path = cfg.site_dir / "data/global-intel.json"
            export = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([item["title"] for item in export["items"]], TITLES)
            self.assertTrue((cfg.site_dir / "index.html").exists())  # rendered first


if __name__ == "__main__":
    unittest.main()
