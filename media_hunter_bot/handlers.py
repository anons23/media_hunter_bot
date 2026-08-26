"""Aiogram handlers + processing engine for Media Hunter Bot.

Critical fixes applied:
1. StateFilter(None) on url_message/upload so they do NOT intercept FSM input.
2. Engine queue-size tracking is now atomic via asyncio.Lock.
3. Temporary directories are cleaned up via try/finally in every handler.
4. OPP private-invite links are handled gracefully.
5. All blocking subprocess calls wrapped in asyncio.to_thread().
6. restart() drains queued jobs and kills subprocesses.
7. shutdown() kills FFmpeg/yt-dlp before stopping workers.
8. ThrottlingMiddleware replies to Messages too.
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import os
import secrets
import shutil
import signal
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    TelegramObject,
)

from .config import (
    ADMIN_ID,
    BOT_TOKEN,
    CLEANER_AGE_HOURS,
    LOCAL_BOT_API,
    LOGO_DIR,
    MAX_CONCURRENT,
    MAX_PLAYLIST_ITEMS,
    MAX_QUEUE_SIZE,
    MAX_USER_QUEUE,
    MAX_URL_LOGICAL_MB,
    MAX_USER_UPLOAD_MB,
    MEDIA_DIR,
    PREMIUM_PLANS,
)
from . import db
from .processor import (
    _is_valid_color,
    cleanup_media,
    cleanup_logos,
    download,
    ffprobe,
    metadata,
    playlist_items,
    process_media,
    validate_logo,
    validate_source_url,
)

router = Router()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Middleware
# ═══════════════════════════════════════════════════════════════════════════════

class ThrottlingMiddleware(BaseMiddleware):
    """Per-user rate limit with automatic stale-entry GC."""

    def __init__(self, rate: float = 1.0, cleanup_every: int = 500):
        self.rate = rate
        self._cleanup_every = cleanup_every
        self._last: dict[int, float] = {}
        self._req_count = 0

    async def __call__(self, handler, event: TelegramObject, data: dict):
        uid = None
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id

        if uid is not None:
            now = asyncio.get_running_loop().time()
            last = self._last.get(uid, 0)
            if now - last < self.rate:
                if isinstance(event, CallbackQuery):
                    await event.answer("Слишком быстро", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⏳ Слишком быстро, подождите секунду.")
                return None
            self._last[uid] = now

            self._req_count += 1
            if self._req_count >= self._cleanup_every:
                self._req_count = 0
                cutoff = now - self.rate * 3
                self._last = {k: v for k, v in self._last.items() if v > cutoff}

        return await handler(event, data)


router.message.middleware(ThrottlingMiddleware(rate=0.8))
router.callback_query.middleware(ThrottlingMiddleware(rate=0.5))


# ═══════════════════════════════════════════════════════════════════════════════
#  States & UI helpers
# ═══════════════════════════════════════════════════════════════════════════════

class S(StatesGroup):
    channel = State()
    wm = State()
    logo = State()
    admin_opp = State()
    admin_ad = State()
    admin_stars = State()


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def B(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def menu(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [B("📥 Скачать", "download"), B("📤 Моё видео", "upload")],
        [B("📺 Каналы", "channels"), B("💧 Водяной знак", "wm")],
        [B("⚙️ Настройки", "settings"), B("⭐ Premium", "premium")],
        [B("🔄 Рестарт моих задач", "restart")],
    ]
    if uid == ADMIN_ID:
        rows.append([B("👑 Admin", "admin")])
    return kb(rows)


def premium_menu() -> InlineKeyboardMarkup:
    return kb(
        [
            [B("⭐ 1 месяц — 150", "buy:30"), B("⭐ 2 месяца — 285", "buy:60")],
            [B("⭐ 3 месяца — 405", "buy:90"), B("⭐ 6 месяцев — 720", "buy:180")],
            [B("💎 Купить Stars", "stars")],
            [B("◀️ Назад", "back")],
        ]
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  OPP (mandatory subscription) check
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_opp_target(url: str) -> str | int | None:
    """Extract Telegram chat identifier from OPP URL.

    Returns:
        @username  for public channels
        int       for numeric chat IDs
        None      for private invite links (t.me/+hash) — cannot check membership
    """
    path = urlparse(url).path.strip("/")
    if not path or path.startswith("+"):
        return None
    target = path.split("/")[0]
    if target.isdigit():
        return int(target)
    return target if target.startswith("@") else "@" + target


async def opp_check(bot: Bot, uid: int) -> tuple[bool, list[list[InlineKeyboardButton]]]:
    """Return (missing_any, keyboard_rows)."""
    rows: list[list[InlineKeyboardButton]] = []
    missing = False
    for r in await db.aactive_opp():
        target = _resolve_opp_target(r["url"])
        ok = False
        if target is not None:
            try:
                m = await bot.get_chat_member(target, uid)
                ok = m.status in ("member", "administrator", "creator") or (
                    m.status == "restricted" and getattr(m, "is_member", False)
                )
            except Exception:
                ok = False
        if target is None:
            logger.warning("OPP slot %s uses a private invite link; membership cannot be verified", r["slot"])
            continue
        if not ok:
            missing = True
            rows.append([B(r["title"] or f'ОПП {r["slot"]}', url=r["url"])])
    if missing:
        rows.append([B("🔄 Проверить подписку", "check_opp")])
    return missing, rows


# ═══════════════════════════════════════════════════════════════════════════════
#  Job & Engine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(order=True)
class Job:
    priority: int
    seq: int
    uid: int = field(compare=False)
    generation: int = field(compare=False)
    url: str | None = field(compare=False, default=None)
    source: Path | None = field(compare=False, default=None)


class Engine:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.q: asyncio.PriorityQueue[Job] = asyncio.PriorityQueue()
        self.seq = 0
        self.gen: dict[int, int] = {}
        self.tasks: dict[int, set[asyncio.Task]] = {}
        self.processes: dict[int, set] = {}
        self.uploads: dict[int, set[Path]] = {}
        self.active_work_dirs: set[str] = set()
        self.workers: list[asyncio.Task] = []
        self.cleaner_task: asyncio.Task | None = None
        self._queue_size = 0
        self._user_queue_size: dict[int, int] = {}
        self._max_queue = MAX_QUEUE_SIZE
        self._lock = asyncio.Lock()
        self._proc_lock = threading.Lock()

    async def start(self):
        for _ in range(MAX_CONCURRENT):
            self.workers.append(asyncio.create_task(self._worker()))
        self.cleaner_task = asyncio.create_task(self._cleaner())

    async def add(self, uid: int, url: str | None = None, source: Path | None = None):
        if url:
            url = validate_source_url(url)
        await db.aensure_user(uid)
        premium = await db.ais_premium(uid)
        async with self._lock:
            if self._queue_size >= self._max_queue:
                raise RuntimeError(
                    f"Очередь переполнена ({self._max_queue} задач). Попробуйте позже."
                )
            if self._user_queue_size.get(uid, 0) >= MAX_USER_QUEUE:
                raise RuntimeError(
                    f"Для одного пользователя можно поставить не более {MAX_USER_QUEUE} задач в очередь."
                )
            self._queue_size += 1
            self._user_queue_size[uid] = self._user_queue_size.get(uid, 0) + 1
            self.seq += 1
            seq = self.seq
            generation = self.gen.get(uid, 0)
        if source:
            self.uploads.setdefault(uid, set()).add(source.parent)
        try:
            await self.q.put(
                Job(0 if premium else 1, seq, uid, generation, url, source)
            )
        except Exception:
            async with self._lock:
                self._queue_size = max(0, self._queue_size - 1)
                count = self._user_queue_size.get(uid, 0) - 1
                if count > 0:
                    self._user_queue_size[uid] = count
                else:
                    self._user_queue_size.pop(uid, None)
            raise

    def register(self, uid: int, proc):
        with self._proc_lock:
            if proc is None:
                for p in list(self.processes.get(uid, set())):
                    if getattr(p, "returncode", None) is not None:
                        self.processes[uid].discard(p)
                return
            self.processes.setdefault(uid, set()).add(proc)

    def active_paths(self) -> set[str]:
        paths = set(self.active_work_dirs)
        for roots in self.uploads.values():
            paths.update(str(p) for p in roots if p.exists())
        return paths

    async def restart(self, uid: int):
        self.gen[uid] = self.gen.get(uid, 0) + 1
        tasks = list(self.tasks.get(uid, set()))
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.pop(uid, None)

        async with self._lock:
            queued = list(self.q._queue)
            kept = [job for job in queued if job.uid != uid]
            removed = len(queued) - len(kept)
            if removed:
                self.q._queue[:] = kept
                heapq.heapify(self.q._queue)
                self._queue_size = max(0, self._queue_size - removed)
                count = self._user_queue_size.get(uid, 0) - removed
                if count > 0:
                    self._user_queue_size[uid] = count
                else:
                    self._user_queue_size.pop(uid, None)

        with self._proc_lock:
            procs = list(self.processes.get(uid, set()))
            self.processes.pop(uid, None)
        for p in procs:
            try:
                if p.returncode is None:
                    p.terminate()
                    try:
                        await asyncio.wait_for(asyncio.to_thread(p.wait), timeout=5)
                    except asyncio.TimeoutError:
                        p.kill()
            except Exception:
                pass

        for root in list(self.uploads.pop(uid, set())):
            await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)

    async def _worker(self):
        while True:
            j = await self.q.get()
            try:
                if j.generation != self.gen.get(j.uid, 0):
                    continue
                t = asyncio.create_task(self._run_job(j))
                self.tasks.setdefault(j.uid, set()).add(t)
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                finally:
                    self.tasks.get(j.uid, set()).discard(t)
                    if not self.tasks.get(j.uid):
                        self.tasks.pop(j.uid, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker failed for uid=%s", j.uid)
            finally:
                self.q.task_done()
                async with self._lock:
                    self._queue_size = max(0, self._queue_size - 1)
                    count = self._user_queue_size.get(j.uid, 0) - 1
                    if count > 0:
                        self._user_queue_size[j.uid] = count
                    else:
                        self._user_queue_size.pop(j.uid, None)

    async def _run_job(self, j: Job):
        if j.generation != self.gen.get(j.uid, 0):
            return

        work = MEDIA_DIR / f"{j.uid}_{uuid.uuid4().hex}"
        work.mkdir(parents=True, exist_ok=True)
        self.active_work_dirs.add(str(work))
        register = lambda p=None: self.register(j.uid, p)

        try:
            user = await db.aget_user(j.uid)
            if not user:
                return

            # ── download / resolve source ──────────────────────────────────
            if j.url:
                safe_url = validate_source_url(j.url)
                items = await asyncio.to_thread(playlist_items, safe_url, MAX_PLAYLIST_ITEMS)
                if len(items) > 1:
                    premium = await db.ais_premium(j.uid)
                    async with self._lock:
                        free_global = self._max_queue - self._queue_size
                        free_user = MAX_USER_QUEUE - self._user_queue_size.get(j.uid, 0)
                        free = min(free_global, free_user)
                        if len(items) > free:
                            raise RuntimeError(
                                f"Плейлист содержит {len(items)} видео, но свободно только {free} мест для ваших задач."
                            )
                        jobs = []
                        generation = self.gen.get(j.uid, 0)
                        for u in items:
                            self.seq += 1
                            self._queue_size += 1
                            self._user_queue_size[j.uid] = self._user_queue_size.get(j.uid, 0) + 1
                            jobs.append(Job(0 if premium else 1, self.seq, j.uid, generation, u, None))
                        for job in jobs:
                            await self.q.put(job)
                    await self.bot.send_message(
                        j.uid,
                        f"📚 Плейлист: {len(items)} видео добавлено в очередь.",
                    )
                    return
                source_url = items[0] if len(items) == 1 else j.url
                source = await asyncio.to_thread(download, source_url, work, register)
            else:
                source = j.source

            if not source or not source.exists():
                raise RuntimeError("Исходный файл не найден")

            # ── probe & limits ─────────────────────────────────────────────
            _, size = await asyncio.to_thread(ffprobe, source)
            oversized = size > MAX_URL_LOGICAL_MB * 1024 * 1024
            fmt = user["format"]
            audio_only = fmt == "mp3"
            limit = MAX_URL_LOGICAL_MB * 1024 * 1024

            # 1st pass
            result = await asyncio.to_thread(
                process_media,
                source,
                work,
                await db.aget_user_watermark(j.uid),
                audio_only=audio_only,
                compress=oversized and not audio_only,
                register=register,
            )
            result_size = (await asyncio.to_thread(result.stat)).st_size

            # 2nd pass: watermark bloated the file
            needs_second = not audio_only and not oversized and result_size > limit
            if needs_second:
                result = await asyncio.to_thread(
                    process_media,
                    source,
                    work,
                    await db.aget_user_watermark(j.uid),
                    audio_only=False,
                    compress=True,
                    register=register,
                )
                result_size = (await asyncio.to_thread(result.stat)).st_size

            if not audio_only and result_size > limit:
                raise RuntimeError(
                    f"Не удалось подготовить видео до лимита {MAX_URL_LOGICAL_MB} МБ"
                )

            # ── send to user ───────────────────────────────────────────────
            meta = await asyncio.to_thread(metadata, source)
            caption = str(meta.get("description") or meta.get("title") or "")[:900]
            if oversized:
                caption += (
                    f"\n\nℹ️ Исходный файл превышал {MAX_URL_LOGICAL_MB} МБ. "
                    "Видео сжато до установленного лимита."
                )
            await self._send_private(j.uid, result, caption)

            # ── autopost to channels ───────────────────────────────────────
            for ch in await db.alist_channels(j.uid):
                if not ch["enabled"]:
                    continue
                try:
                    if audio_only:
                        cr = result
                    else:
                        cr = await asyncio.to_thread(
                            process_media,
                            source,
                            work,
                            await db.aget_channel_watermark(ch["channel_id"], j.uid),
                            audio_only=False,
                            compress=oversized,
                            register=register,
                        )
                        cr_size = (await asyncio.to_thread(cr.stat)).st_size
                        # 2nd pass: channel watermark bloated the file
                        if not oversized and cr_size > limit:
                            cr = await asyncio.to_thread(
                                process_media,
                                source,
                                work,
                                await db.aget_channel_watermark(ch["channel_id"], j.uid),
                                audio_only=False,
                                compress=True,
                                register=register,
                            )
                            cr_size = (await asyncio.to_thread(cr.stat)).st_size
                        if cr_size > limit:
                            raise RuntimeError(
                                f"канальное видео превышает лимит {MAX_URL_LOGICAL_MB} МБ"
                            )
                    if cr.suffix.lower() == ".mp3":
                        await self.bot.send_audio(ch["channel_id"], FSInputFile(cr))
                    else:
                        await self.bot.send_video(
                            ch["channel_id"],
                            FSInputFile(cr),
                            caption=caption or None,
                            supports_streaming=True,
                        )
                except Exception as e:
                    await self.bot.send_message(
                        j.uid,
                        f'⚠️ Автопост в «{ch["title"]}» не выполнен: {str(e)[:250]}',
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            try:
                await self.bot.send_message(
                    j.uid, f"❌ Не удалось обработать: {str(e)[:700]}"
                )
            except Exception:
                pass
        finally:
            self.active_work_dirs.discard(str(work))
            if j.source:
                upload_root = j.source.parent
                roots = self.uploads.get(j.uid, set())
                roots.discard(upload_root)
                if not roots:
                    self.uploads.pop(j.uid, None)
                if upload_root.name.startswith(f"upload_{j.uid}_"):
                    await asyncio.to_thread(shutil.rmtree, upload_root, ignore_errors=True)
            await asyncio.to_thread(shutil.rmtree, work, ignore_errors=True)

    async def _send_private(self, uid: int, path: Path, caption: str):
        if path.suffix.lower() == ".mp3":
            await self.bot.send_audio(uid, FSInputFile(path), caption=caption or None)
        else:
            await self.bot.send_video(
                uid, FSInputFile(path), caption=caption or None, supports_streaming=True
            )
        ad = await db.aget_setting("ad_text", "")
        button = await db.aget_setting("ad_button", "")
        url = await db.aget_setting("ad_url", "")
        if ad:
            rows = [[B(button, url=url)]] if button and url else []
            await self.bot.send_message(
                uid, ad, reply_markup=kb(rows) if rows else None
            )

    async def _cleaner(self):
        while True:
            try:
                await asyncio.sleep(3600)
                await asyncio.to_thread(
                    cleanup_media, CLEANER_AGE_HOURS, self.active_paths()
                )
                active_logos = await db.aactive_logo_paths()
                await asyncio.to_thread(
                    cleanup_logos, CLEANER_AGE_HOURS * 7, active_logos
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cleaner failed")

    async def shutdown(self):
        # Kill running subprocesses first
        with self._proc_lock:
            all_procs = [(uid, list(procs)) for uid, procs in self.processes.items()]
        for uid, procs in all_procs:
            for p in procs:
                try:
                    if p.returncode is None:
                        p.terminate()
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(p.wait), timeout=3
                            )
                        except asyncio.TimeoutError:
                            p.kill()
                except Exception:
                    pass
        self.processes.clear()
        if self.cleaner_task:
            self.cleaner_task.cancel()
        for t in list(self.workers):
            t.cancel()
        tasks = [*self.workers]
        if self.cleaner_task:
            tasks.append(self.cleaner_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.workers.clear()
        self.cleaner_task = None
# ═══════════════════════════════════════════════════════════════════════════════
#  User handlers
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def start(m: Message, bot: Bot):
    await db.aensure_user(
        m.from_user.id, m.from_user.username, m.from_user.first_name
    )
    if m.text:
        parts = m.text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1][4:])
                await db.aapply_referral(m.from_user.id, referrer_id)
            except ValueError:
                pass
    missing, rows = await opp_check(bot, m.from_user.id)
    if missing:
        await m.answer(
            "🔐 Для использования бота выполните обязательные подписки:",
            reply_markup=kb(rows + [[B("◀️ Назад", "back")]]),
        )
        return
    await m.answer("👋 Media Hunter готов.", reply_markup=menu(m.from_user.id))


@router.callback_query(F.data == "menu_ref")
async def menu_ref(c: CallbackQuery, bot: Bot):
    me = await bot.get_me()
    username = me.username
    if not username:
        await c.answer("Не удалось получить ссылку реферала.", show_alert=True)
        return
    count = await db.aget_referrals(c.from_user.id)
    link = f"https://t.me/{username}?start=ref_{c.from_user.id}"
    await c.answer()
    await c.message.edit_text(
        f"🎁 Ваша реферальная ссылка:\n{link}\n\nПриглашено пользователей: {count}",
        reply_markup=kb([[B("◀️ Назад", "back")]]),
    )


@router.callback_query(F.data == "check_opp")
async def check_opp(c: CallbackQuery, bot: Bot):
    missing, rows = await opp_check(bot, c.from_user.id)
    await c.answer()
    await c.message.edit_text(
        "❌ Не все обязательные подписки выполнены."
        if missing
        else "✅ ОПП выполнены.",
        reply_markup=kb(rows) if missing else menu(c.from_user.id),
    )


@router.callback_query(F.data == "back")
async def back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await c.message.edit_text("Главное меню:", reply_markup=menu(c.from_user.id))


@router.callback_query(F.data == "settings")
async def settings(c: CallbackQuery):
    u = await db.aget_user(c.from_user.id)
    f = u["format"] if u else "video"
    await c.answer()
    await c.message.edit_text(
        f'⚙️ Формат: {"🎵 Только MP3" if f == "mp3" else "🎬 Видео"}',
        reply_markup=kb(
            [
                [B("🎬 Видео", "fmt:video"), B("🎵 Только MP3", "fmt:mp3")],
                [B("◀️ Назад", "back")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("fmt:"))
async def fmt(c: CallbackQuery):
    v = c.data.split(":", 1)[1]
    if v not in {"video", "mp3"}:
        await c.answer("Ошибка", show_alert=True)
        return
    await db.aset_format(c.from_user.id, v)
    await c.answer("Сохранено")
    await settings(c)


@router.callback_query(F.data == "premium")
async def premium(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(
        "⭐ Выберите срок Premium:", reply_markup=premium_menu()
    )


@router.callback_query(F.data == "stars")
async def stars(c: CallbackQuery):
    url = await db.aget_setting("stars_link", "")
    if not url:
        await c.answer("Партнёрская ссылка Stars пока не настроена.", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text(
        "💎 Если не хватает Stars, купите их у партнёра:",
        reply_markup=kb(
            [
                [B("💎 Купить Stars", url=url)],
                [B("◀️ Назад", "premium")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery, bot: Bot):
    try:
        days = int(c.data.split(":", 1)[1])
        price = PREMIUM_PLANS[days]
    except (ValueError, KeyError):
        await c.answer("Некорректный тариф", show_alert=True)
        return
    user = await db.aget_user(c.from_user.id)
    if user and user["permanent_premium"]:
        await c.answer("У вас уже постоянный Premium.", show_alert=True)
        return
    payload = f"premium:{days}:{c.from_user.id}:{secrets.token_hex(8)}"
    await c.answer()
    await bot.send_invoice(
        c.from_user.id,
        f"Premium на {days // 30} мес.",
        f"Media Hunter Premium — {days} дней",
        payload,
        "XTR",
        [LabeledPrice(label="Premium", amount=price)],
    )


@router.pre_checkout_query()
async def checkout(q: PreCheckoutQuery, bot: Bot):
    parts = q.invoice_payload.split(":")
    ok = False
    if len(parts) == 4 and parts[0] == "premium":
        try:
            days = int(parts[1])
            uid = int(parts[2])
            ok = (
                uid == q.from_user.id
                and days in PREMIUM_PLANS
                and q.currency == "XTR"
                and q.total_amount == PREMIUM_PLANS[days]
            )
        except ValueError:
            pass
    await bot.answer_pre_checkout_query(
        q.id,
        ok=ok,
        error_message=None
        if ok
        else "Платёж не прошёл проверку. Откройте тариф заново.",
    )


@router.message(F.successful_payment)
async def paid(m: Message):
    p = m.successful_payment
    parts = p.invoice_payload.split(":")
    if len(parts) != 4 or parts[0] != "premium":
        return
    try:
        days = int(parts[1])
        uid = int(parts[2])
    except ValueError:
        return
    if (
        uid != m.from_user.id
        or days not in PREMIUM_PLANS
        or p.currency != "XTR"
        or p.total_amount != PREMIUM_PLANS[days]
    ):
        return
    if await db.asave_payment(
        m.from_user.id,
        p.invoice_payload,
        days,
        p.total_amount,
        p.telegram_payment_charge_id,
    ):
        await db.aextend_premium(m.from_user.id, days)
        await m.answer(
            f"🎉 Premium активирован на {days} дней!",
            reply_markup=menu(m.from_user.id),
        )


@router.callback_query(F.data == "download")
async def download_menu(c: CallbackQuery, bot: Bot):
    missing, _ = await opp_check(bot, c.from_user.id)
    if missing:
        await c.answer("Сначала выполните ОПП", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text(
        "📥 Пришлите ссылку YouTube/TikTok/Instagram. Формат берётся из настроек.",
        reply_markup=kb(
            [
                [B("⚙️ Формат", "settings")],
                [B("◀️ Назад", "back")],
            ]
        ),
    )


# CRITICAL FIX: StateFilter(None) prevents this handler from intercepting
# FSM input (e.g. adding a channel, setting watermark, admin panels).
@router.message(StateFilter(None), F.text.regexp(r"^https?://"))
async def url_message(m: Message, bot: Bot, engine: Engine):
    missing, rows = await opp_check(bot, m.from_user.id)
    if missing:
        await m.answer(
            "🔐 Сначала выполните обязательные подписки.", reply_markup=kb(rows)
        )
        return
    try:
        await engine.add(m.from_user.id, url=m.text.strip())
        await m.answer("⏳ Ссылка добавлена в очередь.")
    except RuntimeError as e:
        await m.answer(f"❌ {e}")


@router.callback_query(F.data == "upload")
async def upload_menu(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(
        f"📤 Отправьте видео до {MAX_USER_UPLOAD_MB} МБ.",
        reply_markup=kb([[B("◀️ Назад", "back")]]),
    )


# CRITICAL FIX: StateFilter(None) — same reason as url_message.
@router.message(StateFilter(None), F.video)
async def upload(m: Message, bot: Bot, engine: Engine):
    if m.video.file_size and m.video.file_size > MAX_USER_UPLOAD_MB * 1024 * 1024:
        await m.answer(f"❌ Максимум {MAX_USER_UPLOAD_MB} МБ.")
        return
    missing, rows = await opp_check(bot, m.from_user.id)
    if missing:
        await m.answer(
            "🔐 Сначала выполните обязательные подписки.", reply_markup=kb(rows)
        )
        return

    p = MEDIA_DIR / f"upload_{m.from_user.id}_{uuid.uuid4().hex}"
    p.mkdir(parents=True, exist_ok=True)
    dst = p / "upload.mp4"
    handed = False

    try:
        f = await asyncio.wait_for(bot.get_file(m.video.file_id), timeout=60)
        await asyncio.wait_for(
            bot.download_file(f.file_path, destination=dst), timeout=300
        )
        if dst.stat().st_size > MAX_USER_UPLOAD_MB * 1024 * 1024:
            raise RuntimeError(f"Файл превышает лимит {MAX_USER_UPLOAD_MB} МБ")
        await engine.add(m.from_user.id, source=dst)
        handed = True
        await m.answer("⏳ Видео принято в очередь.")
    except RuntimeError as e:
        await m.answer(f"❌ {e}")
    except Exception:
        raise
    finally:
        if not handed:
            await asyncio.to_thread(shutil.rmtree, p, ignore_errors=True)


@router.callback_query(F.data == "restart")
async def restart(c: CallbackQuery, engine: Engine):
    await engine.restart(c.from_user.id)
    await c.answer("Ваши задачи отменены")
    await c.message.edit_text(
        "🔄 Только ваши задачи отменены. Очереди других пользователей не затронуты.",
        reply_markup=menu(c.from_user.id),
    )


@router.callback_query(F.data == "channels")
async def channels(c: CallbackQuery):
    rows = [[B("➕ Добавить канал", "addch")]]
    for ch in await db.alist_channels(c.from_user.id):
        rows.append(
            [
                B(
                    f'{"🟢" if ch["enabled"] else "⚪"} {ch["title"] or ch["channel_id"]}',
                    f'ch:{ch["channel_id"]}',
                )
            ]
        )
    rows.append([B("◀️ Назад", "back")])
    await c.answer()
    await c.message.edit_text(
        "📺 Каналы (максимум 3):", reply_markup=kb(rows)
    )


@router.callback_query(F.data == "addch")
async def addch(c: CallbackQuery, state: FSMContext):
    if len(await db.alist_channels(c.from_user.id)) >= 3:
        await c.answer("Максимум 3", show_alert=True)
        return
    await state.set_state(S.channel)
    await c.answer()
    await c.message.edit_text(
        "Пришлите @username или ID канала. Бот должен быть администратором.",
        reply_markup=kb([[B("◀️ Назад", "channels")]]),
    )


@router.message(S.channel)
async def addch_value(m: Message, state: FSMContext, bot: Bot):
    try:
        text = (m.text or "").strip()
        if not text:
            await m.answer("❌ Пришлите @username или ID канала.")
            return
        chat = await bot.get_chat(text)
        # bot.id is a property in aiogram 3.x — use it directly
        me_member = await bot.get_chat_member(chat.id, bot.id)
        if me_member.status not in ("administrator", "creator"):
            raise RuntimeError("Сначала добавьте бота в администраторы канала.")
        await db.aadd_channel(
            m.from_user.id, chat.id, chat.title or str(chat.id)
        )
        await state.clear()
        await m.answer(
            "✅ Канал добавлен.", reply_markup=menu(m.from_user.id)
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await m.answer(
            "❌ Канал не найден или бот не имеет доступа. Добавьте бота в администраторы и попробуйте снова."
        )
    except ValueError as e:
        await m.answer(f"❌ {e}")
    except Exception as e:
        await m.answer("❌ Не удалось добавить канал: " + str(e)[:250])
@router.callback_query(F.data.startswith("ch:"))
async def ch(c: CallbackQuery):
    cid = int(c.data.split(":", 1)[1])
    row = next(
        (
            x
            for x in await db.alist_channels(c.from_user.id)
            if x["channel_id"] == cid
        ),
        None,
    )
    if not row:
        await c.answer("Канал не найден", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text(
        f'📺 {row["title"]}\nАвтопост: {"🟢 включён" if row["enabled"] else "⚪ выключен"}',
        reply_markup=kb(
            [
                [B("🔄 Автопост", f"toggle:{cid}"), B("💧 Watermark", f"cwm:{cid}")],
                [B("🗑 Удалить", f"del:{cid}")],
                [B("◀️ Назад", "channels")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("toggle:"))
async def toggle(c: CallbackQuery):
    cid = int(c.data.split(":", 1)[1])
    row = next(
        (
            x
            for x in await db.alist_channels(c.from_user.id)
            if x["channel_id"] == cid
        ),
        None,
    )
    if not row:
        await c.answer("Канал не найден", show_alert=True)
        return
    await db.aset_channel_enabled(c.from_user.id, cid, not bool(row["enabled"]))
    await c.answer("Сохранено")
    await ch(c)


@router.callback_query(F.data.startswith("del:"))
async def dele(c: CallbackQuery):
    await db.aremove_channel(c.from_user.id, int(c.data.split(":", 1)[1]))
    await c.answer("Удалено")
    await channels(c)

@router.callback_query(F.data == "wm")
async def wm(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(
        "💧 Водяной знак пользователя:",
        reply_markup=kb(
            [
                [B("📝 Текст", "wmtext")],
                [B("🖼 PNG", "wmlogo")],
                [B("◀️ Назад", "back")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("cwm:"))
async def cwm(c: CallbackQuery, state: FSMContext):
    await state.update_data(cid=int(c.data.split(":", 1)[1]))
    await c.answer()
    await c.message.edit_text(
        "💧 Watermark этого канала:",
        reply_markup=kb(
            [
                [B("📝 Текст", "cwmtext")],
                [B("🖼 PNG", "cwmlogo")],
                [B("◀️ Назад", "channels")],
            ]
        ),
    )


@router.callback_query(F.data.in_({"wmtext", "cwmtext"}))
async def wmtext(c: CallbackQuery, state: FSMContext):
    cid = None if c.data == "wmtext" else (await state.get_data()).get("cid")
    await state.update_data(channel=cid)
    await state.set_state(S.wm)
    await c.answer()
    await c.message.edit_text(
        "Введите: ТЕКСТ|ПОЗИЦИЯ|РАЗМЕР|ЦВЕТ|ПРОЗРАЧНОСТЬ\nНапример: PRESTIGE|br|28|white|0.8",
        reply_markup=kb(
            [[B("◀️ Назад", "wm" if cid is None else "channels")]]
        ),
    )


@router.message(S.wm)
async def wmvalue(m: Message, state: FSMContext):
    p = [x.strip() for x in (m.text or "").split("|")]
    if len(p) not in (1, 5):
        await m.answer("Формат: ТЕКСТ|ПОЗИЦИЯ|РАЗМЕР|ЦВЕТ|ПРОЗРАЧНОСТЬ")
        return
    try:
        text = p[0][:200]
        position = p[1] if len(p) == 5 else "br"
        size = int(p[2]) if len(p) == 5 else 28
        color = p[3] if len(p) == 5 else "white"
        opacity = float(p[4]) if len(p) == 5 else 0.8
        if (
            position not in {"tl", "tr", "bl", "br", "c"}
            or not 10 <= size <= 200
            or not 0.05 <= opacity <= 1
            or not _is_valid_color(color)
        ):
            raise ValueError
    except ValueError:
        await m.answer(
            "❌ Позиция tl/tr/bl/br/c; размер 10–200; прозрачность 0.05–1; цвет — имя или #RRGGBB."
        )
        return
    d = await state.get_data()
    w = {
        "type": "text",
        "text": text,
        "position": position,
        "size": size,
        "color": color,
        "opacity": opacity,
    }
    cid = d.get("channel")
    if cid:
        await db.aset_channel_watermark(cid, m.from_user.id, w)
    else:
        await db.aset_user_watermark(m.from_user.id, w)
    await state.clear()
    await m.answer(
        "✅ Текстовый watermark сохранён.", reply_markup=menu(m.from_user.id)
    )


@router.callback_query(F.data.in_({"wmlogo", "cwmlogo"}))
async def wmlogo(c: CallbackQuery, state: FSMContext):
    cid = None if c.data == "wmlogo" else (await state.get_data()).get("cid")
    await state.update_data(channel=cid)
    await state.set_state(S.logo)
    await c.answer()
    await c.message.edit_text(
        "🖼 Пришлите PNG-документ. Максимум 5 МБ и 2000×2000 px.",
        reply_markup=kb(
            [[B("◀️ Назад", "wm" if cid is None else "channels")]]
        ),
    )


@router.message(S.logo, F.document)
async def logovalue(m: Message, bot: Bot, state: FSMContext):
    name = (m.document.file_name or "").lower()
    if not name.endswith(".png") or (
        m.document.file_size and m.document.file_size > 5 * 1024 * 1024
    ):
        await m.answer("❌ Нужен PNG до 5 МБ.")
        return
    p = LOGO_DIR / f"logo_{m.from_user.id}_{uuid.uuid4().hex}.png"
    try:
        f = await asyncio.wait_for(bot.get_file(m.document.file_id), timeout=60)
        await asyncio.wait_for(
            bot.download_file(f.file_path, destination=p), timeout=300
        )
        ok, msg = await asyncio.to_thread(validate_logo, p)
        if not ok:
            p.unlink(missing_ok=True)
            await m.answer("❌ " + msg)
            return
        d = await state.get_data()
        cid = d.get("channel")
        w = {"type": "image", "logo": str(p), "position": "br"}
        if cid:
            await db.aset_channel_watermark(cid, m.from_user.id, w)
        else:
            await db.aset_user_watermark(m.from_user.id, w)
        await state.clear()
        await m.answer(
            "✅ PNG watermark сохранён.", reply_markup=menu(m.from_user.id)
        )
    except Exception:
        p.unlink(missing_ok=True)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
#  Admin handlers
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text(
        "👑 Админ-панель",
        reply_markup=kb(
            [
                [B("🔐 ОПП", "aopp")],
                [B("📣 Реклама", "aad")],
                [B("💎 Ссылка Stars", "astars")],
                [B("🔄 Обновить yt-dlp", "aytdlp")],
                [B("🔄 Перезапустить бота", "abot")],
                [B("◀️ Назад", "back")],
            ]
        ),
    )


@router.callback_query(F.data == "aopp")
async def aopp(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    rows = [
        [
            B(
                f'ОПП {r["slot"]}: {"🟢" if r["enabled"] else "⚪"}',
                f'opp:{r["slot"]}',
            )
        ]
        for r in await db.aget_opp()
    ]
    rows.append([B("◀️ Назад", "admin")])
    await c.answer()
    await c.message.edit_text(
        "Три независимых ОПП:", reply_markup=kb(rows)
    )


@router.callback_query(F.data.startswith("opp:"))
async def opp(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return
    await state.update_data(slot=int(c.data.split(":", 1)[1]))
    await state.set_state(S.admin_opp)
    await c.answer()
    await c.message.edit_text(
        "Отправьте: ВКЛ|Название кнопки|https://t.me/канал\nили ВЫКЛ"
    )


@router.message(S.admin_opp)
async def oppvalue(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    slot = (await state.get_data())["slot"]
    text = (m.text or "").strip()
    if text.upper() == "ВЫКЛ":
        await db.aset_opp(slot, False, "", "")
    else:
        p = text.split("|", 2)
        if len(p) != 3:
            await m.answer("Формат: ВКЛ|Название|https://t.me/канал")
            return
        opp_url = p[2].strip()
        parsed = urlparse(opp_url)
        scheme = parsed.scheme
        host = parsed.hostname
        path = parsed.path.strip("/")
        if (
            scheme != "https"
            or host not in ("t.me", "telegram.me")
            or not path
            or path.startswith("+")
            or path.startswith("joinchat/")
        ):
            await m.answer("❌ ОПП должна быть публичной ссылкой https://t.me/username. Приватные invite-ссылки проверить нельзя.")
            return
        await db.aset_opp(
            slot, p[0].strip().upper() == "ВКЛ", p[1].strip(), opp_url
        )
    await state.clear()
    await m.answer("✅ ОПП сохранено.", reply_markup=menu(m.from_user.id))


@router.callback_query(F.data == "aad")
async def aad(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return
    await state.set_state(S.admin_ad)
    await c.answer()
    await c.message.edit_text(
        "Отправьте: ТЕКСТ|НАЗВАНИЕ КНОПКИ|URL\nили ВЫКЛ. Реклама публикуется только после видео в личном чате."
    )


@router.message(S.admin_ad)
async def advalue(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    text = (m.text or "").strip()
    if text.upper() == "ВЫКЛ":
        for k in ("ad_text", "ad_button", "ad_url"):
            await db.aset_setting(k, "")
    else:
        p = text.split("|", 2)
        if len(p) != 3:
            await m.answer("Формат: ТЕКСТ|КНОПКА|URL")
            return
        for k, v in zip(("ad_text", "ad_button", "ad_url"), p):
            await db.aset_setting(k, v.strip())
    await state.clear()
    await m.answer("✅ Реклама сохранена.", reply_markup=menu(m.from_user.id))


@router.callback_query(F.data == "astars")
async def astars(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return
    await state.set_state(S.admin_stars)
    await c.answer()
    await c.message.edit_text("Пришлите новую партнёрскую ссылку Stars.")


@router.message(S.admin_stars)
async def astarsvalue(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    parsed = urlparse((m.text or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me"):
        await m.answer("❌ Нужна ссылка https://t.me/...")
        return
    await db.aset_setting("stars_link", m.text.strip())
    await state.clear()
    await m.answer(
        "✅ Ссылка Stars изменена.", reply_markup=menu(m.from_user.id)
    )


@router.callback_query(F.data == "aytdlp")
async def aytdlp(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer()
    await c.message.edit_text(
        "🔄 yt-dlp проверяется каждый день в 06:00 по Москве и после загрузки VPS. Если версия изменилась — бот перезапускается.",
        reply_markup=kb([[B("◀️ Назад", "admin")]]),
    )


@router.callback_query(F.data == "abot")
async def abot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer()
    await c.message.edit_text("Перезапустить бота?", reply_markup=kb([
        [B("✅ Подтвердить", "abot:yes"), B("❌ Отмена", "admin")]
    ]))


@router.callback_query(F.data == "abot:yes")
async def abot_yes(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("Бот перезапускается")
    asyncio.create_task(_exit_later())




    if c.from_user.id != ADMIN_ID:
        return
    await c.answer("VPS перезагружается", show_alert=True)
    asyncio.create_task(_reboot_later())


# ═══════════════════════════════════════════════════════════════════════════════
#  Lifecycle helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _exit_later():
    await asyncio.sleep(1)
    if os.name == "nt":
        os._exit(0)
    os.kill(os.getpid(), signal.SIGTERM)




@router.message(Command("paysupport"))
async def paysupport(m: Message):
    await m.answer("💳 По вопросам оплаты Premium напишите администратору.")


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db.init_db()

    if LOCAL_BOT_API:
        session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_BOT_API))
        bot = Bot(BOT_TOKEN, session=session)
    else:
        session = None
        bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    engine = Engine(bot)
    dp["engine"] = engine
    dp.include_router(router)

    # bot.id is a property in aiogram 3.x — do NOT assign to it
    await bot.get_me()  # warms up the cache only

    # Graceful shutdown on SIGTERM / SIGINT
    def _signal_handler(sig):
        logger.info("Received signal %s, initiating graceful shutdown...", sig.name)
        asyncio.create_task(dp.stop_polling())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _signal_handler(s))
        except ValueError:
            pass  # Windows lacks SIGTERM support

    await engine.start()
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    finally:
        await engine.shutdown()
        if session is not None:
            await session.close()
        else:
            await bot.session.close()
        logger.info("Bot stopped cleanly.")
