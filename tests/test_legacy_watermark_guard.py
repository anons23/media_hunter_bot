import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from media_hunter_bot.legacy_watermark_guard import cleanup_legacy_watermark


class LegacyWatermarkGuardTests(unittest.TestCase):
    def _db(self, root: Path):
        path = root / "media_hunter.sqlite3"
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE users(user_id INTEGER PRIMARY KEY, watermark TEXT NOT NULL);
            CREATE TABLE channels(rowid INTEGER PRIMARY KEY, watermark TEXT NOT NULL);
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        return path, con

    def test_removes_legacy_placeholder_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, con = self._db(Path(tmp))
            con.execute("INSERT INTO users VALUES(?, ?)", (1, json.dumps({"type": "text", "text": "Мой канал"}, ensure_ascii=False)))
            con.execute("INSERT INTO channels(rowid, watermark) VALUES(?, ?)", (1, json.dumps({"type": "text", "text": "Мой канал"}, ensure_ascii=False)))
            con.execute("INSERT INTO users VALUES(?, ?)", (2, json.dumps({"type": "text", "text": "Мой бренд"}, ensure_ascii=False)))
            con.commit(); con.close()

            self.assertEqual(cleanup_legacy_watermark(path), 2)
            con = sqlite3.connect(path)
            rows = con.execute("SELECT watermark FROM users ORDER BY user_id").fetchall()
            channel = con.execute("SELECT watermark FROM channels WHERE rowid=1").fetchone()[0]
            marker = con.execute("SELECT value FROM settings WHERE key='legacy_watermark_cleanup_v1'").fetchone()[0]
            con.close()
            self.assertEqual(rows[0][0], "{}")
            self.assertEqual(json.loads(rows[1][0])["text"], "Мой бренд")
            self.assertEqual(channel, "{}")
            self.assertEqual(marker, "done")

    def test_second_run_does_not_delete_newly_configured_same_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, con = self._db(Path(tmp))
            con.execute("INSERT INTO users VALUES(?, ?)", (1, "{}"))
            con.commit(); con.close()
            self.assertEqual(cleanup_legacy_watermark(path), 0)
            con = sqlite3.connect(path)
            con.execute("UPDATE users SET watermark=? WHERE user_id=1", (json.dumps({"type": "text", "text": "Мой канал"}, ensure_ascii=False),))
            con.commit(); con.close()
            self.assertEqual(cleanup_legacy_watermark(path), 0)
            con = sqlite3.connect(path)
            value = con.execute("SELECT watermark FROM users WHERE user_id=1").fetchone()[0]
            con.close()
            self.assertEqual(json.loads(value)["text"], "Мой канал")


if __name__ == "__main__":
    unittest.main()
