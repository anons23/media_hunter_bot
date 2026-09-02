import unittest

from media_hunter_bot import processor
from media_hunter_bot.unique_filter import unique_video_filters


class MediaUniquenessRegressionTests(unittest.TestCase):
    def test_processor_uses_safe_even_dimension_filter(self):
        self.assertEqual(processor._unique_video_filters(), unique_video_filters())
        expr = processor._unique_video_filters()
        self.assertIn("trunc(iw*0.998/2)*2", expr)
        self.assertIn("trunc(ih*0.998/2)*2", expr)
        self.assertIn("trunc(iw*1.002004/2)*2", expr)
        self.assertIn("trunc(ih*1.002004/2)*2", expr)

    def test_common_vertical_dimensions_stay_even(self):
        # Mirrors the FFmpeg truncation expressions for common TikTok/YouTube
        # dimensions and verifies both scale stages remain encoder-safe.
        dimensions = ((720, 1280), (1080, 1920), (576, 1024), (1080, 1921), (721, 1281))
        for width, height in dimensions:
            first = (int(width * 0.998 / 2) * 2, int(height * 0.998 / 2) * 2)
            second = (int(first[0] * 1.002004 / 2) * 2, int(first[1] * 1.002004 / 2) * 2)
            self.assertEqual(first[0] % 2, 0, (width, height, first))
            self.assertEqual(first[1] % 2, 0, (width, height, first))
            self.assertEqual(second[0] % 2, 0, (width, height, second))
            self.assertEqual(second[1] % 2, 0, (width, height, second))


if __name__ == "__main__":
    unittest.main()
