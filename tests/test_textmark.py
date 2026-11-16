import tempfile
import unittest
from pathlib import Path

from media_hunter_bot import textmark


class TextmarkTests(unittest.TestCase):
    def test_bundled_fonts_exist_with_licenses(self):
        for font_id in textmark.FONTS:
            self.assertTrue((textmark.FONT_DIR / f"{font_id}.ttf").exists(), font_id)
        self.assertTrue(any((textmark.FONT_DIR / "licenses").glob("*OFL*")))

    def test_legacy_is_converted(self):
        cfg = textmark.normalize({"type": "text", "text": "Hi", "position": "tl", "size": 54, "color": "yellow", "font": "bold"})
        self.assertEqual((cfg["x"], cfg["y"]), (0.0, 0.0))
        self.assertEqual(cfg["font"], "ptsans_bold")
        self.assertEqual(cfg["color"], "#FFD60A")
        self.assertAlmostEqual(cfg["size"], 0.05, places=3)
        self.assertFalse(textmark.is_new_format({"type": "text", "text": "Hi"}))

    def test_values_are_sanitized(self):
        cfg = textmark.normalize({"type": "text", "x": 3, "y": -2, "size": 9, "font": "../../etc", "color": "red;evil",
                                  "style": "x", "accent": "#abc", "text": "a\n\nb\nc\nd 🔥"})
        self.assertEqual((cfg["x"], cfg["y"], cfg["size"]), (1.0, 0.0, textmark.MAX_SIZE))
        self.assertEqual(cfg["font"], textmark.DEFAULT_FONT)
        self.assertEqual(cfg["color"], "#FFFFFF")
        self.assertEqual(cfg["accent"], "#AABBCC")
        self.assertEqual(cfg["style"], "shadow")
        self.assertEqual(cfg["text"], "a\nb\nc")

    def test_drawtext_outline_and_box(self):
        with tempfile.TemporaryDirectory() as td:
            base = {"type": "text", "text": "50% Мой", "x": 0.5, "y": 1, "size": 0.05, "font": "montserrat"}
            out = textmark.drawtext_filter(textmark.normalize({**base, "style": "outline"}), 1000, Path(td))
            self.assertIn("expansion=none", out)
            self.assertIn("fontsize=50", out)
            self.assertIn("borderw=4", out)
            self.assertIn("montserrat.ttf", out)
            self.assertIn("x='4+(w-text_w-8)*0.5000'", out)
            box = textmark.drawtext_filter(textmark.normalize({**base, "style": "box"}), 1000, Path(td))
            self.assertIn("box=1", box)
            self.assertIn("boxborderw=18", box)
            self.assertEqual((Path(td) / "wm_text.txt").read_text(encoding="utf-8"), "50% Мой")

    def test_empty_text_has_no_filter(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(textmark.drawtext_filter(textmark.normalize({"type": "text", "x": 0, "y": 0}), 720, Path(td)))


if __name__ == "__main__":
    unittest.main()
