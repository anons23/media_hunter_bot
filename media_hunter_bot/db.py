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
        # migrate opp.chat_ref for private-channel support
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
        n = c.execute("SELECT COUNT(*) FROM channels WHERE user_id=?", (user_id,)).fetchone()[0]
        if n >= 3:
            raise ValueError("Максимум 3 канала")
        c.execute(
            "INSERT INTO channels(user_id,channel_id,title,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,channel_id) DO UPDATE SET title=excluded.title",
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


def _end_active_campaigns_locked(c: sqlite3.Connection, slot: int) -> None:
    c.execute(
        "UPDATE opp_campaigns SET ended_at=? WHERE slot=? AND ended_at IS NULL",
        (_now(), slot),
    )


def set_opp(slot: int, enabled: bool, title: str, url: str, chat_ref: str = "") -> None:
    """Enable/disable OPP slot and rotate campaigns for stats.

    chat_ref: @username or numeric -100... used for get_chat_member.
    url: button link shown to the user (public t.me/name or private invite).
    """
    retain = 7
    with _db() as c:
        raw = c.execute("SELECT value FROM settings WHERE key=?", ("opp_retain_days",)).fetchone()
        if raw and str(raw[0]).isdigit():
            retain = max(1, min(365, int(raw[0])))
        _end_active_campaigns_locked(c, slot)
        c.execute(
            "UPDATE opp SET enabled=?, title=?, url=?, chat_ref=? WHERE slot=?",
            (int(enabled), title, url, chat_ref or "", slot),
        )
        if enabled and (url or chat_ref):
            c.execute(
                "INSERT INTO opp_campaigns(slot, title, chat_ref, button_url, started_at, ended_at, retain_days) VALUES(?,?,?,?,?,NULL,?)",
                (slot, title, chat_ref or "", url, _now(), retain),
            )


def active_opp() -> list[sqlite3.Row]:
    rows = []
    for r in get_opp():
        if not r["enabled"]:
            continue
        chat_ref = ""
        try:
            chat_ref = r["chat_ref"] or ""
        except (KeyError, IndexError):
            chat_ref = ""
        if not r["url"] and not chat_ref:
            continue
        rows.append(r)
    return rows


def record_opp_conversion(slot: int, user_id: int, username: str | None = None) -> bool:
    """Record first successful OPP pass for the active campaign on this slot."""
    with _db() as c:
        camp = c.execute(
            "SELECT id FROM opp_campaigns WHERE slot=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (slot,),
        ).fetchone()
        if not camp:
            return False
        before = c.total_changes
        c.execute(
            "INSERT OR IGNORE INTO opp_conversions(campaign_id, slot, user_id, username, first_seen_at) VALUES(?,?,?,?,?)",
            (camp["id"], slot, user_id, username, _now()),
        )
        return c.total_changes > before


def list_opp_campaigns(slot: int | None = None) -> list[sqlite3.Row]:
    with _db() as c:
        if slot is None:
            return c.execute("SELECT * FROM opp_campaigns ORDER BY id DESC").fetchall()
        return c.execute(
            "SELECT * FROM opp_campaigns WHERE slot=? ORDER BY id DESC",
            (slot,),
        ).fetchall()


def get_opp_campaign(campaign_id: int) -> sqlite3.Row | None:
    with _db() as c:
        return c.execute("SELECT * FROM opp_campaigns WHERE id=?", (campaign_id,)).fetchone()


def opp_campaign_stats(campaign_id: int) -> dict[str, Any]:
    with _db() as c:
        camp = c.execute("SELECT * FROM opp_campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not camp:
            return {}
        total = c.execute(
            "SELECT COUNT(*) AS n FROM opp_conversions WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()["n"]
        by_day = c.execute(
            """
            SELECT substr(first_seen_at, 1, 10) AS day, COUNT(*) AS n
            FROM opp_conversions
            WHERE campaign_id=?
            GROUP BY day
            ORDER BY day
            """,
            (campaign_id,),
        ).fetchall()
        users = c.execute(
            """
            SELECT user_id, username, first_seen_at
            FROM opp_conversions
            WHERE campaign_id=?
            ORDER BY first_seen_at
            """,
            (campaign_id,),
        ).fetchall()
        return {
            "campaign": dict(camp),
            "total": total,
            "by_day": [dict(r) for r in by_day],
            "users": [dict(r) for r in users],
        }


def cleanup_expired_opp_campaigns() -> int:
    """Delete closed campaigns whose retain window has passed. Returns removed campaign count."""
    removed = 0
    with _db() as c:
        rows = c.execute(
            "SELECT id, ended_at, retain_days FROM opp_campaigns WHERE ended_at IS NOT NULL"
        ).fetchall()
        now = datetime.now(timezone.utc)
        for r in rows:
            try:
                ended = datetime.fromisoformat(r["ended_at"])
                if ended.tzinfo is None:
                    ended = ended.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            retain = int(r["retain_days"] or 7)
            if now >= ended + timedelta(days=retain):
                c.execute("DELETE FROM opp_conversions WHERE campaign_id=?", (r["id"],))
                c.execute("DELETE FROM opp_campaigns WHERE id=?", (r["id"],))
                removed += 1
    return removed


def get_opp_retain_days() -> int:
    raw = get_setting("opp_retain_days", "7")
    try:
        return max(1, min(365, int(raw)))
    except ValueError:
        return 7


def set_opp_retain_days(days: int) -> None:
    days = max(1, min(365, int(days)))
    set_setting("opp_retain_days", str(days))


def save_payment(user_id: int, payload: str, days: int, stars: int, charge_id: str) -> bool:
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO payments(user_id,payload,days,stars,telegram_charge_id,created_at) VALUES(?,?,?,?,?,?)", (user_id, payload, days, stars, charge_id, _now()))
        return c.total_changes > 0


async def aensure_user(user_id: int, username: str | None = None, first_name: str | None = None): return await asyncio.to_thread(ensure_user, user_id, username, first_name)
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
async def aapply_referral(user_id: int, referrer_id: int) -> bool: return await asyncio.to_thread(apply_referral, user_id, referrer_id)
async def aget_referrals(user_id: int) -> int: return await asyncio.to_thread(get_referrals, user_id)
async def aactive_logo_paths() -> set[str]: return await asyncio.to_thread(active_logo_paths)
async def aget_setting(key: str, default: str = "") -> str: return await asyncio.to_thread(get_setting, key, default)
async def aset_setting(key: str, value: str): return await asyncio.to_thread(set_setting, key, value)
async def aget_opp(): return await asyncio.to_thread(get_opp)
async def aset_opp(slot: int, enabled: bool, title: str, url: str, chat_ref: str = ""): return await asyncio.to_thread(set_opp, slot, enabled, title, url, chat_ref)
async def aactive_opp(): return await asyncio.to_thread(active_opp)
async def arecord_opp_conversion(slot: int, user_id: int, username: str | None = None) -> bool: return await asyncio.to_thread(record_opp_conversion, slot, user_id, username)
async def alist_opp_campaigns(slot: int | None = None): return await asyncio.to_thread(list_opp_campaigns, slot)
async def aget_opp_campaign(campaign_id: int): return await asyncio.to_thread(get_opp_campaign, campaign_id)
async def aopp_campaign_stats(campaign_id: int) -> dict: return await asyncio.to_thread(opp_campaign_stats, campaign_id)
async def acleanup_expired_opp_campaigns() -> int: return await asyncio.to_thread(cleanup_expired_opp_campaigns)
async def aget_opp_retain_days() -> int: return await asyncio.to_thread(get_opp_retain_days)
async def aset_opp_retain_days(days: int): return await asyncio.to_thread(set_opp_retain_days, days)
async def asave_payment(user_id: int, payload: str, days: int, stars: int, charge_id: str) -> bool: return await asyncio.to_thread(save_payment, user_id, payload, days, stars, charge_id)
