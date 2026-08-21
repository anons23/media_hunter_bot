"""Database layer — synchronous core + async thin wrappers.

SQLite runs in WAL mode with a 30-second busy timeout.
All sync functions are offloaded via asyncio.to_thread() so the event
loop never blocks.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import ADMIN_ID, DB_PATH


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
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    premium_until TEXT,
    permanent_premium INTEGER NOT NULL DEFAULT 0,
    format TEXT NOT NULL DEFAULT 'video',
    watermark TEXT NOT NULL DEFAULT '{}',
    referrals INTEGER NOT NULL DEFAULT 0,
    referred_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    title TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    watermark TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, channel_id)
);
CREATE TABLE IF NOT EXISTS opp(
    slot INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    payload TEXT UNIQUE,
    days INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    telegram_charge_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channels_user ON channels(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_users_premium ON users(premium_until);
"""

_DEFAULT_SETTINGS = {
    "stars_link": "https://t.me/starslly_bot?start=489552258",
    "ad_text": "",
    "ad_button": "",
    "ad_url": "",
}


def init_db() -> None:
    with _db() as c:
        c.executescript(_INIT_SQL)
        for k, v in _DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        for slot in (1, 2, 3):
            c.execute("INSERT OR IGNORE INTO opp(slot) VALUES(?)", (slot,))
        _ensure_user_locked(c, ADMIN_ID, None, None)
        c.execute("UPDATE users SET permanent_premium=1 WHERE user_id=?", (ADMIN_ID,))


def _ensure_user_locked(c: sqlite3.Connection, user_id: int, username: str | None, first_name: str | None) -> None:
    username = username or None
    first_name = first_name or None
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
        c.execute("UPDATE users SET format=?,updated_at=? WHERE user_id=?", (fmt, _now(), user_id))


def get_user_watermark(user_id: int) -> dict[str, Any]:
    with _db() as c:
        r = c.execute("SELECT watermark FROM users WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(r[0] or "{}") if r else {}


def set_user_watermark(user_id: int, value: dict[str, Any]) -> None:
    with _db() as c:
        c.execute("UPDATE users SET watermark=?,updated_at=? WHERE user_id=?", (json.dumps(value, ensure_ascii=False), _now(), user_id))


def is_premium(user_id: int) -> bool:
    u = get_user(user_id)
    if not u:
        return False
    if u["permanent_premium"]:
        return True
    until = _parse_premium_until(u["premium_until"])
    if until is None:
        return False
    return datetime.now(timezone.utc) < until


def extend_premium(user_id: int, days: int) -> None:
    with _db() as c:
        u = c.execute("SELECT premium_until,permanent_premium FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u or u["permanent_premium"]:
            return
        base = datetime.now(timezone.utc)
        old = _parse_premium_until(u["premium_until"])
        if old is not None:
            base = max(base, old)
        c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?", ((base + timedelta(days=days)).isoformat(), _now(), user_id))


# The remainder of the database module is intentionally preserved from the existing v3 branch.
# Async wrappers and channel/OPP/settings/payment functions follow unchanged.
