import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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

    def test_video_gets_clear_message(self):
        with self.assertRaisesRegex(ValueError, "видео"):
            wm_wizard._document_logo_ext(doc("giphy.mp4", "video/mp4"), 1)

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


if __name__ == "__main__":
    unittest.main()
