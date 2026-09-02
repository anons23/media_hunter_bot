import asyncio
import logging
import os
import shutil
import signal
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from .config import (
    ADMIN_ID,
    CLEANER_AGE_HOURS,
    LOCAL_BOT_API,
    MAX_CONCURRENT,
    MAX_PLAYLIST_ITEMS,
    MAX_QUEUE_SIZE,
    MAX_SEND_MB,
    MAX_WATERMARK_MB,
    MAX_SOURCE_DOWNLOAD_MB,
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
    safe_media_filename,
    ffprobe,
    metadata,
    playlist_items,
    process_media,
    validate_logo,
    validate_source_url,
)
from .progress import ProgressTracker
from .opp_logic import opp_check
from .opp_admin import register_opp_admin
from .wm_wizard import register_wm_wizard
from .user_errors import user_facing_error
router = Router()
logger = logging.getLogger(__name__)


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

register_opp_admin(router, menu)
register_wm_wizard(router, menu)


def premium_menu() -> InlineKeyboardMarkup:
    return kb([
        [B("⭐ 1 месяц — 150", "buy:30"), B("⭐ 2 месяца — 285", "buy:60")],
        [B("⭐ 3 месяца — 405", "buy:90"), B("⭐ 6 месяцев — 720", "buy:180")],
        [B("💎 Купить Stars", "stars")],
        [B("◀️ Назад", "back")],
    ])


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
        self._restarting: set[int] = set()

    async def start(self):
        for _ in range(MAX_CONCURRENT):
            self.workers.append(asyncio.create_task(self._worker()))
        self.cleaner_task = asyncio.create_task(self._cleaner())

    async def ensure_can_enqueue(self, uid: int) -> None:
        """Raise if a new job cannot be accepted right now (no side effects).

        Used by the upload path to reject early before downloading a large
        Telegram file. add() still re-checks under the same lock at enqueue.
        """
        async with self._lock:
            if uid in self._restarting:
                raise RuntimeError("Ваши задачи сейчас перезапускаются. Попробуйте снова через несколько секунд.")
            if self._queue_size >= self._max_queue:
                raise RuntimeError(f"Очередь переполнена ({self._max_queue} задач). Попробуйте позже.")
            if self._user_queue_size.get(uid, 0) >= MAX_USER_QUEUE:
                raise RuntimeError(f"Для одного пользователя можно поставить не более {MAX_USER_QUEUE} задач в очередь.")

    async def add(self, uid: int, url: str | None = None, source: Path | None = None):
        if url:
            url = validate_source_url(url)
        await db.aensure_user(uid)
        premium = await db.ais_premium(uid)

        async with self._lock:
            if uid in self._restarting:
                raise RuntimeError("Ваши задачи сейчас перезапускаются. Попробуйте снова через несколько секунд.")
            if self._queue_size >= self._max_queue:
                raise RuntimeError(f"Очередь переполнена ({self._max_queue} задач). Попробуйте позже.")
            if self._user_queue_size.get(uid, 0) >= MAX_USER_QUEUE:
                raise RuntimeError(f"Для одного пользователя можно поставить не более {MAX_USER_QUEUE} задач в очередь.")

            self._queue_size += 1
            self._user_queue_size[uid] = self._user_queue_size.get(uid, 0) + 1
            self.seq += 1
            seq = self.seq
            generation = self.gen.get(uid, 0)

            if source:
                self.uploads.setdefault(uid, set()).add(source.parent)

            try:
                await self.q.put(Job(0 if premium else 1, seq, uid, generation, url, source))
            except Exception:
                if source:
                    roots = self.uploads.get(uid)
                    if roots is not None:
                        roots.discard(source.parent)
                        if not roots:
                            self.uploads.pop(uid, None)

                self._queue_size = max(0, self._queue_size - 1)
                count = self._user_queue_size.get(uid, 0) - 1
                if count > 0:
                    self._user_queue_size[uid] = count
                else:
                    self._user_queue_size.pop(uid, None)
                raise

    def register(self, uid: int, proc, generation: int | None = None):
        with self._proc_lock:
            if proc is None:
                for p in list(self.processes.get(uid, set())):
                    if getattr(p, "returncode", None) is not None:
                        self.processes[uid].discard(p)
                return
            if generation is not None and generation != self.gen.get(uid, 0):
                try:
                    if getattr(proc, "returncode", None) is None:
                        proc.terminate()
                except Exception:
                    pass
                return
            self.processes.setdefault(uid, set()).add(proc)

    def active_paths(self) -> set[str]:
        paths = set(self.active_work_dirs)
        for roots in self.uploads.values():
            paths.update(str(p) for p in roots if p.exists())
        return paths

    async def restart(self, uid: int):
        async with self._lock:
            self.gen[uid] = self.gen.get(uid, 0) + 1
            self._restarting.add(uid)
        tasks = list(self.tasks.get(uid, set()))
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.pop(uid, None)
        async with self._lock:
            queued: list[Job] = []
            while True:
                try:
                    queued.append(self.q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            kept = [job for job in queued if job.uid != uid]
            removed = len(queued) - len(kept)
            for job in kept:
                await self.q.put(job)
            for _ in range(removed):
                self.q.task_done()
            if removed:
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
                        await asyncio.to_thread(p.wait)
            except Exception:
                pass
        for root in list(self.uploads.pop(uid, set())):
            await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
        async with self._lock:
            self._restarting.discard(uid)

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
        register = lambda p=None: self.register(j.uid, p, j.generation)
        progress = ProgressTracker(self.bot, j.uid, has_url=bool(j.url))
        try:
            user = await db.aget_user(j.uid)
            if not user:
                return
            if j.url:
                safe_url = validate_source_url(j.url)
                items = await asyncio.to_thread(playlist_items, safe_url, MAX_PLAYLIST_ITEMS)
                if len(items) > 1:
                    premium = await db.ais_premium(j.uid)
                    async with self._lock:
                        current_global = 1
                        current_user = 1
                        free_global = self._max_queue - self._queue_size + current_global
                        free_user = MAX_USER_QUEUE - self._user_queue_size.get(j.uid, 0) + current_user
                        free = min(free_global, free_user)
                        if len(items) > free:
                            raise RuntimeError(f"Плейлист содержит {len(items)} видео, но свободно только {free} мест для ваших задач.")
                        jobs = []
                        generation = self.gen.get(j.uid, 0)
                        for u in items:
                            try:
                                safe_item_url = validate_source_url(u)
                            except ValueError:
                                logger.warning("Skipping unsafe playlist item for uid=%s: %s", j.uid, u)
                                continue
                            self.seq += 1
                            self._queue_size += 1
                            self._user_queue_size[j.uid] = self._user_queue_size.get(j.uid, 0) + 1
                            jobs.append(Job(0 if premium else 1, self.seq, j.uid, generation, safe_item_url, None))
                        for job in jobs:
                            await self.q.put(job)
                    if not jobs:
                        await self.bot.send_message(j.uid, "📚 Плейлист не содержит допустимых ссылок.")
                    elif len(jobs) < len(items):
                        await self.bot.send_message(j.uid, f"📚 Плейлист: {len(jobs)} из {len(items)} видео добавлено в очередь.")
                    else:
                        await self.bot.send_message(j.uid, f"📚 Плейлист: {len(jobs)} видео добавлено в очередь.")
                    return
                await progress.start()
                await progress.advance("download")
                source_url = items[0] if len(items) == 1 else j.url
                source, media_title = await asyncio.to_thread(download, source_url, work, register)
            else:
                await progress.start()
                source = j.source
                media_title = "video"
            if not source or not source.exists():
                raise RuntimeError("Исходный файл не найден")
            if j.generation != self.gen.get(j.uid, 0):
                await progress.cancel()
                return
            await progress.advance("analyze")
            _, size = await asyncio.to_thread(ffprobe, source)
            hard_limit = MAX_SOURCE_DOWNLOAD_MB * 1024 * 1024
            if size > hard_limit:
                raise RuntimeError(f"Исходный файл превышает абсолютный лимит {MAX_SOURCE_DOWNLOAD_MB} МБ")
            fmt = user["format"]
            audio_only = fmt == "mp3"
            oversized = False
            if not audio_only:
                try:
                    oversized = size > MAX_SEND_MB * 1024 * 1024
                except Exception:
                    oversized = False
            wm = await db.aget_user_watermark(j.uid)
            if not audio_only:
                await progress.advance("process")
                result = await asyncio.to_thread(process_media, source, work, wm, audio_only=False, compress=oversized, register=register)
            else:
                await progress.advance("process")
                result = await asyncio.to_thread(process_media, source, work, wm, audio_only=True, compress=False, register=register)
            if j.generation != self.gen.get(j.uid, 0):
                await progress.cancel()
                return
            if result.stat().st_size > MAX_SEND_MB * 1024 * 1024:
                raise RuntimeError(f"Результат превышает лимит отправки {MAX_SEND_MB} МБ")
            caption = await metadata(source, media_title)
            channels = await db.alist_channels(j.uid)
            if channels:
                await progress.advance("send")
                for ch in channels:
                    if not ch["enabled"]:
                        continue
                    try:
                        if audio_only or oversized:
                            cr = result if audio_only else source
                        else:
                            channel_wm = await db.aget_channel_watermark(ch["channel_id"], j.uid)
                            cr = await asyncio.to_thread(process_media, source, work, channel_wm, audio_only=False, compress=False, register=register)
                            cr_size = (await asyncio.to_thread(cr.stat)).st_size
                            if cr_size > MAX_SEND_MB * 1024 * 1024:
                                cr = await asyncio.to_thread(process_media, source, work, channel_wm, audio_only=False, compress=True, register=register)
                                if (await asyncio.to_thread(cr.stat)).st_size > MAX_SEND_MB * 1024 * 1024:
                                    raise RuntimeError(f"После сжатия файл для канала всё ещё превышает лимит отправки {MAX_SEND_MB} МБ")
                        if cr.suffix.lower() == ".mp3":
                            await self.bot.send_audio(ch["channel_id"], FSInputFile(cr, filename=safe_media_filename(media_title, cr.suffix or ".mp3")))
                        else:
                            await self.bot.send_video(ch["channel_id"], FSInputFile(cr, filename=safe_media_filename(media_title, cr.suffix or ".mp4")), caption=caption or None, supports_streaming=True)
                    except Exception as e:
                        logger.exception("Autopost failed uid=%s channel=%s", j.uid, ch.get("channel_id"))
                        safe = user_facing_error(e)
                        try:
                            await self.bot.send_message(j.uid, f'⚠️ Автопост в «{ch["title"]}» не выполнен: {safe}')
                        except Exception:
                            pass
            else:
                await progress.advance("send")
                await self._send_private(j.uid, result, caption, filename=safe_media_filename(media_title, result.suffix or ".mp4"))
            await progress.done()
        except asyncio.CancelledError:
            try:
                await progress.cancel()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.exception("Job failed for uid=%s", j.uid)
            safe = user_facing_error(e)
            try:
                await progress.fail()
            except Exception:
                pass
            try:
                await self.bot.send_message(j.uid, f"❌ {safe}")
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

    async def _send_private(self, uid: int, path: Path, caption: str, filename: str | None = None):
        name = filename or safe_media_filename(path.stem, path.suffix or ".mp4")
        if path.suffix.lower() == ".mp3":
            await self.bot.send_audio(uid, FSInputFile(path, filename=name), caption=caption or None)
        else:
            await self.bot.send_video(uid, FSInputFile(path, filename=name), caption=caption or None, supports_streaming=True)
        ad = await db.aget_setting("ad_text", "")
        button = await db.aget_setting("ad_button", "")
        url = await db.aget_setting("ad_url", "")
        if ad:
            rows = [[B(button, url=url)]] if button and url else []
            await self.bot.send_message(uid, ad, reply_markup=kb(rows) if rows else None)

    async def _cleaner(self):
        while True:
            try:
                await asyncio.sleep(3600)
                await asyncio.to_thread(cleanup_media, CLEANER_AGE_HOURS, self.active_paths())
                active_logos = await db.aactive_logo_paths()
                await asyncio.to_thread(cleanup_logos, CLEANER_AGE_HOURS * 7, active_logos)
                try:
                    removed = await db.acleanup_expired_opp_campaigns()
                    if removed:
                        logger.info("Cleaned %s expired OPP campaigns", removed)
                except Exception:
                    logger.exception("OPP campaign cleanup failed")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cleaner failed")

    async def shutdown(self):
        with self._proc_lock:
            all_procs = [(uid, list(procs)) for uid, procs in self.processes.items()]
        for uid, procs in all_procs:
            for p in procs:
                try:
                    if p.returncode is None:
                        p.terminate()
                except Exception:
                    pass
        for t in self.workers:
            t.cancel()
        if self.cleaner_task:
            self.cleaner_task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        if self.cleaner_task:
            await asyncio.gather(self.cleaner_task, return_exceptions=True)


@router.message(Command("start"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    await db.aensure_user(m.from_user.id)
    await m.answer("🎬 Media Hunter", reply_markup=menu(m.from_user.id))


@router.message(Command("premium"))
async def premium(m: Message):
    await m.answer("⭐ Premium", reply_markup=premium_menu())


@router.message(F.text == "📥 Скачать")
async def download_menu(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(S.wm)
    await m.answer("🔗 Пришлите ссылку на видео или плейлист.")


@router.message(S.wm, F.text)
async def geturl(m: Message, state: FSMContext, engine: Engine):
    try:
        await state.clear()
        await engine.add(m.from_user.id, url=m.text.strip())
        await m.answer("⏳ Ссылка добавлена в очередь.")
    except (RuntimeError, ValueError) as e:
        await m.answer(f"❌ {user_facing_error(e)}")


@router.callback_query(F.data == "upload")
async def upload_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await c.message.edit_text(f"📤 Отправьте видео до {MAX_USER_UPLOAD_MB} МБ.", reply_markup=kb([[B("◀️ Назад", "back")]]))


@router.message(StateFilter(None), F.video)
async def upload(m: Message, bot: Bot, engine: Engine):
    if m.video.file_size is not None and m.video.file_size > MAX_USER_UPLOAD_MB * 1024 * 1024:
        await m.answer(f"❌ Максимальный размер файла — {MAX_USER_UPLOAD_MB} МБ.")
        return
    missing, rows = await opp_check(bot, m.from_user.id, m.from_user.username)
    if missing:
        await m.answer("🔐 Сначала выполните обязательные подписки.", reply_markup=kb(rows))
        return
    try:
        await engine.ensure_can_enqueue(m.from_user.id)
    except RuntimeError as e:
        await m.answer(f"❌ {user_facing_error(e)}")
        return
    p = MEDIA_DIR / f"upload_{m.from_user.id}_{uuid.uuid4().hex}"
    p.mkdir(parents=True, exist_ok=True)
    dst = p / "upload.mp4"
    handed = False
    try:
        f = await asyncio.wait_for(bot.get_file(m.video.file_id), timeout=60)
        await asyncio.wait_for(bot.download_file(f.file_path, destination=dst), timeout=300)
        actual_size = dst.stat().st_size
        if actual_size > MAX_USER_UPLOAD_MB * 1024 * 1024:
            raise RuntimeError(f"Файл превышает абсолютный лимит {MAX_USER_UPLOAD_MB} МБ")
        await engine.add(m.from_user.id, source=dst)
        handed = True
        await m.answer("⏳ Видео принято в очередь.")
    except (RuntimeError, ValueError) as e:
        await m.answer(f"❌ {user_facing_error(e)}")
    except Exception as e:
        logger.exception("Upload failed for uid=%s", m.from_user.id)
        await m.answer(f"❌ {user_facing_error(e)}")
    finally:
        if not handed:
            await asyncio.to_thread(shutil.rmtree, p, ignore_errors=True)


@router.callback_query(F.data == "restart")
async def restart(c: CallbackQuery, engine: Engine, state: FSMContext):
    await state.clear()
    await engine.restart(c.from_user.id)
    await c.answer("Ваши задачи отменены")
    await c.message.edit_text("🔄 Только ваши задачи отменены. Очереди других пользователей не затронуты.", reply_markup=menu(c.from_user.id))


@router.callback_query(F.data == "channels")
async def channels(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [[B("➕ Добавить канал", "addch")]]
    for ch in await db.alist_channels(c.from_user.id):
        rows.append([B(f'{"🟢" if ch["enabled"] else "⚪"} {ch["title"] or ch["channel_id"]}', f'ch:{ch["channel_id"]}')])
    rows.append([B("◀️ Назад", "back")])
    await c.answer()
    await c.message.edit_text("📺 Каналы (максимум 3):", reply_markup=kb(rows))


@router.callback_query(F.data == "addch")
async def addch(c: CallbackQuery, state: FSMContext):
    if len(await db.alist_channels(c.from_user.id)) >= 3:
        await c.answer("Максимум 3", show_alert=True)
        return
    await state.set_state(S.channel)
    await c.answer()
    await c.message.edit_text("Пришлите @username или ID канала. Бот должен быть администратором канала.", reply_markup=kb([[B("◀️ Назад", "channels")]]))


@router.message(S.channel)
async def addch_value(m: Message, state: FSMContext, bot: Bot):
    try:
        text = (m.text or "").strip()
        if not text:
            await m.answer("❌ Пришлите @username или ID канала.")
            return
        chat = await bot.get_chat(text)
        me_member = await bot.get_chat_member(chat.id, bot.id)
        if me_member.status not in ("administrator", "creator"):
            raise RuntimeError("Сначала добавьте бота в администраторы канала.")
        await db.aadd_channel(m.from_user.id, chat.id, chat.title or str(chat.id))
        await state.clear()
        await m.answer("✅ Канал добавлен.", reply_markup=menu(m.from_user.id))
    except (TelegramBadRequest, TelegramForbiddenError):
        await m.answer("❌ Канал не найден или бот не имеет доступа. Добавьте бота в администраторы и попробуйте снова.")
    except ValueError as e:
        await m.answer(f"❌ {user_facing_error(e)}")
    except Exception:
        logger.exception("Failed to add channel for uid=%s", m.from_user.id)
        await m.answer("❌ Не удалось добавить канал.")


@router.callback_query(F.data.startswith("ch:"))
async def ch(c: CallbackQuery):
    try:
        cid = int(c.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await c.answer("Некорректный канал", show_alert=True)
        return
    row = next((x for x in await db.alist_channels(c.from_user.id) if x["channel_id"] == cid), None)
    if not row:
        await c.answer("Канал не найден", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text(f'📺 {row["title"]}\nАвтопост: {"🟢 включён" if row["enabled"] else "⚪ выключен"}', reply_markup=kb([[B("🔄 Автопост", f"toggle:{cid}"), B("💧 Водяной знак", f"cwmx:{cid}")], [B("🗑 Удалить", f"del:{cid}")], [B("◀️ Назад", "channels")]]))


@router.callback_query(F.data.startswith("toggle:"))
async def toggle(c: CallbackQuery):
    try:
        cid = int(c.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await c.answer("Некорректный канал", show_alert=True)
        return
    row = next((x for x in await db.alist_channels(c.from_user.id) if x["channel_id"] == cid), None)
    if not row:
        await c.answer("Канал не найден", show_alert=True)
        return
    await db.aset_channel_enabled(c.from_user.id, cid, not bool(row["enabled"]))
    await c.answer("Сохранено")
    await ch(c)


@router.callback_query(F.data.startswith("del:"))
async def dele(c: CallbackQuery, state: FSMContext):
    try:
        cid = int(c.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await c.answer("Некорректный канал", show_alert=True)
        return
    await db.aremove_channel(c.from_user.id, cid)
    await c.answer("Удалено")
    await channels(c, state)


@router.callback_query(F.data == "wm")
async def wm(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await c.message.edit_text("💧 Водяной знак пользователя:", reply_markup=kb([[B("📝 Текст", "wmtext")], [B("🖼 PNG", "wmlogo")], [B("◀️ Назад", "back")]]))


@router.callback_query(F.data.startswith("cwmx:"))
async def cwm(c: CallbackQuery, state: FSMContext):
    try:
        cid = int(c.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await c.answer("Некорректный канал", show_alert=True)
        return
    row = next((x for x in await db.alist_channels(c.from_user.id) if x["channel_id"] == cid), None)
    if not row:
        await c.answer("Канал не найден", show_alert=True)
        return
    await state.update_data(cid=cid)
    await c.answer()
    await c.message.edit_text("💧 Watermark этого канала:", reply_markup=kb([[B("📝 Текст", "cwmtext")], [B("🖼 PNG", "cwmlogo")], [B("◀️ Назад", "channels")]]))


@router.callback_query(F.data.in_({"wmlogo", "cwmlogo"}))
async def wmlogo(c: CallbackQuery, state: FSMContext):
    cid = None if c.data == "wmlogo" else (await state.get_data()).get("cid")
    if cid is not None:
        row = next((x for x in await db.alist_channels(c.from_user.id) if x["channel_id"] == cid), None)
        if not row:
            await c.answer("Канал не найден", show_alert=True)
            return
    await state.update_data(channel=cid)
    await state.set_state(S.logo)
    await c.answer()
    await c.message.edit_text(f"🖼Логотип не должен превышать {MAX_WATERMARK_MB} МБ", reply_markup=kb([[B("◀️ Назад", "wm" if cid is None else "channels")]]))


@router.message(S.logo, F.document)
async def logovalue(m: Message, bot: Bot, state: FSMContext):
    name = (m.document.file_name or "").lower()
    if not name.endswith(".png"):
        await m.answer("❌ Нужен PNG до 5 МБ.")
        return
    if m.document.file_size is not None and m.document.file_size > MAX_WATERMARK_MB * 1024 * 1024:
        await m.answer("❌ Нужен PNG до 5 МБ.")
        return
    p = LOGO_DIR / f"logo_{m.from_user.id}_{uuid.uuid4().hex}.png"
    try:
        f = await asyncio.wait_for(bot.get_file(m.document.file_id), timeout=60)
        await asyncio.wait_for(bot.download_file(f.file_path, destination=p), timeout=300)
        actual_size = p.stat().st_size
        if actual_size > MAX_WATERMARK_MB * 1024 * 1024:
            raise ValueError("PNG превышает максимальный размер 5 МБ.")
        ok, msg = await asyncio.to_thread(validate_logo, p)
        if not ok:
            p.unlink(missing_ok=True)
            await m.answer("❌ " + msg)
            return
        d = await state.get_data()
        cid = d.get("channel")
        if cid is not None:
            row = next((x for x in await db.alist_channels(m.from_user.id) if x["channel_id"] == cid), None)
            if not row:
                raise ValueError("Канал больше не подключён.")
        w = {"type": "image", "logo": str(p), "position": "br"}
        if cid:
            await db.aset_channel_watermark(cid, m.from_user.id, w)
        else:
            await db.aset_user_watermark(m.from_user.id, w)
        await state.clear()
        await m.answer("✅ PNG watermark сохранён.", reply_markup=menu(m.from_user.id))
    except ValueError as e:
        p.unlink(missing_ok=True)
        await m.answer(f"❌ {user_facing_error(e)}")
    except Exception as e:
        p.unlink(missing_ok=True)
        logger.exception("Logo upload failed for uid=%s", m.from_user.id)
        await m.answer(f"❌ {user_facing_error(e)}")


@router.callback_query(F.data == "admin")
async def admin(c: CallbackQuery, state: FSMContext):
    await state.clear()
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text("👑 Админ-панель", reply_markup=kb([[B("🔐 ОПП", "aopp")], [B("📊 Отчёты ОПП", "aopp_reports")], [B("⏱ Срок хранения ОПП", "aopp_retain")], [B("📣 Реклама", "aad")], [B("💎 Ссылка Stars", "astars")], [B("🔄 Обновить yt-dlp", "aytdlp")], [B("🔄 Перезапустить бота", "abot")], [B("◀️ Назад", "back")]]))

@router.callback_query(F.data == "aopp")
async def aopp(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    rows = [[B(f'ОПП {r["slot"]}: {"🟢" if r["enabled"] else "⚪"}', f'opp:{r["slot"]}')] for r in await db.aget_opp()]
    rows.append([B("◀️ Назад", "admin")])
    await c.answer()
    await c.message.edit_text("Три независимых ОПП:", reply_markup=kb(rows))

@router.callback_query(F.data.startswith("opp:"))
async def opp(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    try:
        slot = int(c.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await c.answer("Некорректный слот", show_alert=True)
        return
    if slot not in {1, 2, 3}:
        await c.answer("Некорректный слот", show_alert=True)
        return
    await state.update_data(slot=slot)
    await state.set_state(S.admin_opp)
    await c.answer()
    await c.message.edit_text("Отправьте:\n• Публичный: ВКЛ|Название|https://t.me/username\n• Закрытый: ВКЛ|Название|-100ID|https://t.me/+invite\n", reply_markup=kb([[B("◀️ Назад", "admin")]]))


@router.message(S.admin_opp)
async def oppvalue(m: Message, state: FSMContext, bot: Bot):
    try:
        slot = int((await state.get_data()).get("slot", 0))
        parts = (m.text or "").split("|", 3)
        if len(parts) not in (3, 4):
            raise ValueError("Неверный формат. Используйте ВКЛ|Название|URL или ВКЛ|Название|-100ID|URL")
        enabled = parts[0].strip().upper() == "ВКЛ"
        if not enabled and parts[0].strip().upper() != "ВЫКЛ":
            raise ValueError("Первое поле должно быть ВКЛ или ВЫКЛ")
        title = parts[1].strip()[:200]
        if len(parts) == 3:
            cid = None
            url = parts[2].strip()
        else:
            cid = int(parts[2].strip())
            url = parts[3].strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me") or parsed.username or parsed.password or parsed.port is not None or "\r" in url or "\n" in url:
            raise ValueError("Нужна ссылка https://t.me/... без учётных данных")
        if cid is not None:
            chat = await bot.get_chat(cid)
            me = await bot.get_chat_member(chat.id, bot.id)
            if me.status not in ("administrator", "creator"):
                raise ValueError("Бот должен быть администратором канала")
        await db.aset_opp(slot, enabled, title, cid, url)
        await state.clear()
        await m.answer("✅ ОПП сохранено", reply_markup=menu(m.from_user.id))
    except (TelegramBadRequest, TelegramForbiddenError):
        await m.answer("❌ Не удалось проверить канал")
    except (ValueError, TypeError) as e:
        await m.answer(f"❌ {user_facing_error(e)}")
    except Exception:
        logger.exception("Failed to save OPP for uid=%s", m.from_user.id)
        await m.answer("❌ Не удалось сохранить ОПП")


@router.callback_query(F.data == "aopp_reports")
async def aopp_reports(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    rows = await db.aget_opp_reports()
    if not rows:
        text = "📊 Отчётов пока нет."
    else:
        lines = ["📊 Последние отчёты ОПП:"]
        for r in rows:
            lines.append(f"• {r['slot']}: {r['title']} — {r['joined_at']}")
        text = "\n".join(lines)
    await c.answer()
    await c.message.edit_text(text, reply_markup=kb([[B("◀️ Назад", "admin")]]))

@router.callback_query(F.data == "aopp_retain")
async def aopp_retain(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(S.admin_opp)
    await c.answer()
    await c.message.edit_text("Укажите срок хранения отчётов в днях (например 30).", reply_markup=kb([[B("◀️ Назад", "admin")]]))

@router.message(S.admin_opp)
async def aopp_retain_value(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await state.clear()
        return
    try:
        days = int((m.text or "").strip())
        if not 1 <= days <= 3650:
            raise ValueError("Срок должен быть от 1 до 3650 дней")
        await db.aset_setting("opp_report_retention_days", str(days))
        await state.clear()
        await m.answer("✅ Срок хранения изменён", reply_markup=menu(m.from_user.id))
    except ValueError as e:
        await m.answer(f"❌ {user_facing_error(e)}")


@router.callback_query(F.data == "aad")
async def aad(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(S.admin_ad)
    await c.answer()
    await c.message.edit_text("Отправьте: ТЕКСТ|НАЗВАНИЕ КНОПКИ|URL\nили ВЫКЛ. Реклама публикуется только после видео в личном чате.")

@router.message(S.admin_ad)
async def advalue(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await state.clear()
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
        ad_text, ad_button, ad_url = (x.strip() for x in p)
        parsed = urlparse(ad_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or "\r" in ad_url or "\n" in ad_url:
            await m.answer("❌ Нужен корректный HTTP/HTTPS URL без учётных данных.")
            return
        await db.aset_setting("ad_text", ad_text[:500])
        await db.aset_setting("ad_button", ad_button[:100])
        await db.aset_setting("ad_url", ad_url[:2000])
    await state.clear()
    await m.answer("✅ Реклама сохранена.", reply_markup=menu(m.from_user.id))

@router.callback_query(F.data == "astars")
async def astars(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(S.admin_stars)
    await c.answer()
    await c.message.edit_text("Пришлите новую партнёрскую ссылку Stars.")

@router.message(S.admin_stars)
async def astarsvalue(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await state.clear()
        return
    raw = (m.text or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me") or parsed.username or parsed.password or parsed.port is not None or "\r" in raw or "\n" in raw:
        await m.answer("❌ Нужна ссылка https://t.me/... без учётных данных.")
        return
    await db.aset_setting("stars_link", raw[:2000])
    await state.clear()
    await m.answer("✅ Ссылка Stars изменена.", reply_markup=menu(m.from_user.id))

@router.callback_query(F.data == "aytdlp")
async def aytdlp(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text("🔄 yt-dlp закреплён на версии из requirements.txt. Для ручного обновления обновите пакет на сервере и перезапустите бота.", reply_markup=kb([[B("◀️ Назад", "admin")]]))

@router.callback_query(F.data == "abot")
async def abot(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer()
    await c.message.edit_text("Перезапустить бота?", reply_markup=kb([[B("✅ Подтвердить", "abot:yes"), B("❌ Отмена", "admin")]]))

@router.callback_query(F.data == "abot:yes")
async def abot_yes(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer("Бот перезапускается")
    asyncio.create_task(_exit_later())

async def _exit_later():
    await asyncio.sleep(1)
    if os.name == "nt":
        os._exit(0)
    os.kill(os.getpid(), signal.SIGTERM)

@router.message(Command("paysupport"))
async def paysupport(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("💳 По вопросам оплаты Premium напишите администратору.")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    await bot.get_me()
    def _signal_handler(sig):
        logger.info("Received signal %s, initiating graceful shutdown...", sig.name)
        asyncio.create_task(dp.stop_polling())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _signal_handler(s))
        except ValueError:
            pass
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
