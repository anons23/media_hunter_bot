import asyncio
import tempfile
import unittest
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

from media_hunter_bot import db
from media_hunter_bot import handlers
from media_hunter_bot import processor
from media_hunter_bot import config
from media_hunter_bot.config import MAX_USER_QUEUE


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

    def test_source_url_rejects_blocked_hostnames(self):
        blocked = (
            "http://localhost/video",
            "https://localhost.localdomain/x",
            "http://metadata/computeMetadata/v1/",
            "https://metadata.google.internal/",
            "http://foo.local/bar",
            "https://app.localhost/path",
            "http://svc.internal/api",
            "https://files.intranet/media",
            "http://nas.corp/share",
            "https://router.home/stream",
            "http://printer.lan/scan",
        )
        for url in blocked:
            with self.assertRaises(ValueError, msg=url):
                processor.validate_source_url(url)

    def test_source_url_rejects_literal_private_ip(self):
        for url in (
            "http://127.0.0.1/video",
            "https://10.0.0.5/x",
            "http://192.168.1.1/stream",
            "https://[::1]/v",
            "http://169.254.169.254/latest/meta-data/",
        ):
            with self.assertRaises(ValueError, msg=url):
                processor.validate_source_url(url)

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

    def test_ensure_can_enqueue_rejects_full_queues(self):
        async def run():
            engine = handlers.Engine(None)
            engine._max_queue = 2
            engine._queue_size = 2
            with self.assertRaises(RuntimeError):
                await engine.ensure_can_enqueue(42)

            engine._queue_size = 0
            engine._user_queue_size[42] = MAX_USER_QUEUE
            with self.assertRaises(RuntimeError):
                await engine.ensure_can_enqueue(42)

            engine._user_queue_size[42] = 0
            engine._restarting.add(42)
            with self.assertRaises(RuntimeError):
                await engine.ensure_can_enqueue(42)

            engine._restarting.discard(42)
            await engine.ensure_can_enqueue(42)

        asyncio.run(run())

    def test_upload_checks_queue_before_download(self):
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        upload_start = source.index("async def upload(")
        ensure_pos = source.index("ensure_can_enqueue", upload_start)
        download_pos = source.index("download_file", upload_start)
        self.assertLess(
            ensure_pos,
            download_pos,
            "upload must call ensure_can_enqueue before download_file",
        )

    def test_oversized_original_is_rejected_before_private_send(self):
        async def run():
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                source = root / "source.mp4"
                source_size = config.MAX_SEND_MB * 1024 * 1024 + 1
                with source.open("wb") as f:
                    f.truncate(source_size)

                engine = handlers.Engine(AsyncMock())
                job = handlers.Job(1, 1, 123, 0, None, source)
                engine.gen[123] = 0

                user = {"format": "mp4"}
                with patch.object(handlers, "MEDIA_DIR", root), \
                     patch.object(db, "aget_user", new=AsyncMock(return_value=user)), \
                     patch.object(db, "aget_user_watermark", new=AsyncMock(return_value=None)), \
                     patch.object(db, "alist_channels", new=AsyncMock(return_value=[])), \
                     patch.object(handlers, "ffprobe", return_value=("mp4", config.MAX_UNIQUE_SIZE_MB * 1024 * 1024 + 1)), \
                     patch.object(handlers, "metadata", return_value={}):

                    engine._send_private = AsyncMock()
                    await engine._run_job(job)

                    engine._send_private.assert_not_awaited()
                    engine.bot.send_message.assert_awaited_once()
                    self.assertIn("Результат превышает лимит отправки", engine.bot.send_message.await_args.args[1])

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
        self.assertIn("if cur.rowcount != 1:", source)

    def test_payment_activation_is_atomic(self):
        source = inspect.getsource(db.save_payment)
    
        self.assertIn("INSERT OR IGNORE INTO payments", source)
        self.assertIn("UPDATE users", source)
        self.assertIn("premium_until", source)
        self.assertIn("commit", source)
    
        insert_pos = source.index("INSERT OR IGNORE INTO payments")
        update_pos = source.index("UPDATE users", insert_pos)
        commit_pos = source.index("commit", update_pos)
    
        self.assertLess(insert_pos, update_pos)
        self.assertLess(update_pos, commit_pos)

    def test_playlist_items_are_validated_before_queueing(self):
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        self.assertIn("safe_item_url = validate_source_url(u)", source)
        self.assertIn("Skipping unsafe playlist item", source)

    def test_logical_limit_matches_unique_limit(self):
        self.assertEqual(
            config.MAX_URL_LOGICAL_MB,
            config.MAX_UNIQUE_SIZE_MB,
        )


if __name__ == "__main__":
    unittest.main()
