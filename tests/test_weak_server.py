import asyncio
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import handlers, mediarun, processor
from media_hunter_bot.progress import ProgressTracker


class MediaRunTests(unittest.TestCase):
    def test_low_priority_prefix(self):
        with patch.object(mediarun, "LOW_PRIORITY_MEDIA", True), patch.object(mediarun, "_NICE", "/usr/bin/nice"), \
             patch.object(mediarun, "_IONICE", None):
            self.assertEqual(mediarun.low_priority(["ffmpeg", "-i", "x"])[:3], ["/usr/bin/nice", "-n", "10"])
        with patch.object(mediarun, "LOW_PRIORITY_MEDIA", False):
            self.assertEqual(mediarun.low_priority(["ffmpeg"]), ["ffmpeg"])

    def test_progress_flag_only_for_ffmpeg(self):
        self.assertEqual(mediarun.with_progress(["ffmpeg", "-y"])[:3], ["ffmpeg", "-progress", "pipe:1"])
        self.assertEqual(mediarun.with_progress(["yt-dlp", "x"]), ["yt-dlp", "x"])

    def test_bot_api_cleanup_only_old_files_in_token_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vids = root / "123:ABC" / "videos"
            vids.mkdir(parents=True)
            old, new = vids / "old.mp4", vids / "new.mp4"
            old.write_bytes(b"x"); new.write_bytes(b"x")
            past = time.time() - 3 * 3600
            os.utime(old, (past, past))
            other = root / "not-a-token" / "keep.txt"
            other.parent.mkdir(); other.write_bytes(b"x"); os.utime(other, (past, past))
            self.assertEqual(mediarun.cleanup_bot_api_dir(td, 60), 1)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists() and other.exists())

    def test_remove_bot_api_file_stays_inside_dir(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            inside = Path(td) / "f.mp4"; inside.write_bytes(b"x")
            foreign = Path(outside) / "g.mp4"; foreign.write_bytes(b"x")
            mediarun.remove_bot_api_file(td, str(foreign))
            mediarun.remove_bot_api_file(td, str(inside))
            self.assertTrue(foreign.exists())
            self.assertFalse(inside.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_run_ffmpeg_reports_progress(self):
        seen = []
        token = mediarun.progress_sink.set(seen.append)
        try:
            with tempfile.TemporaryDirectory() as td:
                code, _, timed_out = mediarun.run_ffmpeg(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=3:r=10", "-c:v", "mpeg4", str(Path(td) / "o.mp4")],
                    lambda _p=None: None, timeout=60, duration=3,
                )
        finally:
            mediarun.progress_sink.reset(token)
        self.assertEqual((code, timed_out), (0, False))


class GuardTests(unittest.TestCase):
    def test_disk_guard(self):
        with patch.object(handlers.mediarun, "free_disk_mb", return_value=100):
            with self.assertRaisesRegex(RuntimeError, "мало свободного места"):
                handlers.ensure_disk_space()
        with patch.object(handlers.mediarun, "free_disk_mb", return_value=10 ** 6):
            handlers.ensure_disk_space(500)

    def test_download_errors_are_explained(self):
        self.assertIn("приватное", processor.explain_download_error("ERROR: [youtube] x: Private video. Sign in"))
        self.assertIn("не поддерживается", processor.explain_download_error("ERROR: Unsupported URL: https://x"))
        self.assertIn("Проверьте ссылку", processor.explain_download_error("weird"))

    def test_queue_eta(self):
        engine = handlers.Engine(None)
        engine._avg_job_s = 60
        for seq, uid in enumerate([1, 2, 3], start=1):
            engine.q.put_nowait(handlers.Job(1, seq, uid, 0, "https://x"))
        ahead, wait = engine.queue_eta(3)
        self.assertEqual(ahead, 2)
        self.assertEqual(wait, 180)
        self.assertIn("Перед вами в очереди: 2", handlers.queued_text(engine, 3, "Ссылка принята"))
        self.assertIn("начинаю", handlers.queued_text(handlers.Engine(None), 9, "Ссылка принята"))


class ProgressTests(unittest.TestCase):
    def test_percent_bar(self):
        async def run():
            bot = MagicMock()
            bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
            bot.edit_message_text = AsyncMock()
            p = ProgressTracker(bot, 1, has_url=False)
            await p.start()
            await p.advance("process")
            p._last_percent_edit = 0
            await p.set_percent(0.47)
            text = bot.edit_message_text.await_args.args[0]
            self.assertIn("47%", text)
            self.assertIn("▓▓▓▓░", text)
            calls = bot.edit_message_text.await_count
            await p.set_percent(0.48)  # throttled
            self.assertEqual(bot.edit_message_text.await_count, calls)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
