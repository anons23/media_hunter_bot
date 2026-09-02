import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from media_hunter_bot import admin_premium, db
from media_hunter_bot import handlers
from media_hunter_bot.config import ADMIN_ID


class AdminPremiumTests(unittest.TestCase):
    def test_only_admin_gets_admin_button(self):
        admin_buttons = [b for row in handlers.menu(ADMIN_ID).inline_keyboard for b in row]
        other_buttons = [b for row in handlers.menu(987654321).inline_keyboard for b in row]
        self.assertIn("admin", {b.callback_data for b in admin_buttons})
        self.assertNotIn("admin", {b.callback_data for b in other_buttons})

    def test_revoke_admin_grant_preserves_paid_premium(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            paid_until = datetime.now(timezone.utc) + timedelta(days=12)
            with patch.object(db, "DB_PATH", db_path), patch.object(db, "ensure_directories", lambda: None):
                with db._db() as c:
                    c.execute(
                        "CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, premium_until TEXT, permanent_premium INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'video', watermark TEXT NOT NULL DEFAULT '{}', referrals INTEGER NOT NULL DEFAULT 0, referred_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                    )
                    c.execute(
                        "CREATE TABLE payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, payload TEXT UNIQUE, days INTEGER NOT NULL, stars INTEGER NOT NULL, telegram_charge_id TEXT, created_at TEXT NOT NULL)"
                    )
                    now = datetime.now(timezone.utc).isoformat()
                    c.execute(
                        "INSERT INTO users(user_id,created_at,updated_at,premium_until) VALUES(?,?,?,?)",
                        (123, now, now, paid_until.isoformat()),
                    )
                    c.execute(
                        "CREATE TABLE admin_premium_grants(user_id INTEGER PRIMARY KEY, base_until TEXT, grant_until TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                    )
                    grant_until = (paid_until + timedelta(days=30)).isoformat()
                    c.execute(
                        "INSERT INTO admin_premium_grants VALUES(?,?,?,?,?)",
                        (123, paid_until.isoformat(), grant_until, now, now),
                    )
                    c.execute(
                        "INSERT INTO payments(user_id,payload,days,stars,telegram_charge_id,created_at) VALUES(?,?,?,?,?,?)",
                        (123, "premium:30:123:test", 30, 150, "charge-1", now),
                    )

                self.assertTrue(admin_premium._revoke_sync(123))
                with db._db() as c:
                    row = c.execute("SELECT premium_until FROM users WHERE user_id=123").fetchone()
                    grant = c.execute("SELECT 1 FROM admin_premium_grants WHERE user_id=123").fetchone()
                self.assertIsNone(grant)
                self.assertIsNotNone(row[0])
                restored = datetime.fromisoformat(row[0])
                self.assertGreaterEqual(restored, paid_until)

    def test_revoke_reads_payments_inside_immediate_transaction(self):
        source = Path(admin_premium.__file__).read_text(encoding="utf-8")
        revoke_src = source[source.index("def _revoke_sync"):source.index("def _list_sync")]
        self.assertIn('c.execute("BEGIN IMMEDIATE")', revoke_src)
        payments_pos = revoke_src.index('SELECT created_at, days FROM payments')
        update_pos = revoke_src.index('UPDATE users SET premium_until', payments_pos)
        delete_pos = revoke_src.index('DELETE FROM admin_premium_grants', update_pos)
        self.assertLess(payments_pos, update_pos)
        self.assertLess(update_pos, delete_pos)

    def test_grant_rejects_unknown_user(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            with patch.object(db, "DB_PATH", db_path), patch.object(db, "ensure_directories", lambda: None):
                db.init_db()
                self.assertRaises(ValueError, admin_premium._grant_sync, 999, 30)


if __name__ == "__main__":
    unittest.main()
