import asyncio
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import admin_stats, db, handlers


class AdminStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(db, "DB_PATH", Path(self.tmp.name) / "t.db"),
                        patch.object(db, "ensure_directories", lambda: None)]
        for p in self.patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_user_and_job_statistics(self):
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        for uid in (1, 2, 3):
            db.ensure_user(uid)
        with db._db() as c:
            c.execute("UPDATE users SET created_at=? WHERE user_id=3", (old,))
        admin_stats.touch_user_sync(1)
        admin_stats.record_job_sync(1, "url", "ok", 12.5, 30, None)
        admin_stats.record_job_sync(2, "upload", "failed", 3, 5, "Видео удалено")
        text = admin_stats.stats_text()
        self.assertIn("Всего пользователей: <b>3</b>", text)
        self.assertIn("• за неделю: 2", text)          # new users this week
        self.assertIn("• за месяц: 3", text)
        self.assertIn("2 (✅ 1 / ❌ 1)", text)
        self.assertIn("Видео удалено", admin_stats.errors_text())

    def test_error_log_is_a_bounded_ring(self):
        handler = admin_stats.ErrorLogHandler()
        log = logging.getLogger("test_admin_stats")
        log.addHandler(handler)
        try:
            with patch.object(admin_stats, "ERRORS_KEEP", 5):
                for i in range(12):
                    try:
                        raise ValueError(f"boom {i}")
                    except ValueError:
                        log.exception("Job failed")
                log.warning("not stored")
        finally:
            log.removeHandler(handler)
        with db._db() as c:
            rows = c.execute("SELECT message FROM bot_errors ORDER BY id").fetchall()
        self.assertLessEqual(len(rows), 6)
        self.assertIn("ValueError: boom 11", rows[-1]["message"])
        self.assertIn("boom 11", admin_stats.errors_text())
        admin_stats.clear_errors_sync()
        self.assertIn("Ошибок нет", admin_stats.errors_text())

    def test_health_report(self):
        engine = handlers.Engine(None)
        text = admin_stats.health_text(engine)
        self.assertIn("Диск: свободно", text)
        self.assertIn("Очередь: 0", text)

    def test_jobs_are_pruned(self):
        admin_stats.record_job_sync(1, "url", "ok", 1, 1, None)
        with db._db() as c:
            c.execute("UPDATE jobs SET created_at=?", ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),))
        admin_stats.prune_sync()
        with db._db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_touch_is_throttled(self):
        calls = []
        with patch.object(admin_stats, "touch_user_sync", side_effect=calls.append):
            admin_stats._last_touch.clear()
            asyncio.run(admin_stats.touch_user(5))
            asyncio.run(admin_stats.touch_user(5))
        self.assertEqual(calls, [5])

    def test_admin_menu_has_dashboard(self):
        import inspect
        src = inspect.getsource(handlers.admin)
        for cb in ("astats", "ahealth", "aerrors"):
            self.assertIn(f'"{cb}"', src)


if __name__ == "__main__":
    unittest.main()
