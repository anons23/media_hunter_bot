import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media_hunter_bot


class TestOversizeRouting(unittest.TestCase):
    def test_over_100mb_bypasses_uniqueness_and_uses_compression_only(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            work = Path(td) / "work"
            with source.open("wb") as fh:
                fh.truncate((media_hunter_bot.MAX_UNIQUE_SIZE_MB * 1024 * 1024) + 1)

            expected = work / "compressed.mp4"
            with patch.object(media_hunter_bot, "_compress_for_send", return_value=expected) as compress, \
                 patch.object(media_hunter_bot, "_cached_process_media") as cached:
                result = media_hunter_bot._cached_process_entry(
                    source, work, {}, audio_only=False, compress=False, register=lambda _: None
                )

            self.assertIs(result, expected)
            compress.assert_called_once()
            cached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
