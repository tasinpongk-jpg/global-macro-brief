"""Contract and filtering tests for the public headline export."""
from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta

from src.global_intel import write_global_intel
from src.models import init_db
from tests.fakes import TempDir

NOW = datetime(2026, 11, 28, 2, tzinfo=UTC)


class GlobalIntelTests(unittest.TestCase):
    def test_filters_and_caps_headlines_in_deterministic_order(self) -> None:
        items = [
            dict(title=f"Headline {i}", source="Original feed", url=f"https://a.test/{i:03}",
                 published="2026-11-28T08:00:00+07:00", language=None)
            for i in range(501)
        ]
        items[-1].update(title="เงินบาทแข็งค่า", language="th")
        items[-2].update(language="fr")
        invalid = [
            {"published": None}, {"published": "invalid"}, {"published": "2026-11-28T01:00:00"},
            {"published": (NOW + timedelta(minutes=2)).isoformat()},
            {"published": (NOW - timedelta(days=7, seconds=1)).isoformat()},
            {"url": "http://a.test/story"}, {"url": "https:///story"},
            {"url": "https://a.test:bad/story"}, {"url": "https://u:p@a.test/story"},
            {"url": "https://a.test/\tstory"}, {"url": "https://a.test/" + "x" * 2048},
            {"title": " "}, {"title": "x" * 513}, {"source": None}, {"source": "x" * 129},
        ]
        with TempDir() as root:
            with init_db(root / "news.db") as conn:
                rows = items + [{**items[0], "url": f"https://z.test/{i}", **fields}
                                for i, fields in enumerate(invalid)]
                conn.executemany(
                    "INSERT INTO articles (url_hash, title, source, url, published, language, "
                    "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(str(i), row["title"], row["source"], row["url"], row["published"],
                      row["language"], NOW.isoformat()) for i, row in enumerate(rows)],
                )
                db_rows = conn.execute("SELECT * FROM articles").fetchall()
            conn.close()
            path = root / "data/global-intel.json"
            write_global_intel(db_rows, root, NOW)
            first = json.loads(path.read_text(encoding="utf-8"))
            write_global_intel(reversed(db_rows), root, NOW + timedelta(minutes=1))
            second = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(set(first), {"schema", "editionId", "generatedAt", "items"})
        self.assertEqual(first["schema"], 1)
        self.assertEqual(first["generatedAt"], NOW.isoformat())
        self.assertNotEqual(first["generatedAt"], second["generatedAt"])
        self.assertEqual(first["items"], second["items"])
        expected_items = []
        for row in reversed(items[1:]):
            item = {**row, "published": "2026-11-28T01:00:00+00:00"}
            if item["language"] != "th":
                del item["language"]
            expected_items.append(item)
        self.assertEqual(first["items"], expected_items)
        canonical = json.dumps(expected_items, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        self.assertEqual(first["editionId"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(second["editionId"], first["editionId"])
