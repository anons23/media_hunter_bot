import inspect
import tempfile
import unittest
from pathlib import Path

from media_hunter_bot import processor
from media_hunter_bot.unique_filter import unique_video_filters


class MediaUniquenessRegressionTests(unittest.TestCase):
    def test_processor_uses_safe_even_dimension_filter(self):
        self.assertEqual(processor._unique_video_filters(), unique_video_filters())
        expr = processor._unique_video_filters()
        self.assertIn("trunc(iw*0.998/2)*2", expr)
        self.assertIn("trunc(ih*0.998/2)*2", expr)
        self.assertNotIn("unsharp=", expr)
        self.assertNotIn("noise=", expr)

    def test_common_vertical_dimensions_stay_even(self):
        dimensions = ((720, 1280), (1080, 1920), (576, 1024), (1080, 1921), (721, 1281))
        for width, height in dimensions:
            scaled = (int(width * 0.998 / 2) * 2, int(height * 0.998 / 2) * 2)
            self.assertEqual(scaled[0] % 2, 0, (width, height, scaled))
            self.assertEqual(scaled[1] % 2, 0, (width, height, scaled))

    def test_video_encoder_is_cpu_bounded_and_fast_preset(self):
        from media_hunter_bot import optimized_processor

        source = inspect.getsource(optimized_processor.process_media)
        self.assertIn('"-threads", "2"', source)
        self.assertIn('"-preset", "veryfast"', source)
        self.assertIn('"-crf", "27"', source)

    def test_local_bot_api_is_configured_for_absolute_file_paths(self):
        source = inspect.getsource(__import__("media_hunter_bot"))
        self.assertIn('kwargs.setdefault("is_local", True)', source)

    def test_cached_process_entry_accepts_legacy_positional_call(self):
        import media_hunter_bot

        signature = inspect.signature(media_hunter_bot._cached_process_entry)
        for name in ("audio_only", "compress", "register"):
            self.assertNotEqual(signature.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_cached_process_entry_resolves_runtime_dependencies(self):
        import media_hunter_bot

        calls = []
        original_cache = media_hunter_bot._cached_process_media
        original_processor = media_hunter_bot._optimized_process_media

        def fake_cache(processor_fn, source, work, watermark, *, audio_only, compress, register):
            calls.append((processor_fn, source, work, watermark, audio_only, compress, register))
            return "ok"

        def fake_processor(*args, **kwargs):
            return "processed"

        try:
            media_hunter_bot._cached_process_media = fake_cache
            media_hunter_bot._optimized_process_media = fake_processor
            result = media_hunter_bot._cached_process_entry(
                "source", "work", {"type": "text"}, False, True, "register"
            )
        finally:
            media_hunter_bot._cached_process_media = original_cache
            media_hunter_bot._optimized_process_media = original_processor

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], fake_processor)
        self.assertEqual(calls[0][1:], ("source", "work", {"type": "text"}, False, True, "register"))

    def test_identical_processing_profile_is_reused(self):
        from media_hunter_bot.process_cache import cached_process_media, clear

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "work"
            source.write_bytes(b"source")
            work.mkdir()

            def fake_processor(source_path, work_path, watermark, *, audio_only, compress, register):
                calls.append((source_path, work_path, watermark, audio_only, compress, register))
                result = work_path / f"out-{len(calls)}.mp4"
                result.write_bytes(b"result")
                return result

            clear()
            first = cached_process_media(fake_processor, source, work, {"type": "text", "text": "A"}, audio_only=False, compress=False, register=None)
            second = cached_process_media(fake_processor, source, work, {"type": "text", "text": "A"}, audio_only=False, compress=False, register=None)
            third = cached_process_media(fake_processor, source, work, {"type": "text", "text": "B"}, audio_only=False, compress=False, register=None)
            self.assertEqual(first, second)
            self.assertNotEqual(first, third)
            self.assertEqual(len(calls), 2)
            clear()


if __name__ == "__main__":
    unittest.main()
