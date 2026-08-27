import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from media_hunter_bot import db
from media_hunter_bot import handlers
from media_hunter_bot import processor
from media_hunter_bot import config


class SecurityRegressionTests(unittest.TestCase):
    def test_source_url_rejects_non_http(self):
        for url in ("file:///etc/passwd", "ftp://example.com/file", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                processor.validate_source_url(url)

    def test_source_url_rejects_loopback_without_dns(self):
        with patch.object(processor.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with self.assertRaises(ValueError):
                processor.validate_source_url("http://localhost/test")

    def test_source_url_rejects_private_address(self):
        with patch.object(processor.socket, "getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.1", 0))]):
            with self.assertRaises(ValueError):
                processor.validate_source_url("https://internal.example/test")

    def test_source_url_allows_public_address(self):
        with patch.object(processor.socket, "getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
            self.assertEqual(
                processor.validate_source_url("https://example.com/video"),
                "https://example.com/video",
            )

    def test_media_policy_thresholds(self):
        self.assertEqual(config.SOFT_UNIQUE_SIZE_MB, 80)
        self.assertEqual(config.MAX_UNIQUE_SIZE_MB, 100)
        self.assertEqual(config.MAX_URL_LOGICAL_MB, 100)
        self.assertEqual(config.MAX_SOURCE_DOWNLOAD_MB, 1536)
        self.assertEqual(config.MAX_USER_UPLOAD_MB, 1536)
        self.assertGreater(config.MAX_SOURCE_DOWNLOAD_MB, config.MAX_UNIQUE_SIZE_MB)

    def test_logo_path_is_confined_to_logo_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logo = root / "logo.png"
            logo.write_bytes(b"test")
            outside = root.parent / "outside-logo.png"
            outside.write_bytes(b"test")
            try:
                with patch.object(processor, "LOGO_DIR", root):
                    self.assertEqual(processor._logo_path({"logo": str(logo)}), logo.resolve())
                    self.assertIsNone(processor._logo_path({"logo": str(outside)}))
                    self.assertIsNone(processor._logo_path({"logo": str(root / ".." / outside.name)}))
            finally:
                outside.unlink(missing_ok=True)

    def test_restart_removes_queued_jobs_and_balances_task_done(self):
        async def run():
            engine = handlers.Engine(None)
            engine._max_queue = 10
            engine._queue_size = 2
            engine._user_queue_size[123] = 2
            engine.gen[123] = 0
            engine.seq = 2
            await engine.q.put(handlers.Job(1, 1, 123, 0, "https://example.com/1", None))
            await engine.q.put(handlers.Job(1, 2, 123, 0, "https://example.com/2", None))
            await engine.restart(123)
            self.assertEqual(engine.q.qsize(), 0)
            self.assertEqual(engine._queue_size, 0)
            self.assertEqual(engine._user_queue_size.get(123, 0), 0)
            await asyncio.wait_for(engine.q.join(), timeout=1)

        asyncio.run(run())

    def test_add_and_restart_are_serialized(self):
        async def run():
            engine = handlers.Engine(None)
            engine._max_queue = 10
            engine.gen[123] = 0
            engine.seq = 0

            original_put = engine.q.put
            put_started = asyncio.Event()
            allow_put = asyncio.Event()

            async def blocked_put(job):
                put_started.set()
                await allow_put.wait()
                await original_put(job)

            with patch.object(engine.q, "put", new=blocked_put), \
                 patch.object(db, "aensure_user", new=AsyncMock()), \
                 patch.object(db, "ais_premium", new=AsyncMock(return_value=False)):

                add_task = asyncio.create_task(
                    engine.add(123, url="https://example.com/video")
                )

                await asyncio.wait_for(put_started.wait(), timeout=1)

                restart_task = asyncio.create_task(engine.restart(123))

                await asyncio.sleep(0)

                self.assertFalse(
                    restart_task.done(),
                    "restart() должен ждать _lock, пока add() добавляет Job в очередь",
                )

                allow_put.set()

                await asyncio.wait_for(add_task, timeout=1)
                await asyncio.wait_for(restart_task, timeout=1)

            self.assertEqual(engine.q.qsize(), 0)
            self.assertEqual(engine._queue_size, 0)
            self.assertEqual(engine._user_queue_size.get(123, 0), 0)

        asyncio.run(run())

    def test_worker_cancellation_while_waiting_does_not_call_task_done(self):
        async def run():
            engine = handlers.Engine(None)
            worker = asyncio.create_task(engine._worker())
            await asyncio.sleep(0)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
            self.assertEqual(engine.q._unfinished_tasks, 0)

        asyncio.run(run())

    def test_existing_private_opp_is_not_silently_satisfied(self):
        async def run():
            rows = [{"slot": 1, "url": "https://t.me/+privatehash", "title": "Private"}]
            bot = AsyncMock()
            with patch.object(db, "aactive_opp", new=AsyncMock(return_value=rows)):
                missing, keyboard = await handlers.opp_check(bot, 123)
            self.assertTrue(missing)
            self.assertTrue(keyboard)
            bot.get_chat_member.assert_not_awaited()

        asyncio.run(run())

    def test_reboot_handler_removed_completely(self):
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        for forbidden in (
            '"areboot"',
            "async def areboot",
            "def _reboot_later",
            "_reboot_later()",
            "VPS перезагружается",
        ):
            self.assertNotIn(forbidden, source)

    def test_referral_update_is_guarded_by_referred_by_null(self):
        source = Path(db.__file__).read_text(encoding="utf-8")
        self.assertIn("AND referred_by IS NULL", source)
        self.assertIn("if c.rowcount != 1:", source)

    def test_playlist_items_are_validated_before_queueing(self):
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        self.assertIn("safe_item_url = validate_source_url(u)", source)
        self.assertIn("Skipping unsafe playlist item", source)

    def test_logical_limit_is_explicitly_configurable(self):
        source = Path(config.__file__).read_text(encoding="utf-8")
        self.assertIn('os.getenv("MAX_URL_LOGICAL_MB", str(MAX_UNIQUE_SIZE_MB))', source)


if __name__ == "__main__":
    unittest.main()
