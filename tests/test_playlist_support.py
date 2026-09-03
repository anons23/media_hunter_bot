import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_hunter_bot import playlist_support


class PlaylistSupportTests(unittest.TestCase):
    def test_free_playlist_limit_is_twenty_and_monthly_limit_is_three(self):
        self.assertEqual(playlist_support.FREE_PLAYLIST_MAX_VIDEOS, 20)
        self.assertEqual(playlist_support.FREE_PLAYLISTS_PER_MONTH, 3)
        self.assertEqual(playlist_support.PLAYLIST_MAX_ORIGINAL_MB, 80)

    def test_free_playlist_usage_is_atomic_and_refundable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "usage.sqlite3"
            with patch.object(playlist_support, "DB_PATH", db_path):
                uid = 123
                self.assertTrue(playlist_support.consume_free_playlist(uid))
                self.assertTrue(playlist_support.consume_free_playlist(uid))
                self.assertTrue(playlist_support.consume_free_playlist(uid))
                self.assertFalse(playlist_support.consume_free_playlist(uid))
                self.assertEqual(playlist_support.free_playlist_usage(uid), 3)
                playlist_support.refund_free_playlist(uid)
                self.assertEqual(playlist_support.free_playlist_usage(uid), 2)

    def test_playlist_priority_yields_to_normal_jobs(self):
        self.assertEqual(playlist_support._priority(True, playlist=True), 2)
        self.assertEqual(playlist_support._priority(False, playlist=True), 2)
        self.assertEqual(playlist_support._priority(True, playlist=False), 0)
        self.assertEqual(playlist_support._priority(False, playlist=False), 1)

    def test_known_video_size_parses_numeric_output(self):
        fake = type("Proc", (), {"returncode": 0, "stdout": "83886080\n", "stderr": ""})()
        with patch("media_hunter_bot.playlist_support.subprocess.run", return_value=fake):
            self.assertEqual(playlist_support._known_video_size("https://www.youtube.com/watch?v=test"), 83886080)

    def test_known_video_size_returns_none_for_na(self):
        fake = type("Proc", (), {"returncode": 0, "stdout": "NA\n", "stderr": ""})()
        with patch("media_hunter_bot.playlist_support.subprocess.run", return_value=fake):
            self.assertIsNone(playlist_support._known_video_size("https://www.youtube.com/watch?v=test"))


if __name__ == "__main__":
    unittest.main()
