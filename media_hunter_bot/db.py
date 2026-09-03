"""Database layer — synchronous SQLite core with async thread wrappers."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import ADMIN_ID, DB_PATH, FREE_MAX_CHANNELS, PREMIUM_MAX_CHANNELS, ensure_directories


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_premium_until(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@contextmanager
def _db():
    ensure_directories()
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


_INIT_SQL = """
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, premium_until TEXT, permanent_premium INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'video', watermark TEXT NOT NULL DEFAULT '{}', referrals INTEGER NOT NULL DEFAULT 0, referred_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, title TEXT, enabled INTEGER NOT NULL DEFAULT 1, watermark TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, UNIQUE(user_id, channel_id));
CREATE TABLE IF NOT EXISTS opp(slot INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, payload TEXT UNIQUE, days INTEGER NOT NULL, stars INTEGER NOT NULL, telegram_charge_id TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_channels_user ON channels(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_users_premium ON users(premium_until);
CREATE TABLE IF NOT EXISTS opp_campaigns(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  chat_ref TEXT NOT NULL DEFAULT '',
  button_url TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  ended_at TEXT,
  retain_days INTEGER NOT NULL DEFAULT 7
);
CREATE TABLE IF NOT EXISTS opp_conversions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  slot INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  username TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(campaign_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_opp_conv_campaign ON opp_conversions(campaign_id);
CREATE INDEX IF NOT EXISTS idx_opp_campaigns_slot ON opp_campaigns(slot, ended_at);
"""
_DEFAULT_SETTINGS = {"stars_link": "", "ad_text": "", "ad_button": "", "ad_url": "", "opp_retain_days": "7"}


def init_db() -> None:
    ensure_directories()
    with _db() as c:
        c.executescript(_INIT_SQL)
        c.execute("DELETE FROM payments WHERE id NOT IN (SELECT MIN(id) FROM payments WHERE telegram_charge_id IS NOT NULL GROUP BY telegram_charge_id) AND telegram_charge_id IS NOT NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_telegram_charge_id ON payments(telegram_charge_id) WHERE telegram_charge_id IS NOT NULL")
        for k, v in _DEFAULT_SETTINGS.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        cols = {r[1] for r in c.execute("PRAGMA table_info(opp)").fetchall()}
        if "chat_ref" not in cols:
            c.execute("ALTER TABLE opp ADD COLUMN chat_ref TEXT NOT NULL DEFAULT ''")
        for slot in (1, 2, 3): c.execute("INSERT OR IGNORE INTO opp(slot) VALUES(?)", (slot,))
        if ADMIN_ID:
            _ensure_user_locked(c, ADMIN_ID, None, None)
            c.execute("UPDATE users SET permanent_premium=1 WHERE user_id=?", (ADMIN_ID,))


def _ensure_user_locked(c: sqlite3.Connection, user_id: int, username: str | None, first_name: str | None) -> None:
    username, first_name = username or None, first_name or None
    t = _now()
    c.execute("INSERT OR IGNORE INTO users(user_id,username,first_name,created_at,updated_at) VALUES(?,?,?,?,?)", (user_id, username, first_name, t, t))
    c.execute("UPDATE users SET username=COALESCE(?,username), first_name=COALESCE(?,first_name), updated_at=? WHERE user_id=?", (username, first_name, t, user_id))


def ensure_user(user_id: int, username: str | None = None, first_name: str | None = None) -> None:
    with _db() as c:
        _ensure_user_locked(c, user_id, username, first_name)


def get_user(user_id: int) -> sqlite3.Row | None:
    with _db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def set_format(user_id: int, fmt: str) -> None:
    with _db() as c:
        _ensure_user_locked(c, user_id, None, None)
        c.execute("UPDATE users SET format=?, updated_at=? WHERE user_id=?", (fmt, _now(), user_id))


def get_user_watermark(user_id: int) -> dict[str, Any]:
    with _db() as c:
        r = c.execute("SELECT watermark FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return {}
        try:
            return json.loads(r[0] or "{}")
        except json.JSONDecodeError:
            return {}


def set_user_watermark(user_id: int, value: dict[str, Any]) -> None:
    with _db() as c:
        _ensure_user_locked(c, user_id, None, None)
        c.execute("UPDATE users SET watermark=?, updated_at=? WHERE user_id=?", (json.dumps(value, ensure_ascii=False), _now(), user_id))


def is_premium(user_id: int) -> bool:
    with _db() as c:
        r = c.execute("SELECT permanent_premium, premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return False
        if r["permanent_premium"]:
            return True
        dt = _parse_premium_until(r["premium_until"])
        return bool(dt and dt > datetime.now(timezone.utc))


def extend_premium(user_id: int, days: int) -> None:
    with _db() as c:
        _ensure_user_locked(c, user_id, None, None)
        r = c.execute("SELECT permanent_premium, premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        if r and r["permanent_premium"]:
            return
        now = datetime.now(timezone.utc)
        cur = _parse_premium_until(r["premium_until"] if r else None)
        base = cur if cur and cur > now else now
        until = (base + timedelta(days=days)).isoformat()
        c.execute("UPDATE users SET premium_until=?, updated_at=? WHERE user_id=?", (until, _now(), user_id))


def list_channels(user_id: int) -> list[sqlite3.Row]:
    with _db() as c:
        return c.execute("SELECT * FROM channels WHERE user_id=? ORDER BY id", (user_id,)).fetchall()


def add_channel(user_id: int, channel_id: int, title: str) -> None:
    with _db() as c:
        existing = c.execute("SELECT 1 FROM channels WHERE user_id=? AND channel_id=?", (user_id, channel_id)).fetchone()
        if existing:
            c.execute(
                "UPDATE channels SET title=? WHERE user_id=? AND channel_id=?",
                (title, user_id, channel_id),
            )
            return

        premium = c.execute(
            "SELECT permanent_premium, premium_until FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        is_premium_user = False
        if premium:
            if premium["permanent_premium"]:
                is_premium_user = True
            else:
                dt = _parse_premium_until(premium["premium_until"])
                is_premium_user = bool(dt and dt > datetime.now(timezone.utc))

        max_channels = PREMIUM_MAX_CHANNELS if is_premium_user else FREE_MAX_CHANNELS
        n = c.execute("SELECT COUNT(*) FROM channels WHERE user_id=?", (user_id,)).fetchone()[0]
        if n >= max_channels:
            raise ValueError(
                f"Ваш тариф позволяет подключить не более {max_channels} канала"
                if max_channels == 1
                else f"Premium позволяет подключить не более {max_channels} каналов"
            )
        c.execute(
            "INSERT INTO channels(user_id,channel_id,title,created_at) VALUES(?,?,?,?)",
            (user_id, channel_id, title, _now()),
        )


def remove_channel(user_id: int, channel_id: int) -> None:
    with _db() as c:
        c.execute("DELETE FROM channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))


def set_channel_enabled(user_id: int, channel_id: int, enabled: bool) -> None:
    with _db() as c:
        c.execute("UPDATE channels SET enabled=? WHERE user_id=? AND channel_id=?", (int(enabled), user_id, channel_id))


def get_channel_watermark(channel_id: int, user_id: int) -> dict[str, Any]:
    with _db() as c:
        r = c.execute("SELECT watermark FROM channels WHERE channel_id=? AND user_id=?", (channel_id, user_id)).fetchone()
        if not r:
            return {}
        try:
            return json.loads(r[0] or "{}")
        except json.JSONDecodeError:
            return {}


def set_channel_watermark(channel_id: int, user_id: int, value: dict[str, Any]) -> None:
    with _db() as c:
        c.execute(
            "UPDATE channels SET watermark=? WHERE channel_id=? AND user_id=?",
            (json.dumps(value, ensure_ascii=False), channel_id, user_id),
        )


def apply_referral(user_id: int, referrer_id: int) -> bool:
    if user_id == referrer_id:
        return False
    with _db() as c:
        _ensure_user_locked(c, user_id, None, None)
        _ensure_user_locked(c, referrer_id, None, None)
        cur = c.execute(
            "UPDATE users SET referred_by=?, updated_at=? WHERE user_id=? AND referred_by IS NULL",
            (referrer_id, _now(), user_id),
        )
        if cur.rowcount != 1:
            return False
        c.execute("UPDATE users SET referrals=referrals+1, updated_at=? WHERE user_id=?", (_now(), referrer_id))
        return True


def get_referrals(user_id: int) -> int:
    with _db() as c:
        r = c.execute("SELECT referrals FROM users WHERE user_id=?", (user_id,)).fetchone()
        return int(r[0]) if r else 0


def active_logo_paths() -> set[str]:
    paths: set[str] = set()
    with _db() as c:
        for row in c.execute("SELECT watermark FROM users").fetchall():
            try:
                w = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                continue
            logo = w.get("logo")
            if logo:
                paths.add(str(logo))
        for row in c.execute("SELECT watermark FROM channels").fetchall():
            try:
                w = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                continue
            logo = w.get("logo")
            if logo:
                paths.add(str(logo))
    return paths


def get_setting(key: str, default: str = "") -> str:
    with _db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default


def set_setting(key: str, value: str) -> None:
    with _db() as c: c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_opp() -> list[sqlite3.Row]:
    with _db() as c: return c.execute("SELECT * FROM opp ORDER BY slot").fetchall()
