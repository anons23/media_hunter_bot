from pathlib import Path
import tempfile
import unittest

from media_hunter_bot.process_cache import cached_process_media, clear


class ProcessCacheTests(unittest.TestCase):
    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_different_watermarks_reuse_same_noncompressed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "job"
            result = work / "result.mp4"
            source.write_bytes(b"source")
            work.mkdir()

            calls = []

            def processor(*args, **kwargs):
                calls.append((args[2], kwargs.get("compress")))
                result.write_bytes(b"processed")
                return result

            first = cached_process_media(
                processor,
                source,
                work,
                {"type": "text", "text": "user"},
                audio_only=False,
                compress=False,
                register=lambda *_: None,
            )
            second = cached_process_media(
                processor,
                source,
                work,
                {"type": "logo", "path": "/tmp/channel.png"},
                audio_only=False,
                compress=False,
                register=lambda *_: None,
            )

            self.assertEqual(first, result)
            self.assertEqual(second, result)
            self.assertEqual(len(calls), 1)

    def test_compression_mode_has_separate_cache_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            work = root / "job"
            result = work / "result.mp4"
            source.write_bytes(b"source")
            work.mkdir()

            calls = []

            def processor(*args, **kwargs):
                calls.append(kwargs.get("compress"))
                result.write_bytes(b"processed")
                return result

            cached_process_media(
                processor,
                source,
                work,
                None,
                audio_only=False,
                compress=False,
                register=lambda *_: None,
            )
            cached_process_media(
                processor,
                source,
                work,
                None,
                audio_only=False,
                compress=True,
                register=lambda *_: None,
            )

            self.assertEqual(calls, [False, True])


if __name__ == "__main__":
    unittest.main()
