import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import wm_wizard


def doc(name=None, mime=None, size=1000):
    return SimpleNamespace(file_name=name, mime_type=mime, file_size=size, file_id="f")


class DocumentLogoExtTests(unittest.TestCase):
    def test_by_name(self):
        self.assertEqual(wm_wizard._document_logo_ext(doc("Logo.GIF"), 1), ".gif")
        self.assertEqual(wm_wizard._document_logo_ext(doc("a.png"), 1), ".png")

    def test_by_mime_when_name_has_no_extension(self):
        self.assertEqual(wm_wizard._document_logo_ext(doc("logo", "image/gif"), 1), ".gif")
        self.assertEqual(wm_wizard._document_logo_ext(doc(None, "image/png"), 1), ".png")

    def test_unknown_is_left_to_signature_check(self):
        self.assertEqual(wm_wizard._document_logo_ext(doc(None, None), 1), ".gif")

    def test_video_is_marked_for_conversion(self):
        self.assertEqual(wm_wizard._document_logo_ext(doc("giphy.mp4", "video/mp4"), 1), ".mp4")
        self.assertEqual(wm_wizard._document_logo_ext(doc(None, "video/mp4"), 1), ".mp4")

    def test_other_format_names_it(self):
        with self.assertRaisesRegex(ValueError, "WEBP"):
            wm_wizard._document_logo_ext(doc("a.webp", "image/webp"), 1)


class SniffTests(unittest.TestCase):
    def _file(self, data: bytes) -> Path:
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(data)
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return Path(f.name)

    def test_signatures(self):
        self.assertEqual(wm_wizard._sniff_image(self._file(b"GIF89a....")), ".gif")
        self.assertEqual(wm_wizard._sniff_image(self._file(b"GIF87a....")), ".gif")
        self.assertEqual(wm_wizard._sniff_image(self._file(b"\x89PNG\r\n\x1a\n....")), ".png")
        self.assertIsNone(wm_wizard._sniff_image(self._file(b"\x00\x00\x00\x18ftypmp42")))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class Mp4AnimationToGifTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _mp4(self, seconds=2):
        path = self.tmp / "anim.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
             "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        return path

    def test_video_to_gif(self):
        out = self.tmp / "out.gif"
        wm_wizard._video_to_gif(self._mp4(), out, 10)
        self.assertEqual(wm_wizard._sniff_image(out), ".gif")

    def _message(self, mp4: Path, as_animation: bool):
        file = SimpleNamespace(file_id="f", file_size=mp4.stat().st_size, file_name="giphy.mp4", mime_type="video/mp4")
        return SimpleNamespace(
            from_user=SimpleNamespace(id=42), photo=None,
            document=None if as_animation else file,
            animation=file if as_animation else None,
        )

    def _bot(self, mp4: Path):
        async def download_file(path, destination):
            shutil.copy(mp4, destination)
        return SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="x")),
            download_file=download_file,
        )

    def test_telegram_mp4_gif_becomes_gif_logo(self):
        mp4 = self._mp4()
        for as_animation in (False, True):
            with patch.object(wm_wizard, "LOGO_DIR", self.tmp / "logos"):
                final, fmt = asyncio.run(wm_wizard._download_logo_message(self._message(mp4, as_animation), self._bot(mp4)))
            self.assertEqual(final.suffix, ".gif")
            self.assertEqual(wm_wizard._sniff_image(final), ".gif")
            self.assertIn("без прозрачного фона", fmt)
            leftovers = [p.name for p in (self.tmp / "logos").iterdir() if p.name.startswith(".upload_")]
            self.assertEqual(leftovers, [])

    def test_too_long_animation_is_rejected(self):
        mp4 = self._mp4(seconds=20)
        with patch.object(wm_wizard, "LOGO_DIR", self.tmp / "logos"):
            with self.assertRaisesRegex(ValueError, "слишком длинная"):
                asyncio.run(wm_wizard._download_logo_message(self._message(mp4, False), self._bot(mp4)))
        self.assertEqual(list((self.tmp / "logos").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
