import inspect
import unittest

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
        from media_hunter_bot import __file__ as package_file
        source = inspect.getsource(__import__("media_hunter_bot"))
        self.assertIn('kwargs.setdefault("is_local", True)', source)


if __name__ == "__main__":
    unittest.main()
