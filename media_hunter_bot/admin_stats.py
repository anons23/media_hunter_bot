"""Admin dashboard: user statistics, server health and recent errors.

Storage is tiny and bounded:
* ``users.last_seen`` — one timestamp per user, written at most every 10 min;
* ``jobs`` — one ~100-byte row per processed video, pruned after 90 days
  (≈3 MB per 30 000 videos);
* ``bot_errors`` — ring buffer of the last 300 ERROR log records.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import shutil
import sqlite3
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db
from .config import ADMIN_ID, LOCAL_BOT_API_DIR, MEDIA_DIR

logger = logging.getLogger(__name__)

BOT_STARTED = time.time()
ERRORS_KEEP = 300
JOBS_KEEP_DAYS = 90
TOUCH_EVERY_S = 600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  size_mb REAL,
  seconds REAL,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE TABLE IF NOT EXISTS bot_errors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  message TEXT NOT NULL
);
"""


def ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript(_SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    if "last_seen" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _since(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- recording

_last_touch: dict[int, float] = {}


def touch_user_sync(uid: int) -> None:
    with db._db() as c:
        c.execute("UPDATE users SET last_seen=? WHERE user_id=?", (_now(), uid))


async def touch_user(uid: int) -> None:
    now = time.monotonic()
    if now - _last_touch.get(uid, 0) < TOUCH_EVERY_S:
        return
    _last_touch[uid] = now
    if len(_last_touch) > 50_000:
        _last_touch.clear()
    try:
        await asyncio.to_thread(touch_user_sync, uid)
    except Exception:
        pass


def record_job_sync(uid: int, kind: str, status: str, size_mb: float | None, seconds: float, error: str | None) -> None:
    with db._db() as c:
        c.execute(
            "INSERT INTO jobs(user_id,kind,status,size_mb,seconds,error,created_at) VALUES(?,?,?,?,?,?,?)",
            (uid, kind, status, size_mb, round(seconds, 1), (error or None) and error[:300], _now()),
        )


async def record_job(uid: int, kind: str, status: str, size_mb: float | None, seconds: float, error: str | None = None) -> None:
    try:
        await asyncio.to_thread(record_job_sync, uid, kind, status, size_mb, seconds, error)
    except Exception:
        logger.warning("record_job failed", exc_info=False)


def prune_sync() -> None:
    with db._db() as c:
        c.execute("DELETE FROM jobs WHERE created_at < ?", (_since(JOBS_KEEP_DAYS),))


class ErrorLogHandler(logging.Handler):
    """Keep the last ERROR records in SQLite so the admin sees them in Telegram."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._busy = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                where = traceback.extract_tb(record.exc_info[2])[-1:] if record.exc_info[2] else []
                loc = f" @ {Path(where[0].filename).name}:{where[0].lineno}" if where else ""
                msg = f"{msg} — {type(exc).__name__}: {exc}{loc}"
            con = sqlite3.connect(db.DB_PATH, timeout=5)
            try:
                con.execute(
                    "INSERT INTO bot_errors(created_at, source, message) VALUES(?,?,?)",
                    (_now(), record.name[:60], msg[:600]),
                )
                con.execute(
                    "DELETE FROM bot_errors WHERE id <= (SELECT MAX(id) FROM bot_errors) - ?",
                    (ERRORS_KEEP,),
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            pass
        finally:
            self._busy = False


def install_error_handler() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, ErrorLogHandler) for h in root.handlers):
        root.addHandler(ErrorLogHandler())


class ActivityMiddleware(BaseMiddleware):
    """Updates users.last_seen (throttled) for active-user statistics."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None and not getattr(user, "is_bot", False):
            await touch_user(user.id)
        return await handler(event, data)


# ---------------------------------------------------------------- reports

def _count(c: sqlite3.Connection, sql: str, *args: Any) -> int:
    row = c.execute(sql, args).fetchone()
    return int(row[0] or 0) if row else 0


def stats_text() -> str:
    now = datetime.now(timezone.utc).isoformat()
    with db._db() as c:
        total = _count(c, "SELECT COUNT(*) FROM users")
        new = {d: _count(c, "SELECT COUNT(*) FROM users WHERE created_at >= ?", _since(d)) for d in (1, 7, 30)}
        active = {d: _count(c, "SELECT COUNT(*) FROM users WHERE last_seen >= ?", _since(d)) for d in (1, 7, 30)}
        premium = _count(c, "SELECT COUNT(*) FROM users WHERE permanent_premium=1 OR premium_until > ?", now)
        channels = _count(c, "SELECT COUNT(*) FROM channels")
        jobs = {}
        for d in (1, 7, 30):
            rows = c.execute("SELECT status, COUNT(*) FROM jobs WHERE created_at >= ? GROUP BY status", (_since(d),)).fetchall()
            jobs[d] = {r[0]: r[1] for r in rows}
        refs = _count(c, "SELECT COALESCE(SUM(referrals),0) FROM users")

    def jline(d: int) -> str:
        j = jobs[d]
        ok, fail = j.get("ok", 0), j.get("failed", 0)
        return f"{ok + fail} (✅ {ok} / ❌ {fail})"

    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"⭐ Premium: {premium}   📺 Каналов: {channels}   🔗 По рефералкам: {refs}\n\n"
        "🆕 <b>Новые</b>\n"
        f"• за сутки: {new[1]}\n• за неделю: {new[7]}\n• за месяц: {new[30]}\n\n"
        "🔥 <b>Активные</b> (заходили в бота)\n"
        f"• за сутки: {active[1]}\n• за неделю: {active[7]}\n• за месяц: {active[30]}\n\n"
        "🎬 <b>Обработано видео</b>\n"
        f"• за сутки: {jline(1)}\n• за неделю: {jline(7)}\n• за месяц: {jline(30)}"
    )


def _dir_size_mb(path: Path, limit_files: int = 20000) -> float:
    total, n = 0, 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                n += 1
                if n > limit_files:
                    return total / (1024 * 1024)
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total / (1024 * 1024)


def _meminfo() -> tuple[float, float, float, float]:
    """(available, total, swap free, swap total) in MB."""
    vals: dict[str, float] = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                vals[k] = float(v.split()[0]) / 1024
    except OSError:
        pass
    return vals.get("MemAvailable", 0), vals.get("MemTotal", 0), vals.get("SwapFree", 0), vals.get("SwapTotal", 0)


def _fmt_uptime(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    return f"{d} д {h} ч" if d else f"{h} ч {rem // 60} мин"


def health_text(engine: Any) -> str:
    disk = shutil.disk_usage(MEDIA_DIR if MEDIA_DIR.exists() else "/")
    free_gb, total_gb = disk.free / 1024 ** 3, disk.total / 1024 ** 3
    mem_av, mem_tot, swap_free, swap_tot = _meminfo()
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    cpus = os.cpu_count() or 1
    queued = getattr(getattr(engine, "q", None), "qsize", lambda: 0)()
    running = sum(len(t) for t in getattr(engine, "tasks", {}).values())
    avg = getattr(engine, "_avg_job_s", 0)
    media_mb = _dir_size_mb(MEDIA_DIR)
    api_mb = _dir_size_mb(Path(LOCAL_BOT_API_DIR)) if LOCAL_BOT_API_DIR else None
    db_mb = db.DB_PATH.stat().st_size / (1024 * 1024) if db.DB_PATH.exists() else 0
    with db._db() as c:
        errors_24h = _count(c, "SELECT COUNT(*) FROM bot_errors WHERE created_at >= ?", _since(1))
        failed_24h = _count(c, "SELECT COUNT(*) FROM jobs WHERE status='failed' AND created_at >= ?", _since(1))

    def mark(bad: bool, warn: bool = False) -> str:
        return "🔴" if bad else ("🟡" if warn else "🟢")

    lines = [
        "🩺 <b>Состояние сервера</b>\n",
        f"{mark(free_gb < 1.5, free_gb < 3)} Диск: свободно <b>{free_gb:.1f}</b> из {total_gb:.1f} ГБ",
        f"   • временные файлы бота: {media_mb:.0f} МБ, база: {db_mb:.1f} МБ"
        + (f", Bot API: {api_mb:.0f} МБ" if api_mb is not None else ""),
        f"{mark(mem_av < 300, mem_av < 800)} Память: свободно {mem_av:.0f} из {mem_tot:.0f} МБ"
        + (f", swap {swap_tot - swap_free:.0f}/{swap_tot:.0f} МБ" if swap_tot else ", swap нет"),
        f"{mark(load > cpus * 2, load > cpus)} Нагрузка CPU: {load:.2f} (ядер: {cpus})",
        f"⏱ Бот работает: {_fmt_uptime(time.time() - BOT_STARTED)}",
        "",
        f"📥 Очередь: {queued}, в работе: {running}, среднее время задачи: {avg / 60:.1f} мин",
        f"{mark(errors_24h > 20, errors_24h > 0)} Ошибок за сутки: {errors_24h}, неудачных задач: {failed_24h}",
    ]
    return "\n".join(lines)


def errors_text(limit: int = 10) -> str:
    with db._db() as c:
        rows = c.execute(
            "SELECT created_at, source, message FROM bot_errors ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        failed = c.execute(
            "SELECT created_at, user_id, error FROM jobs WHERE status='failed' ORDER BY id DESC LIMIT 5"
        ).fetchall()
    if not rows and not failed:
        return "✅ <b>Ошибок нет</b>\n\nЗа последнее время бот работал без сбоев."
    out = ["🧯 <b>Последние ошибки</b> (новые сверху)\n"]
    for r in rows:
        t = _local_time(r["created_at"])
        out.append(f"• <code>{t}</code> {html.escape(r['message'][:300])}")
    if failed:
        out.append("\n❌ <b>Неудачные задачи пользователей</b>")
        for r in failed:
            out.append(f"• <code>{_local_time(r['created_at'])}</code> id {r['user_id']}: {html.escape((r['error'] or '—')[:150])}")
    text = "\n".join(out)
    return text[:3900]


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d.%m %H:%M")
    except ValueError:
        return iso[:16]


def clear_errors_sync() -> None:
    with db._db() as c:
        c.execute("DELETE FROM bot_errors")


# ---------------------------------------------------------------- handlers

def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _B(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def dashboard_keyboard(current: str) -> InlineKeyboardMarkup:
    tabs = [("📊 Статистика", "astats"), ("🩺 Сервер", "ahealth"), ("🧯 Ошибки", "aerrors")]
    rows = [[_B(("• " + t) if d == current else t, d) for t, d in tabs]]
    rows.append([_B("🔄 Обновить", current)])
    if current == "aerrors":
        rows.append([_B("🧹 Очистить список ошибок", "aerrors_clear")])
    rows.append([_B("◀️ В админку", "admin")])
    return _kb(rows)


def register_admin_stats(router: Router) -> None:
    if getattr(router, "_media_hunter_admin_stats", False):
        return
    router._media_hunter_admin_stats = True
    router.message.outer_middleware(ActivityMiddleware())
    router.callback_query.outer_middleware(ActivityMiddleware())

    async def _show(c: CallbackQuery, text: str, tab: str) -> None:
        await c.answer()
        try:
            await c.message.edit_text(text, reply_markup=dashboard_keyboard(tab), parse_mode="HTML")
        except Exception:
            pass  # "message is not modified" on refresh without changes

    @router.callback_query(F.data == "astats")
    async def astats(c: CallbackQuery):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await _show(c, await asyncio.to_thread(stats_text), "astats")

    @router.callback_query(F.data == "ahealth")
    async def ahealth(c: CallbackQuery, engine=None):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await _show(c, await asyncio.to_thread(health_text, engine), "ahealth")

    @router.callback_query(F.data == "aerrors")
    async def aerrors(c: CallbackQuery):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await _show(c, await asyncio.to_thread(errors_text), "aerrors")

    @router.callback_query(F.data == "aerrors_clear")
    async def aerrors_clear(c: CallbackQuery):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await asyncio.to_thread(clear_errors_sync)
        await _show(c, await asyncio.to_thread(errors_text), "aerrors")

    @router.message(Command("status"))
    async def status_cmd(m: Message, engine=None):
        if m.from_user.id != ADMIN_ID:
            return
        await m.answer(await asyncio.to_thread(health_text, engine), reply_markup=dashboard_keyboard("ahealth"), parse_mode="HTML")
