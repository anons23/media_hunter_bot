import inspect
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_hunter_bot import processor
from media_hunter_bot.unique_filter import unique_video_filters


class MediaUniquenessRegressionTests(unittest.TestCase):
    def test_processor_uses_safe_even_dimension_filter(self):
        expr = processor._unique_video_filters()
        self.assertIn("trunc(iw*0.998/2)*2", expr)
        self.assertIn("trunc(ih*0.998/2)*2", expr)
        self.assertIn("eq=contrast=", expr)
        self.assertNotIn("unsharp=", expr)
        self.assertNotIn("noise=", expr)

    def test_controlled_variation_stays_in_safe_ranges(self):
        from media_hunter_bot import unique_filter

        with patch.object(unique_filter.random, "uniform", side_effect=[0.991, -0.004, 1.029]):
            expr = unique_video_filters()
        self.assertIn("contrast=0.9910", expr)
        self.assertIn("brightness=-0.0040", expr)
        self.assertIn("saturation=1.0290", expr)
        self.assertNotIn("noise=", expr)
        self.assertNotIn("unsharp=", expr)

    def test_controlled_variation_uses_declared_bounds(self):
        from media_hunter_bot import unique_filter

        values = iter([0.99, -0.005, 0.99])
        with patch.object(unique_filter.random, "uniform", side_effect=lambda _low, _high: next(values)):
            low = unique_video_filters()
        values = iter([1.02, 0.008, 1.03])
        with patch.object(unique_filter.random, "uniform", side_effect=lambda _low, _high: next(values)):
            high = unique_video_filters()
        self.assertIn("contrast=0.9900", low)
        self.assertIn("brightness=-0.0050", low)
        self.assertIn("saturation=0.9900", low)
        self.assertIn("contrast=1.0200", high)
        self.assertIn("brightness=0.0080", high)
        self.assertIn("saturation=1.0300", high)

    def test_variation_is_not_fixed_between_processing_passes(self):
        from media_hunter_bot import unique_filter

        with patch.object(unique_filter.random, "uniform", side_effect=[1.0, 0.0, 1.0, 1.01, 0.001, 1.02]):
            first = unique_video_filters()
            second = unique_video_filters()
        self.assertNotEqual(first, second)

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
        self.assertTrue('"-preset", "veryfast"' in source or '"-preset", "superfast"' in source)

    def test_processed_media_validation_accepts_valid_video(self):
        from media_hunter_bot.optimized_processor import _validate_processed_media

        class Proc:
            returncode = 0
            stdout = '{"format":{"duration":"2.5"},"streams":[{"codec_type":"video","width":720,"height":1280}]}'
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp, patch("media_hunter_bot.optimized_processor.subprocess.run", return_value=Proc()):
            output = Path(tmp) / "output.mp4"
            output.write_bytes(b"video")
            _validate_processed_media(output, audio_only=False)

    def test_processed_media_validation_rejects_empty_result(self):
        from media_hunter_bot.optimized_processor import _validate_processed_media

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.mp4"
            output.touch()
            with self.assertRaisesRegex(RuntimeError, "не создан или пуст"):
                _validate_processed_media(output, audio_only=False)

    def test_processed_media_validation_rejects_missing_video_stream(self):
        from media_hunter_bot.optimized_processor import _validate_processed_media

        class Proc:
            returncode = 0
            stdout = '{"format":{"duration":"2.5"},"streams":[]}'
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp, patch("media_hunter_bot.optimized_processor.subprocess.run", return_value=Proc()):
            output = Path(tmp) / "output.mp4"
            output.write_bytes(b"video")
            with self.assertRaisesRegex(RuntimeError, "ожидаемый медиапоток"):
                _validate_processed_media(output, audio_only=False)

    def test_cached_process_entry_accepts_legacy_positional_call(self):
        import media_hunter_bot

        original_cache = media_hunter_bot._cached_process_media
        original_processor = media_hunter_bot._optimized_process_media
        calls = []

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

    def test_cached_process_entry_resolves_runtime_dependencies(self):
        import media_hunter_bot

        original_cache = media_hunter_bot._cached_process_media
        original_processor = media_hunter_bot._optimized_process_media
        calls = []

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
            self.assertEqual(second, third)
            self.assertEqual(len(calls), 1)
            clear()


if __name__ == "__main__":
    unittest.main()
