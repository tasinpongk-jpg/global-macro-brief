from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.models import compact_db, init_db


def _insert(conn, i: int, summarized: int, text: str) -> None:
    conn.execute(
        """INSERT INTO articles (url_hash, norm_title, url, title, source,
               feed_topic, published, fetched_at, raw_text, summarized)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (f"h{i}", f"t{i}", f"https://example.com/{i}", f"T{i}", "Feed",
         "Markets", "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00",
         text, summarized),
    )


class CompactDbTests(unittest.TestCase):
    def test_clears_summarized_text_and_vacuums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = init_db(Path(tmp) / "t.db")
            for i in range(200):
                _insert(conn, i, summarized=1 if i % 2 else 0, text="x" * 20_000)
            conn.commit()

            stats = compact_db(conn)

            self.assertEqual(stats["cleared"], 100)
            self.assertTrue(stats["vacuumed"])
            self.assertLess(stats["size_bytes"], stats["before_bytes"] * 0.7)
            kept = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE raw_text IS NOT NULL"
            ).fetchone()[0]
            self.assertEqual(kept, 100)  # pending articles keep their text
            conn.close()

    def test_second_compaction_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = init_db(Path(tmp) / "t.db")
            _insert(conn, 1, summarized=1, text="body")
            conn.commit()
            compact_db(conn)
            stats = compact_db(conn)
            self.assertEqual(stats["cleared"], 0)
            self.assertFalse(stats["vacuumed"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
