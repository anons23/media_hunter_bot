"""Fair, bounded YouTube playlist handling layered onto the existing Engine.

Playlist requests occupy one logical queue slot and feed one video at a time.
Free users are limited by monthly playlist requests and videos per request.
Each playlist item is guarded at 80 MB before normal media processing.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import sqlite3
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import (
    COOKIES_PATH,
    DB_PATH,
    MAX_PLAYLIST_ITEMS,
    MAX_QUEUE_SIZE,
    SOFT_UNIQUE_SIZE_MB,
)
from . import db
from .processor import playlist_items, validate_source_url

logger = logging.getLogger(__name__)

FREE_PLAYLIST_MAX_VIDEOS = 20
FREE_PLAYLISTS_PER_MONTH = 3
PLAYLIST_MAX_ORIGINAL_MB = 80


@dataclass
class PlaylistState:
    uid: int
    remaining: deque[str]
    total: int
    accepted: int
    free: bool


def _month_key() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ensure_usage_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS playlist_usage(
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, month)
        )
        """
    )


def consume_free_playlist(uid: int, limit: int = FREE_PLAYLISTS_PER_MONTH) -> bool:
    month = _month_key()
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        con.execute("PRAGMA busy_timeout=30000")
        _ensure_usage_table(con)
        con.execute("INSERT OR IGNORE INTO playlist_usage(user_id, month, used) VALUES(?,?,0)", (uid, month))
        cur = con.execute(
            "UPDATE playlist_usage SET used=used+1 WHERE user_id=? AND month=? AND used<?",
            (uid, month, limit),
        )
        return cur.rowcount == 1


def refund_free_playlist(uid: int) -> None:
    month = _month_key()
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        con.execute("PRAGMA busy_timeout=30000")
        _ensure_usage_table(con)
        con.execute(
            "UPDATE playlist_usage SET used=CASE WHEN used>0 THEN used-1 ELSE 0 END WHERE user_id=? AND month=?",
            (uid, month),
        )


def free_playlist_usage(uid: int) -> int:
    month = _month_key()
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        con.execute("PRAGMA busy_timeout=30000")
        _ensure_usage_table(con)
        row = con.execute("SELECT used FROM playlist_usage WHERE user_id=? AND month=?", (uid, month)).fetchone()
        return int(row[0]) if row else 0


def _playlist_total(url: str) -> int | None:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-items",
        "0",
        "--print",
        "playlist:playlist_count",
        "--quiet",
        url,
    ]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        logger.warning("playlist count failed for %s: %s", url, proc.stderr[:500])
        return None
    values = []
    for line in proc.stdout.splitlines():
        try:
            value = int(line.strip())
        except ValueError:
            continue
        if value >= 1:
            values.append(value)
    return max(values) if values else None


def inspect_playlist(url: str, probe_limit: int) -> tuple[list[str], int | None]:
    safe = validate_source_url(url)
    items = playlist_items(safe, probe_limit)
    if len(items) <= 1:
        return items, 1 if items else None
    total = _playlist_total(safe)
    return items, total or len(items)


def _priority(premium: bool, playlist: bool = False) -> int:
    if premium:
        return 0
    return 2 if playlist else 1


def patch_engine(engine_cls, handlers_module) -> None:
    """Patch the existing Engine without rewriting handlers.py."""
    if getattr(engine_cls, "_playlist_support_patched", False):
        return

    original_add = engine_cls.add
    original_run_job = engine_cls._run_job
    original_restart = engine_cls.restart
    original_download = handlers_module.download

    async def add(self, uid: int, url: str | None = None, source: Path | None = None):
        if not url:
            return await original_add(self, uid, url=url, source=source)

        safe = validate_source_url(url)
        premium = await db.ais_premium(uid)
        probe_limit = max(FREE_PLAYLIST_MAX_VIDEOS, MAX_PLAYLIST_ITEMS)
        items, total = await asyncio.to_thread(inspect_playlist, safe, probe_limit)
        if len(items) <= 1:
            return await original_add(self, uid, url=safe, source=source)

        limit = MAX_PLAYLIST_ITEMS if premium else FREE_PLAYLIST_MAX_VIDEOS
        items = items[:limit]
        if not items:
            raise RuntimeError("Плейлист не содержит доступных видео.")

        if not premium:
            if not consume_free_playlist(uid):
                raise RuntimeError(
                    f"Бесплатный тариф позволяет обработать до {FREE_PLAYLISTS_PER_MONTH} плейлистов в месяц. "
                    "Оформите Premium или попробуйте снова в следующем месяце."
                )

        async with self._lock:
            if uid in self._restarting:
                if not premium:
                    refund_free_playlist(uid)
                raise RuntimeError("Ваши задачи сейчас перезапускаются. Попробуйте снова через несколько секунд.")
            if self._queue_size >= self._max_queue:
                if not premium:
                    refund_free_playlist(uid)
                raise RuntimeError(f"Очередь переполнена ({self._max_queue} задач). Попробуйте позже.")

            self._queue_size += 1
            # A playlist is one logical user task, regardless of how many
            # continuation items it contains. This intentionally bypasses
            # MAX_USER_QUEUE for playlist continuations.
            self._user_queue_size[uid] = self._user_queue_size.get(uid, 0) + 1
            self.seq += 1
            seq = self.seq
            generation = self.gen.get(uid, 0)
            state = PlaylistState(uid, deque(items[1:]), int(total or len(items)), len(items), not premium)
            states = getattr(self, "_playlist_states", None)
            if states is None:
                states = self._playlist_states = {}
            states[seq] = state
            try:
                await self.q.put(Job(_priority(premium, playlist=True), seq, uid, generation, items[0], None))
            except Exception:
                states.pop(seq, None)
                self._queue_size = max(0, self._queue_size - 1)
                count = self._user_queue_size.get(uid, 0) - 1
                if count > 0:
                    self._user_queue_size[uid] = count
                else:
                    self._user_queue_size.pop(uid, None)
                if not premium:
                    refund_free_playlist(uid)
                raise

        if premium:
            await self.bot.send_message(
                uid,
                f"📚 Найдено {int(total or len(items))} видео в плейлисте. "
                f"В этом запросе будут обработаны первые {len(items)}.\n"
                "▶️ Видео идут по одному, чтобы не блокировать очередь бота.",
            )
        else:
            extra = " Остальные видео будут пропущены." if (total or len(items)) > len(items) else ""
            await self.bot.send_message(
                uid,
                f"📚 Найдено {int(total or len(items))} видео в плейлисте.\n"
                f"🆓 Бесплатный тариф: за раз обрабатываются только первые {len(items)} видео.{extra}\n"
                f"📅 Лимит: до {FREE_PLAYLIST_MAX_VIDEOS} видео за запрос и {FREE_PLAYLISTS_PER_MONTH} плейлистов в месяц.\n"
                "▶️ Видео идут по одному, чтобы не блокировать очередь бота.",
            )

    async def run_job(self, j):
        states = getattr(self, "_playlist_states", {})
        state = states.get(j.seq)
        playlist_guard = state is not None
        token = _PLAYLIST_DOWNLOAD_GUARD.set(playlist_guard)
        try:
            await original_run_job(self, j)
        finally:
            _PLAYLIST_DOWNLOAD_GUARD.reset(token)
            if state is not None:
                states.pop(j.seq, None)
                if j.generation != self.gen.get(j.uid, 0) or j.uid in self._restarting:
                    return
                if not state.remaining:
                    return
                next_url = state.remaining.popleft()
                async with self._lock:
                    if self._queue_size >= self._max_queue:
                        state.remaining.appendleft(next_url)
                        return
                    self._queue_size += 1
                    self._user_queue_size[j.uid] = self._user_queue_size.get(j.uid, 0) + 1
                    self.seq += 1
                    seq = self.seq
                    generation = self.gen.get(j.uid, 0)
                    states[seq] = state
                    try:
                        await self.q.put(Job(_priority(await db.ais_premium(j.uid), playlist=True), seq, j.uid, generation, next_url, None))
                    except Exception:
                        states.pop(seq, None)
                        self._queue_size = max(0, self._queue_size - 1)
                        count = self._user_queue_size.get(j.uid, 0) - 1
                        if count > 0:
                            self._user_queue_size[j.uid] = count
                        else:
                            self._user_queue_size.pop(j.uid, None)
                        state.remaining.appendleft(next_url)
                        raise

    async def restart(self, uid: int):
        states = getattr(self, "_playlist_states", {})
        for seq, state in list(states.items()):
            if state.uid == uid:
                states.pop(seq, None)
        return await original_restart(self, uid)

    async def guarded_download(url, work_dir, register):
        if _PLAYLIST_DOWNLOAD_GUARD.get():
            known = await asyncio.to_thread(_known_video_size, url)
            if known is not None and known > PLAYLIST_MAX_ORIGINAL_MB * 1024 * 1024:
                raise RuntimeError(
                    f"Видео из плейлиста пропущено: исходный размер больше {PLAYLIST_MAX_ORIGINAL_MB} МБ."
                )
            result = await asyncio.to_thread(original_download, url, work_dir, register)
            source, title = result
            if source.exists() and source.stat().st_size > PLAYLIST_MAX_ORIGINAL_MB * 1024 * 1024:
                raise RuntimeError(
                    f"Видео из плейлиста пропущено: исходный размер больше {PLAYLIST_MAX_ORIGINAL_MB} МБ."
                )
            return result
        return await asyncio.to_thread(original_download, url, work_dir, register)

    # _run_job calls handlers.download through the module global, so replace
    # that exact symbol. The wrapper itself is sync because _run_job calls it
    # inside asyncio.to_thread().
    def guarded_download_sync(url, work_dir, register):
        if _PLAYLIST_DOWNLOAD_GUARD.get():
            known = _known_video_size(url)
            if known is not None and known > PLAYLIST_MAX_ORIGINAL_MB * 1024 * 1024:
                raise RuntimeError(
                    f"Видео из плейлиста пропущено: исходный размер больше {PLAYLIST_MAX_ORIGINAL_MB} МБ."
                )
            source, title = original_download(url, work_dir, register)
            if source.exists() and source.stat().st_size > PLAYLIST_MAX_ORIGINAL_MB * 1024 * 1024:
                raise RuntimeError(
                    f"Видео из плейлиста пропущено: исходный размер больше {PLAYLIST_MAX_ORIGINAL_MB} МБ."
                )
            return source, title
        return original_download(url, work_dir, register)

    engine_cls.add = add
    engine_cls._run_job = run_job
    engine_cls.restart = restart
    handlers_module.download = guarded_download_sync
    engine_cls._playlist_support_patched = True


try:
    from contextvars import ContextVar
    _PLAYLIST_DOWNLOAD_GUARD: ContextVar[bool] = ContextVar("playlist_download_guard", default=False)
except Exception:  # pragma: no cover
    _PLAYLIST_DOWNLOAD_GUARD = None


def _known_video_size(url: str) -> int | None:
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--print",
        "%(filesize,filesize_approx)s",
        "--quiet",
        "--no-warnings",
        url,
    ]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        value = line.strip()
        if not value or value == "NA":
            continue
        try:
            size = int(float(value))
        except ValueError:
            continue
        if size > 0:
            return size
    return None
