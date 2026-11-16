import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_hunter_bot import optimized_processor


class TestOptimizedLogo(unittest.TestCase):
    def test_logo_watermark_uses_configured_size_and_opacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "source.mp4"
            logo = work / "logo.png"
            source.touch()
            logo.touch()

            captured = {}

            def fake_run_ffmpeg(cmd, output, work_dir, register):
                captured["cmd"] = cmd
                return output

            watermark = {
                "type": "image",
                "logo": str(logo),
                "logo_size": 40,
                "logo_opacity": 0.6,
                "position": "tr",
            }

            with patch.object(optimized_processor.base, "_logo_path", return_value=logo), \
                 patch.object(optimized_processor, "_probe_frame", return_value=(1000, 500, 10.0)), \
                 patch.object(optimized_processor, "_run_ffmpeg", side_effect=fake_run_ffmpeg):
                result = optimized_processor.apply_watermark(
                    source, work, watermark, False, lambda _proc=None: None
                )

            self.assertTrue(result.name.startswith("watermark_"))
            cmd = captured["cmd"]
            graph = cmd[cmd.index("-filter_complex") + 1]
            # Legacy logo: 40% of the video width, top-right, 60% opacity.
            self.assertIn("colorchannelmixer=aa=0.600", graph)
            self.assertIn("scale=400:-2", graph)
            self.assertIn("overlay=x='(W-w)*1.0000':y='(H-h)*0.0000'", graph)
            self.assertNotIn("scale2ref", graph)
            # Still image is looped so timing/fade work on every frame.
            self.assertIn("-loop", cmd)


if __name__ == "__main__":
    unittest.main()
