"""Regression tests for the 2026-11-16 code review fixes."""
import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import db, handlers, optimized_processor, process_cache


def _member(status, **kw):
    return SimpleNamespace(status=status, **kw)


class ChannelOwnershipTests(unittest.TestCase):
    def test_only_creator_or_posting_admin_can_manage(self):
        async def check(member):
            bot = MagicMock()
            bot.get_chat_member = AsyncMock(return_value=member)
            return await handlers.user_can_manage_channel(bot, -100, 1)

        self.assertTrue(asyncio.run(check(_member("creator"))))
        self.assertTrue(asyncio.run(check(_member("administrator", can_post_messages=True))))
        self.assertFalse(asyncio.run(check(_member("administrator", can_post_messages=False))))
        self.assertFalse(asyncio.run(check(_member("member"))))
        self.assertFalse(asyncio.run(check(_member("left"))))

    def test_foreign_channel_is_rejected(self):
        async def run():
            bot = MagicMock()
            bot.id = 42
            bot.get_chat = AsyncMock(return_value=SimpleNamespace(id=-100500, type="channel", title="Чужой"))

            async def member(chat_id, user_id):
                return _member("administrator") if user_id == 42 else _member("member")

            bot.get_chat_member = AsyncMock(side_effect=member)
            m = SimpleNamespace(text="@foreign", from_user=SimpleNamespace(id=7), answer=AsyncMock())
            state = AsyncMock()
            with patch.object(db, "aadd_channel", new=AsyncMock()) as add:
                await handlers.addch_value(m, state, bot)
            add.assert_not_awaited()
            self.assertIn("владелец или администратор", m.answer.await_args.args[0])

        asyncio.run(run())

    def test_autopost_rechecks_channel_rights(self):
        source = inspect.getsource(handlers.Engine._run_job)
        self.assertIn("user_can_manage_channel", source)


class UploadAndThrottleTests(unittest.TestCase):
    def test_video_sent_as_file_is_accepted(self):
        def msg(mime, name):
            return SimpleNamespace(document=SimpleNamespace(mime_type=mime, file_name=name))

        self.assertTrue(handlers.is_video_document(msg("video/mp4", "a.mp4")))
        self.assertTrue(handlers.is_video_document(msg(None, "clip.MKV")))
        self.assertFalse(handlers.is_video_document(msg("image/png", "logo.png")))
        self.assertFalse(handlers.is_video_document(SimpleNamespace(document=None)))

    def test_upload_keeps_container_suffix(self):
        m = SimpleNamespace(video=None, document=SimpleNamespace(file_id="f", file_size=10, file_name="x.mov"))
        self.assertEqual(handlers._upload_media(m), ("f", 10, ".mov"))

    def test_links_and_media_are_not_throttled(self):
        async def run():
            mw = handlers.ThrottlingMiddleware(rate=10)
            handler = AsyncMock(return_value="ok")
            user = {"id": 5, "is_bot": False, "first_name": "u"}
            for _ in range(3):
                link = Message.model_validate({"message_id": 1, "date": 0, "chat": {"id": 5, "type": "private"}, "from": user, "text": "https://youtu.be/x"})
                self.assertEqual(await mw(handler, link, {}), "ok")
            self.assertEqual(handler.await_count, 3)

        asyncio.run(run())


class ReferralTests(unittest.TestCase):
    def test_unknown_referrer_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(db, "DB_PATH", Path(td) / "t.db"), patch.object(db, "ensure_directories", lambda: None):
                db.init_db()
                db.ensure_user(1)
                self.assertFalse(db.apply_referral(1, 999999))
                self.assertIsNone(db.get_user(999999))
                db.ensure_user(2)
                self.assertTrue(db.apply_referral(1, 2))
                self.assertEqual(db.get_referrals(2), 1)

    def test_start_applies_referral_only_for_new_users(self):
        source = inspect.getsource(handlers.start)
        self.assertIn("is_new_user", source)


class CompressAndTimeoutTests(unittest.TestCase):
    def test_compress_steps_down_until_under_soft_target(self):
        target = optimized_processor.SOFT_UNIQUE_SIZE_MB * 1024 * 1024
        sizes = iter([target + 1, target - 1])
        calls = []

        def fake_run(cmd, output, work_dir, register, timeout=None):
            calls.append(cmd)
            with Path(output).open("wb") as fh:
                fh.truncate(next(sizes))
            return Path(output)

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.mp4"
            src.write_bytes(b"x")
            with patch.object(optimized_processor, "_run_ffmpeg", side_effect=fake_run), \
                 patch.object(optimized_processor, "_input_duration", return_value=60):
                optimized_processor.process_media(src, Path(td), {}, audio_only=False, compress=True, register=lambda _p=None: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][calls[0].index("-crf") + 1], "30")
        self.assertEqual(calls[1][calls[1].index("-crf") + 1], "33")

    def test_timeout_scales_with_duration(self):
        self.assertEqual(optimized_processor._timeout_for(30), 600)
        self.assertEqual(optimized_processor._timeout_for(1800), 3600)
        self.assertEqual(optimized_processor._timeout_for(10 ** 6), 3 * 3600)

    def test_channel_autopost_reuses_compress_flag(self):
        source = inspect.getsource(handlers.Engine._run_job)
        self.assertIn("compress=unique_compress", source)


class AdminAndMiscTests(unittest.TestCase):
    def test_admin_premium_is_registered_and_in_menu(self):
        self.assertTrue(getattr(handlers.router, "_media_hunter_admin_premium", False))
        self.assertIn('"admin_premium"', inspect.getsource(handlers.admin))

    def test_process_cache_prunes_dead_entries(self):
        process_cache.clear()
        with tempfile.TemporaryDirectory() as td:
            alive = Path(td) / "a.mp4"
            alive.write_bytes(b"x")
            process_cache._base_cache[("dead", "w", False, False)] = Path(td) / "gone.mp4"
            process_cache._remember(("alive", "w", False, False), alive, process_cache._base_cache)
            self.assertNotIn(("dead", "w", False, False), process_cache._base_cache)
            self.assertIn(("alive", "w", False, False), process_cache._base_cache)
        process_cache.clear()

    def test_bot_commands_keep_paysupport(self):
        self.assertIn("paysupport", dict(media_hunter_bot._BOT_COMMANDS))


if __name__ == "__main__":
    unittest.main()
