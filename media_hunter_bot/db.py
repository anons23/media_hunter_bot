"""Database layer — synchronous SQLite core with async thread wrappers."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import ADMIN_ID, DB_PATH, ensure_directories


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

_DEFAULT_SETTINGS = {"stars_link": "", "ad_text": "", "ad_button": "", "ad_url": ""}


def init_db() -> None:
    ensure_directories()
    with _db() as c:
        c.executescript(_INIT_SQL)
        c.execute("DELETE FROM payments WHERE id NOT IN (SELECT MIN(id) FROM payments WHERE telegram_charge_id IS NOT NULL GROUP BY telegram_charge_id) AND telegram_charge_id IS NOT NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_telegram_charge_id ON payments(telegram_charge_id) WHERE telegram_charge_id IS NOT NULL")
        for k, v in _DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        for slot in (1, 2, 3):
            c.execute("INSERT OR IGNORE INTO opp(slot) VALUES(?)", (slot,))
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


def apply_referral(user_id: int, referrer_id: int) -> bool:
    if user_id == referrer_id:
        return False
    with _db() as c:
        referrer = c.execute(
            "SELECT user_id FROM users WHERE user_id=?", (referrer_id,)
        ).fetchone()
        if not referrer:
            return False
        c.execute(
            "UPDATE users SET referred_by=?, updated_at=? "
            "WHERE user_id=? AND referred_by IS NULL",
            (referrer_id, _now(), user_id),
        )
        if c.rowcount != 1:
            return False
        c.execute(
            "UPDATE users SET referrals=referrals+1, updated_at=? WHERE user_id=?",
            (_now(), referrer_id),
        )
        return True


def get_referrals(user_id: int) -> int:
    with _db() as c:
        r = c.execute("SELECT referrals FROM users WHERE user_id=?", (user_id,)).fetchone()
        return int(r[0]) if r else 0


def active_logo_paths() -> set[str]:
    active: set[str] = set()
    with _db() as c:
        rows = c.execute("SELECT watermark FROM users WHERE watermark IS NOT NULL UNION ALL SELECT watermark FROM channels WHERE watermark IS NOT NULL").fetchall()
    for row in rows:
        try:
            wm = json.loads(row[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if wm.get("type") == "image" and wm.get("logo"):
            active.add(str(wm["logo"]))
    return active


def get_user(user_id: int) -> sqlite3.Row | None:
    with _db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def set_format(user_id: int, fmt: str) -> None:
    with _db() as c: c.execute("UPDATE users SET format=?,updated_at=? WHERE user_id=?", (fmt, _now(), user_id))


def get_user_watermark(user_id: int) -> dict[str, Any]:
    with _db() as c:
        r = c.execute("SELECT watermark FROM users WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(r[0] or "{}") if r else {}


def set_user_watermark(user_id: int, value: dict[str, Any]) -> None:
    with _db() as c: c.execute("UPDATE users SET watermark=?,updated_at=? WHERE user_id=?", (json.dumps(value, ensure_ascii=False), _now(), user_id))


def is_premium(user_id: int) -> bool:
    u = get_user(user_id)
    if not u or u["permanent_premium"]: return bool(u and u["permanent_premium"])
    until = _parse_premium_until(u["premium_until"])
    return until is not None and datetime.now(timezone.utc) < until


def extend_premium(user_id: int, days: int) -> None:
    with _db() as c:
        u = c.execute("SELECT premium_until,permanent_premium FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u or u["permanent_premium"]: return
        base = datetime.now(timezone.utc)
        old = _parse_premium_until(u["premium_until"])
        if old is not None: base = max(base, old)
        c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?", ((base + timedelta(days=days)).isoformat(), _now(), user_id))


def list_channels(user_id: int) -> list[sqlite3.Row]:
    with _db() as c: return c.execute("SELECT * FROM channels WHERE user_id=? ORDER BY id", (user_id,)).fetchall()


def add_channel(user_id: int, channel_id: int, title: str) -> None:
    with _db() as c:
        existing = c.execute("SELECT id FROM channels WHERE user_id=? AND channel_id=?", (user_id, channel_id)).fetchone()
        if existing:
            c.execute("UPDATE channels SET title=? WHERE user_id=? AND channel_id=?", (title, user_id, channel_id))
            return
        premium_row = c.execute("SELECT premium_until, permanent_premium FROM users WHERE user_id=?", (user_id,)).fetchone()
        premium = False
        if premium_row:
            if premium_row["permanent_premium"]:
                premium = True
            else:
                until = _parse_premium_until(premium_row["premium_until"])
                premium = until is not None and datetime.now(timezone.utc) < until
        max_channels = 3 if premium else 1
        count = c.execute("SELECT COUNT(*) FROM channels WHERE user_id=?", (user_id,)).fetchone()[0]
        if count >= max_channels:
            if premium:
                raise ValueError("Максимум 3 канала для Premium")
            raise ValueError("Для бесплатного тарифа доступен только 1 канал. Подключите Premium для 3 каналов.")
        c.execute("INSERT INTO channels(user_id,channel_id,title,created_at) VALUES(?,?,?,?)", (user_id, channel_id, title, _now()))


def remove_channel(user_id: int, channel_id: int) -> None:
    with _db() as c: c.execute("DELETE FROM channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))


def set_channel_enabled(user_id: int, channel_id: int, enabled: bool) -> None:
    with _db() as c: c.execute("UPDATE channels SET enabled=? WHERE user_id=? AND channel_id=?", (int(enabled), user_id, channel_id))


def get_channel_watermark(channel_id: int, user_id: int) -> dict[str, Any]:
    with _db() as c:
        r = c.execute("SELECT watermark FROM channels WHERE channel_id=? AND user_id=?", (channel_id, user_id)).fetchone()
        return json.loads(r[0] or "{}") if r else {}


def set_channel_watermark(channel_id: int, user_id: int, value: dict[str, Any]) -> None:
    with _db() as c: c.execute("UPDATE channels SET watermark=? WHERE channel_id=? AND user_id=?", (json.dumps(value, ensure_ascii=False), channel_id, user_id))


def get_setting(key: str, default: str = "") -> str:
    with _db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default


def set_setting(key: str, value: str) -> None:
    with _db() as c: c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_opp() -> list[sqlite3.Row]:
    with _db() as c: return c.execute("SELECT * FROM opp ORDER BY slot").fetchall()


def set_opp(slot: int, enabled: bool, title: str, url: str) -> None:
    with _db() as c: c.execute("UPDATE opp SET enabled=?,title=?,url=? WHERE slot=?", (int(enabled), title, url, slot))


def active_opp() -> list[sqlite3.Row]: return [r for r in get_opp() if r["enabled"] and r["url"]]


def save_payment(user_id: int, payload: str, days: int, stars: int, charge_id: str) -> bool:
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO payments(user_id,payload,days,stars,telegram_charge_id,created_at) VALUES(?,?,?,?,?,?)", (user_id, payload, days, stars, charge_id, _now()))
        return c.total_changes > 0


async def aensure_user(user_id: int, username: str | None = None, first_name: str | None = None): return await asyncio.to_thread(ensure_user, user_id, username, first_name)
async def aapply_referral(user_id: int, referrer_id: int) -> bool: return await asyncio.to_thread(apply_referral, user_id, referrer_id)
async def aget_referrals(user_id: int) -> int: return await asyncio.to_thread(get_referrals, user_id)
async def aactive_logo_paths() -> set[str]: return await asyncio.to_thread(active_logo_paths)
async def aget_user(user_id: int): return await asyncio.to_thread(get_user, user_id)
async def aset_format(user_id: int, fmt: str): return await asyncio.to_thread(set_format, user_id, fmt)
async def aget_user_watermark(user_id: int) -> dict[str, Any]: return await asyncio.to_thread(get_user_watermark, user_id)
async def aset_user_watermark(user_id: int, value: dict[str, Any]): return await asyncio.to_thread(set_user_watermark, user_id, value)
async def ais_premium(user_id: int) -> bool: return await asyncio.to_thread(is_premium, user_id)
async def aextend_premium(user_id: int, days: int): return await asyncio.to_thread(extend_premium, user_id, days)
async def alist_channels(user_id: int): return await asyncio.to_thread(list_channels, user_id)
async def aadd_channel(user_id: int, channel_id: int, title: str): return await asyncio.to_thread(add_channel, user_id, channel_id, title)
async def aremove_channel(user_id: int, channel_id: int): return await asyncio.to_thread(remove_channel, user_id, channel_id)
async def aset_channel_enabled(user_id: int, channel_id: int, enabled: bool): return await asyncio.to_thread(set_channel_enabled, user_id, channel_id, enabled)
async def aget_channel_watermark(channel_id: int, user_id: int) -> dict[str, Any]: return await asyncio.to_thread(get_channel_watermark, channel_id, user_id)
async def aset_channel_watermark(channel_id: int, user_id: int, value: dict[str, Any]): return await asyncio.to_thread(set_channel_watermark, channel_id, user_id, value)
async def aget_setting(key: str, default: str = "") -> str: return await asyncio.to_thread(get_setting, key, default)
async def aset_setting(key: str, value: str): return await asyncio.to_thread(set_setting, key, value)
async def aget_opp(): return await asyncio.to_thread(get_opp)
async def aset_opp(slot: int, enabled: bool, title: str, url: str): return await asyncio.to_thread(set_opp, slot, enabled, title, url)
async def aactive_opp(): return await asyncio.to_thread(active_opp)
async def asave_payment(user_id: int, payload: str, days: int, stars: int, charge_id: str) -> bool: return await asyncio.to_thread(save_payment, user_id, payload, days, stars, charge_id)
