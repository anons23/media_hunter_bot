import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import handlers, processor, quality

MB = 1024 * 1024


def _info(duration=3600, video_mb=None, audio_mb=60):
    """YouTube-like format list, sorted worst -> best like yt-dlp returns it."""
    video_mb = video_mb or {1080: 1200, 720: 600, 480: 300, 360: 150, 240: 80, 144: 40}
    formats = [{"format_id": "a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 128,
                "filesize": audio_mb * MB}]
    for h, mb in sorted(video_mb.items()):
        formats.append({"format_id": f"v{h}", "ext": "mp4", "vcodec": "avc1", "acodec": "none",
                        "height": h, "fps": 30, "filesize": mb * MB})
        # webm duplicates must be ignored by the mp4-only selector
        formats.append({"format_id": f"w{h}", "ext": "webm", "vcodec": "vp9", "acodec": "none",
                        "height": h, "filesize": 1})
    return {"duration": duration, "formats": formats}


class SelectorTests(unittest.TestCase):
    def test_default_selector_unchanged(self):
        self.assertEqual(
            quality.format_selector(None),
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        )

    def test_capped_selector_has_no_unbounded_fallback(self):
        sel = quality.format_selector(480)
        self.assertIn("height<=480", sel)
        self.assertFalse(sel.endswith("/best"))


class PlanTests(unittest.TestCase):
    def test_no_choice_when_fits(self):
        self.assertIsNone(quality.plan(_info(video_mb={1080: 300, 720: 150}), limit_mb=700))

    def test_no_choice_when_size_unknown(self):
        info = {"duration": 0, "formats": [{"ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080}]}
        self.assertIsNone(quality.plan(info, limit_mb=700))

    def test_offers_only_fitting_lower_qualities(self):
        p = quality.plan(_info(), limit_mb=700)
        self.assertEqual(p.best_mb, 1260)
        # 720p: 600+60=660 MB > 700*0.95=665? no -> fits; 480p 360; 360p 210; 240p 140; 144p 100
        self.assertEqual([h for h, _ in p.options], [720, 480, 360, 240, 144])
        self.assertEqual(p.options[0], (720, 660))

    def test_follows_ytdlp_preference_order_not_bitrate(self):
        # Two 1080p mp4 streams: H.264 (bigger) first, AV1 (smaller, preferred) last.
        info = {"duration": 600, "formats": [
            {"ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 10 * MB},
            {"ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 900 * MB},
            {"ext": "mp4", "vcodec": "av01", "acodec": "none", "height": 1080, "filesize": 400 * MB},
        ]}
        self.assertEqual(quality.estimate(info, 1080), (410 * MB, 1080))
        self.assertIsNone(quality.plan(info, limit_mb=700))

    def test_rough_size_lets_user_try_best(self):
        # HLS: only filesize_approx, ~2x the real size on YouTube.
        info = {"duration": 735, "formats": [
            {"ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 11 * MB},
            {"ext": "mp4", "vcodec": "av01", "acodec": "none", "height": 720, "filesize": 35 * MB},
            {"ext": "mp4", "vcodec": "vp09", "acodec": "none", "height": 1080, "filesize_approx": 900 * MB},
        ]}
        p = quality.plan(info, limit_mb=700)
        self.assertEqual(p.try_best, 1080)
        self.assertEqual(p.options, [(720, 46)])
        rows = quality.choice_rows("t", p)
        self.assertEqual(rows[0][0][1], "q:t:1080")
        self.assertIn("неточно", quality.choice_text(p))
        # Far above the limit even for a rough size: no "try" button.
        info["formats"][2]["filesize_approx"] = 3000 * MB
        self.assertIsNone(quality.plan(info, limit_mb=700).try_best)

    def test_exact_size_never_offers_try_best(self):
        self.assertIsNone(quality.plan(_info(), limit_mb=700).try_best)

    def test_margin_drops_borderline_quality(self):
        p = quality.plan(_info(video_mb={1080: 1200, 720: 640, 480: 300}), limit_mb=700)
        self.assertEqual([h for h, _ in p.options], [480])

    def test_nothing_fits(self):
        p = quality.plan(_info(video_mb={1080: 5000, 720: 3000}), limit_mb=700)
        self.assertEqual(p.options, [])
        self.assertIn("слишком большое", quality.choice_text(p))

    def test_bitrate_estimate_when_no_filesize(self):
        info = {"duration": 1000, "formats": [
            {"ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "tbr": 1000},
            {"ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 1080, "tbr": 8000},
        ]}
        p = quality.plan(info, limit_mb=700)  # 1080: 1000 MB, 360: 125 MB
        self.assertEqual([h for h, _ in p.options], [360])


class PendingTests(unittest.TestCase):
    def test_offer_is_per_user_and_one_shot(self):
        token = quality.offer(1, "https://example.com/v")
        self.assertIsNone(quality.take_offer(token, 2))
        self.assertEqual(quality.take_offer(token, 1), "https://example.com/v")
        self.assertIsNone(quality.take_offer(token, 1))

    def test_choice_is_consumed_once(self):
        quality.remember_choice(5, "https://example.com/v", 480)
        self.assertEqual(quality.take_choice(5, "https://example.com/v"), 480)
        self.assertIsNone(quality.take_choice(5, "https://example.com/v"))

    def test_rows_carry_token(self):
        p = quality.Plan(1200, [(720, 600), (480, 300)])
        rows = quality.choice_rows("ab12", p)
        self.assertEqual(rows[0][0], ("720p (~600 МБ)", "q:ab12:720"))
        self.assertEqual(rows[-1][0][1], "q:ab12:x")


class DownloadSelectorTests(unittest.TestCase):
    def test_download_uses_context_height_and_valid_duration_filter(self):
        captured = {}

        class FakeProc:
            returncode = 0

            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def communicate(self, timeout=None):
                return b"", b""

        token = quality.MAX_HEIGHT.set(480)
        try:
            with patch.object(processor.subprocess, "Popen", FakeProc), \
                 patch.object(processor, "validate_source_url", lambda u: u), \
                 patch.object(processor, "MAX_VIDEO_MINUTES", 80):
                with self.assertRaises(RuntimeError):  # no file produced by the fake
                    processor.download("https://example.com/v", Path("."), lambda p=None: None)
        finally:
            quality.MAX_HEIGHT.reset(token)
        cmd = captured["cmd"]
        self.assertIn(quality.format_selector(480), cmd)
        self.assertIn("duration <=? 4800", cmd)


class JobFlowTests(unittest.TestCase):
    def _engine(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
        bot.edit_message_text = AsyncMock()
        return handlers.Engine(bot), bot

    def test_too_big_link_gets_buttons_instead_of_download(self):
        engine, bot = self._engine()
        job = handlers.Job(1, 1, 77, 0, "https://example.com/v", None)
        download = MagicMock()
        with patch.object(handlers.db, "aget_user", AsyncMock(return_value={"format": "mp4"})), \
             patch.object(handlers, "playlist_items", lambda u, n: [u]), \
             patch.object(handlers, "validate_source_url", lambda u: u), \
             patch.object(handlers, "download", download), \
             patch.object(quality, "probe", lambda u: _info()), \
             patch.object(handlers.admin_stats, "record_job", AsyncMock()) as rec:
            asyncio.run(engine._run_job(job))
        download.assert_not_called()
        rec.assert_not_called()
        text = bot.send_message.call_args.args[1]
        self.assertIn("1260", text)
        markup = bot.send_message.call_args.kwargs["reply_markup"]
        self.assertTrue(markup.inline_keyboard[0][0].callback_data.startswith("q:"))

    def test_chosen_height_skips_probe(self):
        engine, bot = self._engine()
        url = "https://example.com/v2"
        quality.remember_choice(78, url, 480)
        job = handlers.Job(1, 1, 78, 0, url, None)
        seen = {}

        def fake_download(u, work, register):
            seen["height"] = quality.MAX_HEIGHT.get()
            raise RuntimeError("stop")

        probe = MagicMock()
        with patch.object(handlers.db, "aget_user", AsyncMock(return_value={"format": "mp4"})), \
             patch.object(handlers, "playlist_items", lambda u, n: [u]), \
             patch.object(handlers, "validate_source_url", lambda u: u), \
             patch.object(handlers, "download", fake_download), \
             patch.object(quality, "probe", probe), \
             patch.object(handlers.admin_stats, "record_job", AsyncMock()):
            asyncio.run(engine._run_job(job))
        probe.assert_not_called()
        self.assertEqual(seen["height"], 480)


if __name__ == "__main__":
    unittest.main()
