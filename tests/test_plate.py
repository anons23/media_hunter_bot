import unittest

from media_hunter_bot import plate


class PlateTests(unittest.TestCase):
    def test_legacy_logo_is_converted(self):
        p = plate.normalize({"type": "image", "logo": "/x.png", "position": "bl", "logo_size": 30, "logo_opacity": 0.6})
        self.assertEqual((p["x"], p["y"], p["w"], p["opacity"]), (0.0, 1.0, 0.3, 0.6))
        self.assertEqual(p["timing"]["mode"], "all")

    def test_values_are_clamped(self):
        p = plate.normalize({"x": 5, "y": -1, "w": 9, "logo_opacity": 0, "timing": {"mode": "bogus", "start": -3}})
        self.assertEqual((p["x"], p["y"], p["w"]), (1.0, 0.0, 1.0))
        self.assertEqual(p["opacity"], plate.MIN_OPACITY)
        self.assertEqual(p["timing"]["mode"], "all")

    def test_windows(self):
        def win(timing, duration):
            return plate.window(plate.normalize({"x": 0, "y": 0, "w": 0.5, "timing": timing}), duration)

        self.assertEqual(win({"mode": "all"}, 30), (0.0, None, None))
        self.assertEqual(win({"mode": "start"}, 30), (1.0, 6.0, None))
        self.assertEqual(win({"mode": "end"}, 30), (25.0, None, None))
        self.assertEqual(win({"mode": "custom", "start": 2, "duration": 3}, 30), (2.0, 5.0, None))
        self.assertEqual(win({"mode": "custom", "start": 2, "duration": None}, 30), (2.0, None, None))

    def test_start_beyond_video_is_moved_and_reported(self):
        start, end, note = plate.window(
            plate.normalize({"x": 0, "y": 0, "w": 0.5, "timing": {"mode": "custom", "start": 10, "duration": 3}}), 6
        )
        self.assertEqual((start, end), (3.0, None))
        self.assertIn("Видео 6 с", note)

    def test_overlay_graph_timing_and_fade(self):
        p = plate.normalize({"x": 0.5, "y": 1, "w": 0.5, "logo_opacity": 0.9,
                             "timing": {"mode": "custom", "start": 2, "duration": 4}, "fade": True})
        g = plate.overlay_graph("eq=contrast=1", p, 1280, 20)
        self.assertIn("scale=640:-2", g)
        self.assertIn("fade=t=in:st=2.000", g)
        self.assertIn("fade=t=out:st=5.500:d=0.500", g)
        self.assertIn("enable='between(t,2.000,6.000)'", g)
        self.assertIn("shortest=1", g)

    def test_whole_video_plate_has_no_timing(self):
        g = plate.overlay_graph("", plate.normalize({"x": 0, "y": 0, "w": 0.3}), 1000, 10)
        self.assertNotIn("enable=", g)
        self.assertNotIn("fade=", g)

    def test_gif_loops_and_png_repeats(self):
        from pathlib import Path
        self.assertEqual(plate.input_args(Path("a.gif"))[:2], ["-ignore_loop", "0"])
        self.assertEqual(plate.input_args(Path("a.png"))[:2], ["-loop", "1"])


if __name__ == "__main__":
    unittest.main()
