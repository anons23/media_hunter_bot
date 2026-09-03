from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from media_hunter_bot.process_cache import cached_process_media, clear


class ProcessCacheTests(unittest.TestCase):
    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_one_channel_uses_first_channel_watermark_and_reuses_exact_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "123_job"
            result = work / "result.mp4"
            source.write_bytes(b"source")
            work.mkdir()
            calls = []

            def processor(*args, **kwargs):
                calls.append(args[2])
                result.write_bytes(b"processed")
                return result

            first_channel = {"type": "text", "text": "REAL CHANNEL", "color": "red"}
            import json
            with patch(
                "media_hunter_bot.process_cache.db.list_channels",
                return_value=[{"enabled": 1, "watermark": json.dumps(first_channel)}],
            ):
                first = cached_process_media(
                    processor, source, work, {"type": "text", "text": "Мой канал"},
                    audio_only=False, compress=False, register=lambda *_: None,
                )
                second = cached_process_media(
                    processor, source, work, {"type": "image", "logo": "/tmp/old.png"},
                    audio_only=False, compress=False, register=lambda *_: None,
                )

            self.assertEqual(first, result)
            self.assertEqual(second, result)
            self.assertEqual(calls, [first_channel])

    def test_multiple_channels_use_first_channel_watermark_for_private_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "123_job"
            source.write_bytes(b"source")
            work.mkdir()

            processor_calls = []
            watermark_calls = []
            unique_base = work / "output.mp4"
            first_channel = {"type": "text", "text": "FIRST", "color": "white"}
            second_channel = {"type": "text", "text": "SECOND", "color": "blue"}

            def processor(source_path, work_path, watermark, *, audio_only, compress, register):
                processor_calls.append(dict(watermark))
                unique_base.write_bytes(b"unique")
                return unique_base

            def fake_apply(source_path, work_path, watermark, compress, register):
                watermark_calls.append(dict(watermark))
                result = work_path / f"wm-{len(watermark_calls)}.mp4"
                result.write_bytes(b"variant")
                return result

            import json
            rows = [
                {"enabled": 1, "watermark": json.dumps(first_channel)},
                {"enabled": 1, "watermark": json.dumps(second_channel)},
            ]
            with patch("media_hunter_bot.process_cache.db.list_channels", return_value=rows), \
                 patch("media_hunter_bot.process_cache.apply_watermark", side_effect=fake_apply):
                first = cached_process_media(
                    processor, source, work, {"type": "text", "text": "STALE USER"},
                    audio_only=False, compress=False, register=None,
                )
                second = cached_process_media(
                    processor, source, work, first_channel,
                    audio_only=False, compress=False, register=None,
                )
                third = cached_process_media(
                    processor, source, work, second_channel,
                    audio_only=False, compress=False, register=None,
                )

            self.assertEqual(processor_calls, [{}])
            self.assertEqual(first.name, "wm-1.mp4")
            self.assertEqual(second.name, "wm-2.mp4")
            self.assertEqual(third.name, "wm-3.mp4")
            self.assertEqual(watermark_calls, [first_channel, first_channel, second_channel])

    def test_different_watermarks_reuse_same_noncompressed_result_for_one_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "job"
            result = work / "result.mp4"
            source.write_bytes(b"source")
            work.mkdir()

            calls = []

            def processor(*args, **kwargs):
                calls.append((args[2], kwargs.get("compress")))
                result.write_bytes(b"processed")
                return result

            with patch("media_hunter_bot.process_cache.db.list_channels", return_value=[{"enabled": 1, "watermark": "{}"}]):
                first = cached_process_media(
                    processor, source, work, {"type": "text", "text": "user"},
                    audio_only=False, compress=False, register=lambda *_: None,
                )
                second = cached_process_media(
                    processor, source, work, {"type": "image", "logo": "/tmp/channel.png"},
                    audio_only=False, compress=False, register=lambda *_: None,
                )

            self.assertEqual(first, result)
            self.assertEqual(second, result)
            self.assertEqual(len(calls), 1)

    def test_multiple_channels_freeze_unique_base_and_render_each_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "123_job"
            source.write_bytes(b"source")
            work.mkdir()

            processor_calls = []
            watermark_calls = []
            unique_base = work / "output.mp4"
            first_channel = {"type": "text", "text": "CHANNEL-1"}
            second_channel = {"type": "text", "text": "CHANNEL-2"}

            def processor(source_path, work_path, watermark, *, audio_only, compress, register):
                processor_calls.append(dict(watermark))
                unique_base.write_bytes(b"unique")
                return unique_base

            def fake_apply(source_path, work_path, watermark, compress, register):
                watermark_calls.append((source_path, dict(watermark)))
                result = work_path / f"wm-{len(watermark_calls)}.mp4"
                result.write_bytes(b"variant")
                return result

            import json
            rows = [
                {"enabled": 1, "watermark": json.dumps(first_channel)},
                {"enabled": 1, "watermark": json.dumps(second_channel)},
                {"enabled": 1, "watermark": json.dumps({"type": "text", "text": "CHANNEL-3"})},
            ]
            with patch("media_hunter_bot.process_cache.db.list_channels", return_value=rows), \
                 patch("media_hunter_bot.process_cache.apply_watermark", side_effect=fake_apply):
                first = cached_process_media(
                    processor, source, work, {"type": "text", "text": "private"},
                    audio_only=False, compress=False, register=None,
                )
                second = cached_process_media(
                    processor, source, work, second_channel,
                    audio_only=False, compress=False, register=None,
                )

            self.assertEqual(processor_calls, [{}])
            self.assertEqual(first.name, "wm-1.mp4")
            self.assertEqual(second.name, "wm-2.mp4")
            self.assertEqual(len(watermark_calls), 2)
            self.assertEqual(watermark_calls[0][1], first_channel)
            self.assertEqual(watermark_calls[1][1], second_channel)
            self.assertTrue(all(call[0].name == "unique_base.mp4" for call in watermark_calls))

    def test_empty_watermark_returns_frozen_base_for_multiple_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "123_job"
            source.write_bytes(b"source")
            work.mkdir()
            output = work / "output.mp4"

            calls = []

            def processor(*args, **kwargs):
                calls.append(args[2])
                output.write_bytes(b"unique")
                return output

            with patch("media_hunter_bot.process_cache.db.list_channels", return_value=[{"enabled": 1}, {"enabled": 1}]):
                result = cached_process_media(
                    processor, source, work, {}, audio_only=False, compress=False, register=None,
                )

            self.assertEqual(result.name, "unique_base.mp4")
            self.assertEqual(calls, [{}])

    def test_compression_mode_has_separate_cache_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "job"
            result = work / "result.mp4"
            source.write_bytes(b"source")
            work.mkdir()

            calls = []

            def processor(*args, **kwargs):
                calls.append(kwargs.get("compress"))
                result.write_bytes(b"processed")
                return result

            cached_process_media(
                processor, source, work, None,
                audio_only=False, compress=False, register=lambda *_: None,
            )
            cached_process_media(
                processor, source, work, None,
                audio_only=False, compress=True, register=lambda *_: None,
            )

            self.assertEqual(calls, [False, True])


if __name__ == "__main__":
    unittest.main()
