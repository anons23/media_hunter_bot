import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import oversize_processor as op

MB = 1024 * 1024


def _sparse(path: Path, size: int) -> Path:
    with path.open("wb") as fh:
        fh.truncate(size)
    return path


def _fake_run_factory(out_size: int, calls: list):
    def fake_run(cmd, output, register, timeout):
        calls.append(cmd)
        _sparse(Path(output), out_size)
        return Path(output)
    return fake_run


class TestOversizePolicy(unittest.TestCase):
    def test_100_to_130_mb_mp4_is_sent_as_original_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as td:
            source = _sparse(Path(td) / "source.mp4", 120 * MB)
            with patch.object(op, "_run") as run:
                result = op.compress_for_send(source, Path(td) / "work", {}, lambda _p: None)
            self.assertEqual(result, source)
            run.assert_not_called()

    def test_100_to_130_mb_non_mp4_is_only_remuxed(self):
        with tempfile.TemporaryDirectory() as td:
            source = _sparse(Path(td) / "source.mkv", 120 * MB)
            calls: list = []
            with patch.object(op, "_run", side_effect=_fake_run_factory(120 * MB, calls)), \
                 patch.object(op, "_validate_processed_media"):
                result = op.compress_for_send(source, Path(td) / "work", {}, lambda _p: None)
            self.assertEqual(result.name, "original.mp4")
            self.assertEqual(len(calls), 1)
            self.assertIn("copy", calls[0])
            self.assertNotIn("libx264", calls[0])

    def test_over_130_mb_uses_gentle_crf_compression(self):
        with tempfile.TemporaryDirectory() as td:
            source = _sparse(Path(td) / "source.mp4", 300 * MB)
            info = {
                "format": {"duration": "600"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
            calls: list = []
            with patch.object(op.base, "ffprobe", return_value=(info, 300 * MB)), \
                 patch.object(op, "_run", side_effect=_fake_run_factory(200 * MB, calls)), \
                 patch.object(op, "_validate_processed_media"):
                result = op.compress_for_send(source, Path(td) / "work", {}, lambda _p: None)
            self.assertEqual(result.name, "oversize_plain.mp4")
            cmd = calls[0]
            self.assertEqual(cmd[cmd.index("-crf") + 1], str(op.OVERSIZE_CRF))
            self.assertNotIn("-b:v", cmd)
            self.assertNotIn("-maxrate", cmd)
            # AAC audio is copied untouched.
            self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")

    def test_compression_that_does_not_shrink_falls_back_to_original(self):
        with tempfile.TemporaryDirectory() as td:
            source = _sparse(Path(td) / "source.mp4", 200 * MB)
            info = {"format": {"duration": "60"}, "streams": [{"codec_type": "video"}]}
            with patch.object(op.base, "ffprobe", return_value=(info, 200 * MB)), \
                 patch.object(op, "_run", side_effect=_fake_run_factory(250 * MB, [])), \
                 patch.object(op, "_validate_processed_media"):
                result = op.compress_for_send(source, Path(td) / "work", {}, lambda _p: None)
            self.assertEqual(result, source)

    def test_timeout_is_not_retried_without_watermark(self):
        with tempfile.TemporaryDirectory() as td:
            source = _sparse(Path(td) / "source.mp4", 200 * MB)
            info = {"format": {"duration": "60"}, "streams": [{"codec_type": "video"}]}
            wm = {"type": "text", "text": "hello"}
            with patch.object(op.base, "ffprobe", return_value=(info, 200 * MB)), \
                 patch.object(op, "_run", side_effect=op._EncodeTimeout("timeout")) as run:
                with self.assertRaises(RuntimeError):
                    op.compress_for_send(source, Path(td) / "work", wm, lambda _p: None)
            self.assertEqual(run.call_count, 1)

    def test_timeout_scales_with_duration(self):
        self.assertEqual(op._timeout_for(10), op._MIN_TIMEOUT)
        self.assertEqual(op._timeout_for(3600), 3 * 3600)
        self.assertEqual(op._timeout_for(10 ** 6), op._MAX_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
