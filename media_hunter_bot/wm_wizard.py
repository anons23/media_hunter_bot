"""Interactive Russian watermark setup via inline buttons."""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db
from .config import LOGO_DIR, MAX_WATERMARK_MB
from .processor import _is_valid_color, validate_logo

COLORS = [
    ("white", "⬜ Белый"), ("black", "⬛ Чёрный"), ("red", "🔴 Красный"),
    ("yellow", "🟡 Жёлтый"), ("orange", "🟠 Оранжевый"), ("green", "🟢 Зелёный"),
    ("blue", "🔵 Синий"), ("cyan", "🩵 Голубой"), ("pink", "🩷 Розовый"),
    ("purple", "🟣 Фиолетовый"), ("gold", "🥇 Золотой"), ("silver", "⚪ Серебристый"),
]
SIZES = [(18, "Мелкий"), (28, "Обычный"), (40, "Крупный"), (56, "Очень крупный"), (72, "Огромный")]
POSITIONS = [("tl", "↖ Верх слева"), ("tr", "↗ Верх справа"), ("c", "⏺ По центру"), ("bl", "↙ Низ слева"), ("br", "↘ Низ справа")]
OPACITIES = [(0.4, "Слабый (40%)"), (0.6, "Средний (60%)"), (0.8, "Заметный (80%)"), (1.0, "Яркий (100%)")]
FONTS = [("sans", "Обычный"), ("bold", "Жирный"), ("serif", "С засечками"), ("mono", "Моноширинный")]
LOGO_SIZES = [(10, "Очень маленький — 10%"), (20, "Маленький — 20%"), (30, "Средний — 30%"), (40, "Крупный — 40%"), (50, "Большой — 50%")]
LOGO_OPACITIES = OPACITIES
POS_RU, COLOR_RU, FONT_RU, LOGO_SIZE_RU = dict(POSITIONS), dict(COLORS), dict(FONTS), dict(LOGO_SIZES)

_MAIN_MENU_TEXT = {"upload": "📤 Загрузить видео", "premium": "⭐ Премиум", "restart": "🔄 Отменить мои задачи", "admin": "👑 Админка"}
_MAIN_MENU_INFO = {
    "download": "📥 <b>Скачать</b>\n\nПришлите ссылку на видео из YouTube, TikTok или Instagram. Бот скачает его, обработает и отправит вам готовый файл.",
    "upload": "📤 <b>Загрузить видео</b>\n\nОтправьте боту уже имеющийся видеофайл с телефона или компьютера. Бот обработает его так же, как видео по ссылке.",
    "channels": "📺 <b>Каналы</b>\n\nПодключайте свои Telegram-каналы для автоматической публикации обработанных видео. Для каждого канала можно отдельно включить автопост и настроить собственный водяной знак.",
    "wm": "💧 <b>Водяной знак</b>\n\nЭто ваш личный водяной знак для видео, которое бот отправляет вам. Он настраивается отдельно от водяного знака подключённых каналов.",
    "settings": "⚙️ <b>Настройки</b>\n\nВыберите, что получать после обработки: обычное видео или только аудио в формате MP3.",
    "premium": "⭐ <b>Премиум</b>\n\nЗдесь можно купить Премиум на выбранный срок. Премиум-задачи получают приоритет в очереди.",
    "restart": "🔄 <b>Отменить мои задачи</b>\n\nОтменяются только ваши текущие и ожидающие задачи. Задачи других пользователей не затрагиваются.",
    "admin": "👑 <b>Админка</b>\n\nРаздел управления ботом: ОПП, отчёты, реклама, Stars и служебные настройки.",
}

class _MainMenuInfoMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        info = _MAIN_MENU_INFO.get(event.data or "")
        if info and event.message:
            try:
                await event.message.answer(info, parse_mode="HTML")
            except Exception:
                pass
        result = await handler(event, data)
        if event.message and event.data == "wm":
            try:
                await event.message.edit_reply_markup(reply_markup=_kb([[_B("📝 Текст", "wmtext")], [_B("🖼 Логотип", "wmlogo")], [_B("◀️ Назад", "back")]]))
            except Exception:
                pass
        elif event.message and (event.data or "").startswith("cwm:"):
            try:
                cid = (event.data or "").split(":", 1)[1]
                await event.message.edit_reply_markup(reply_markup=_kb([[_B("🔄 Автопост", f"toggle:{cid}"), _B("💧 Водяной знак", f"cwm:{cid}")], [_B("🗑 Удалить", f"del:{cid}")], [_B("◀️ Назад", "channels")]]))
            except Exception:
                pass
        elif event.message and event.data == "upload":
            try:
                await event.message.edit_text("📤 Отправьте видео с вашего устройства.", reply_markup=_kb([[_B("◀️ Назад", "back")]]))
            except Exception:
                pass
        elif event.message and (event.data or "").startswith("ch:"):
            try:
                cid = int((event.data or "").split(":", 1)[1])
                row = next((x for x in await db.alist_channels(event.from_user.id) if x["channel_id"] == cid), None)
                if row:
                    await event.message.edit_reply_markup(reply_markup=_kb([[_B("🔄 Автопост", f"toggle:{cid}"), _B("💧 Водяной знак", f"cwm:{cid}")], [_B("🗑 Удалить", f"del:{cid}")], [_B("◀️ Назад", "channels")]]))
            except Exception:
                pass
        return result

class WmStates(StatesGroup):
    text = State()
class LogoStates(StatesGroup):
    upload = State()
    settings = State()

def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)
def _B(text, data=None, url=None):
    return InlineKeyboardButton(text=text, callback_data=data, url=url)
def _chunk(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]
def _friendly_menu(menu_fn, uid):
    original = menu_fn(uid)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_MAIN_MENU_TEXT.get(b.callback_data, b.text), callback_data=b.callback_data, url=b.url)
        for b in row] for row in original.inline_keyboard])

def _summary(data):
    text = data.get("wm_text") or "—"
    color, size = data.get("wm_color", "white"), data.get("wm_size", 28)
    pos, opacity, font = data.get("wm_position", "br"), data.get("wm_opacity", 0.8), data.get("wm_font", "sans")
    label = next((lab for s, lab in SIZES if s == size), str(size))
    return ("💧 <b>Ваш водяной знак</b>\n\n" f"📝 Текст: <code>{text}</code>\n" f"🎨 Цвет: {COLOR_RU.get(color, color)}\n" f"🔤 Шрифт: {FONT_RU.get(font, font)}\n" f"📏 Размер: {label}\n" f"📍 Позиция: {POS_RU.get(pos, pos)}\n" f"👁 Прозрачность: {int(float(opacity) * 100)}%\n\n" "Так надпись будет накладываться на видео.")

def _logo_summary(data):
    size, pos, opacity = int(data.get("logo_size", 20)), data.get("logo_position", "br"), float(data.get("logo_opacity", 0.8))
    return ("🖼 <b>Настройки логотипа</b>\n\n" f"📏 Размер: {LOGO_SIZE_RU.get(size, f'{size}%')}\n" f"📍 Позиция: {POS_RU.get(pos, pos)}\n" f"👁 Прозрачность: {int(opacity * 100)}%\n\n" "Настройки можно менять кнопками ниже.")

async def _save_watermark(uid, data):
    w = {"type": "text", "text": str(data.get("wm_text", ""))[:200], "position": data.get("wm_position", "br"), "size": int(data.get("wm_size", 28)), "color": data.get("wm_color", "white"), "opacity": float(data.get("wm_opacity", 0.8)), "font": data.get("wm_font", "sans")}
    if not _is_valid_color(w["color"]): w["color"] = "white"
    if w["position"] not in POS_RU: w["position"] = "br"
    if not 10 <= w["size"] <= 200: w["size"] = 28
    if not 0.05 <= w["opacity"] <= 1.0: w["opacity"] = 0.8
    cid = data.get("channel")
    if cid:
        row = next((x for x in await db.alist_channels(uid) if x["channel_id"] == cid), None)
        if not row: raise ValueError("Канал больше не подключён.")
        await db.aset_channel_watermark(cid, uid, w)
    else:
        await db.aset_user_watermark(uid, w)

def _probe_dimensions(path: Path):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)], capture_output=True, text=True, timeout=30)
    if p.returncode != 0: raise RuntimeError("Не удалось определить размер изображения.")
    try: w, h = map(int, p.stdout.strip().split("x", 1))
    except ValueError as exc: raise RuntimeError("Не удалось определить размер изображения.") from exc
    if w <= 0 or h <= 0: raise RuntimeError("Не удалось определить размер изображения.")
    return w, h

def _render_logo_for_video(source, logo, size_percent, opacity, work_dir):
    vw, vh = _probe_dimensions(source)
    lw, lh = _probe_dimensions(logo)
    pct = max(5, min(int(size_percent), 80)) / 100.0
    scale = min((vw * pct) / lw, (vh * pct) / lh)
    scale = max(scale, min(32 / lw, 32 / lh))
    tw, th = max(32, int(round(lw * scale))), max(32, int(round(lh * scale)))
    rendered = LOGO_DIR / f".render_{uuid.uuid4().hex}.png"
    vf = f"scale={tw}:{th}:flags=lanczos,format=rgba,colorchannelmixer=aa={max(0.05, min(float(opacity), 1.0)):.3f}"
    p = subprocess.run(["ffmpeg", "-y", "-i", str(logo), "-vf", vf, str(rendered)], capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not rendered.exists():
        rendered.unlink(missing_ok=True)
        raise RuntimeError("Не удалось подготовить логотип для видео.")
    return rendered

def _install_logo_processing_wrapper():
    try:
        from . import handlers as hm
        current = hm.process_media
        if getattr(current, "_media_hunter_logo_wrapper", False): return
        def wrapped(source, work_dir, watermark, audio_only, compress, register):
            if audio_only or watermark.get("type") != "image" or not watermark.get("logo"):
                return current(source, work_dir, watermark, audio_only, compress, register)
            logo = Path(str(watermark["logo"]))
            if not logo.exists(): return current(source, work_dir, watermark, audio_only, compress, register)
            rendered = _render_logo_for_video(source, logo, int(watermark.get("logo_size", 20)), float(watermark.get("logo_opacity", 0.8)), work_dir)
            try:
                adjusted = dict(watermark); adjusted["logo"] = str(rendered)
                return current(source, work_dir, adjusted, audio_only, compress, register)
            finally:
                rendered.unlink(missing_ok=True)
        wrapped._media_hunter_logo_wrapper = True
        hm.process_media = wrapped
    except Exception:
        pass

def register_wm_wizard(router: Router, menu_fn):
    base_menu_fn = menu_fn
    router.callback_query.middleware(_MainMenuInfoMiddleware())
    _install_logo_processing_wrapper()
    def friendly_main_menu(uid): return _friendly_menu(base_menu_fn, uid)
    try:
        from . import handlers as hm
        hm.menu = friendly_main_menu
    except Exception: pass

    @router.callback_query(F.data.in_({"wmtext", "cwmtext"}))
    async def wm_start_text(c, state):
        cid = None if c.data == "wmtext" else (await state.get_data()).get("cid")
        if cid is not None and not any(x["channel_id"] == cid for x in await db.alist_channels(c.from_user.id)):
            await c.answer("Канал не найден", show_alert=True); return
        await state.set_state(WmStates.text)
        await state.update_data(channel=cid, wm_text=None, wm_color="white", wm_size=28, wm_position="br", wm_opacity=0.8, wm_font="sans")
        await c.answer()
        await c.message.edit_text("📝 Введите текст водяного знака одним сообщением.\nНапример: <code>Мой канал</code>", reply_markup=_kb([[_B("◀️ Назад", "wm" if cid is None else "channels")]]), parse_mode="HTML")

    @router.message(WmStates.text)
    async def wm_got_text(m, state):
        if not m.text or not m.text.strip(): await m.answer("❌ Пришлите обычный текст (не файл)."); return
        await state.update_data(wm_text=m.text.strip()[:200]); await state.set_state(None)
        rows = [[_B(lab, f"wmcolor:{code}") for code, lab in pair] for pair in _chunk(COLORS, 2)] + [[_B("❌ Отмена", "wm_cancel")]]
        await m.answer(f"Текст: <b>{m.text.strip()[:200]}</b>\n\n🎨 Выберите цвет:", reply_markup=_kb(rows), parse_mode="HTML")

    @router.callback_query(F.data.startswith("wmcolor:"))
    async def wm_color(c, state):
        color = c.data.split(":", 1)[1]
        if color not in COLOR_RU: await c.answer("Некорректный цвет", show_alert=True); return
        data = await state.get_data()
        if not data.get("wm_text"): await c.answer("Сначала введите текст", show_alert=True); return
        await state.update_data(wm_color=color); await c.answer()
        await c.message.edit_text(f"Цвет: {COLOR_RU[color]}\n\n🔤 Выберите стиль шрифта:", reply_markup=_kb([[ _B(lab, f"wmfont:{code}")] for code, lab in FONTS] + [[_B("❌ Отмена", "wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmfont:"))
    async def wm_font(c, state):
        font = c.data.split(":", 1)[1]
        if font not in FONT_RU: await c.answer("Некорректный шрифт", show_alert=True); return
        await state.update_data(wm_font=font); await c.answer()
        await c.message.edit_text(f"Шрифт: {FONT_RU[font]}\n\n📏 Выберите размер:", reply_markup=_kb([[ _B(f"{lab} ({sz})", f"wmsize:{sz}")] for sz, lab in SIZES] + [[_B("❌ Отмена", "wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmsize:"))
    async def wm_size(c, state):
        try: size = int(c.data.split(":", 1)[1])
        except ValueError: await c.answer("Некорректный размер", show_alert=True); return
        await state.update_data(wm_size=size); await c.answer()
        await c.message.edit_text(f"Размер: {next(l for s,l in SIZES if s == size)}\n\n📍 Где показать надпись на видео?", reply_markup=_kb([[_B(lab, f"wmpos:{pos}")] for pos, lab in POSITIONS] + [[_B("❌ Отмена", "wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmpos:"))
    async def wm_pos(c, state):
        pos = c.data.split(":", 1)[1]; await state.update_data(wm_position=pos); await c.answer()
        await c.message.edit_text(f"Позиция: {POS_RU[pos]}\n\n👁 Насколько яркой сделать надпись?", reply_markup=_kb([[_B(lab, f"wmop:{op}")] for op, lab in OPACITIES] + [[_B("❌ Отмена", "wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmop:"))
    async def wm_opacity(c, state):
        opacity = float(c.data.split(":", 1)[1]); await state.update_data(wm_opacity=opacity); data = await state.get_data(); await c.answer()
        await c.message.edit_text(_summary(data), reply_markup=_kb([[_B("✅ Сохранить", "wm_save"), _B("❌ Отмена", "wm_cancel")]]), parse_mode="HTML")

    @router.callback_query(F.data == "wm_save")
    async def wm_save(c, state):
        data = await state.get_data()
        if not data.get("wm_text"): await c.answer("Нет текста для сохранения", show_alert=True); return
        try: await _save_watermark(c.from_user.id, data)
        except ValueError as e: await c.answer(str(e), show_alert=True); await state.clear(); return
        await state.clear(); await c.answer("Сохранено")
        await c.message.edit_text("✅ Водяной знак сохранён.\nОн будет на новых обработанных видео.", reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data == "wm_cancel")
    async def wm_cancel(c, state):
        await state.clear(); await c.answer("Отменено")
        await c.message.edit_text("Настройка водяного знака отменена.", reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data.in_({"wmlogo", "cwmlogo"}))
    async def logo_start(c, state):
        cid = None if c.data == "wmlogo" else (await state.get_data()).get("cid")
        if cid is not None and not any(x["channel_id"] == cid for x in await db.alist_channels(c.from_user.id)):
            await c.answer("Канал не найден", show_alert=True); return
        await state.set_state(LogoStates.upload)
        await state.update_data(channel=cid, logo_path=None, logo_size=20, logo_position="br", logo_opacity=0.8)
        await c.answer(); back = "wm" if cid is None else "channels"
        await c.message.edit_text(f"🖼 <b>Загрузка логотипа</b>\n\nОтправьте PNG-файл. Максимальный размер — {MAX_WATERMARK_MB} МБ.", reply_markup=_kb([[_B("◀️ Назад", back)]]), parse_mode="HTML")

    @router.message(LogoStates.upload, F.document)
    async def logo_upload(m, bot, state):
        name = (m.document.file_name or "").lower()
        if not name.endswith(".png"): await m.answer(f"❌ Нужен PNG-файл до {MAX_WATERMARK_MB} МБ."); return
        if m.document.file_size is not None and m.document.file_size > MAX_WATERMARK_MB * 1024 * 1024: await m.answer(f"❌ Нужен PNG-файл до {MAX_WATERMARK_MB} МБ."); return
        p = LOGO_DIR / f"logo_{m.from_user.id}_{uuid.uuid4().hex}.png"
        try:
            f = await asyncio.wait_for(bot.get_file(m.document.file_id), timeout=60)
            await asyncio.wait_for(bot.download_file(f.file_path, destination=p), timeout=300)
            if p.stat().st_size > MAX_WATERMARK_MB * 1024 * 1024: raise ValueError(f"PNG превышает максимальный размер {MAX_WATERMARK_MB} МБ.")
            ok, msg = await asyncio.to_thread(validate_logo, p)
            if not ok: p.unlink(missing_ok=True); await m.answer("❌ " + msg); return
            await state.update_data(logo_path=str(p)); await state.set_state(LogoStates.settings)
            data = await state.get_data(); await m.answer(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")
        except ValueError as e: p.unlink(missing_ok=True); await m.answer(f"❌ {e}")
        except Exception as e: p.unlink(missing_ok=True); await m.answer(f"❌ Не удалось загрузить логотип: {e}")

    def _logo_settings_keyboard():
        return _kb([[_B("📏 Размер", "logosize_menu"), _B("📍 Позиция", "logopos_menu")], [_B("👁 Прозрачность", "logoop_menu")], [_B("✅ Сохранить", "logo_save")], [_B("❌ Отмена", "logo_cancel")]])

    @router.callback_query(F.data == "logosize_menu")
    async def logo_size_menu(c, state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип", show_alert=True); return
        await c.answer(); await c.message.edit_text("📏 Выберите размер логотипа относительно видео:", reply_markup=_kb([[_B(label, f"logosize:{size}")] for size,label in LOGO_SIZES] + [[_B("◀️ Назад", "logo_settings")]]))

    @router.callback_query(F.data.startswith("logosize:"))
    async def logo_size(c, state):
        size = int(c.data.split(":", 1)[1]); await state.update_data(logo_size=size); data = await state.get_data(); await c.answer("Размер сохранён"); await c.message.edit_text(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")

    @router.callback_query(F.data == "logopos_menu")
    async def logo_pos_menu(c, state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип", show_alert=True); return
        await c.answer(); await c.message.edit_text("📍 Выберите положение логотипа:", reply_markup=_kb([[_B(label, f"logopos:{pos}")] for pos,label in POSITIONS] + [[_B("◀️ Назад", "logo_settings")]]))

    @router.callback_query(F.data.startswith("logopos:"))
    async def logo_pos(c, state):
        pos = c.data.split(":", 1)[1]; await state.update_data(logo_position=pos); data=await state.get_data(); await c.answer("Позиция сохранена"); await c.message.edit_text(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")

    @router.callback_query(F.data == "logoop_menu")
    async def logo_op_menu(c, state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип", show_alert=True); return
        await c.answer(); await c.message.edit_text("👁 Выберите прозрачность логотипа:", reply_markup=_kb([[_B(label, f"logoop:{op}")] for op,label in LOGO_OPACITIES] + [[_B("◀️ Назад", "logo_settings")]]))

    @router.callback_query(F.data.startswith("logoop:"))
    async def logo_opacity(c, state):
        opacity = float(c.data.split(":",1)[1]); await state.update_data(logo_opacity=opacity); data=await state.get_data(); await c.answer("Прозрачность сохранена"); await c.message.edit_text(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")

    @router.callback_query(F.data == "logo_settings")
    async def logo_settings(c, state):
        data=await state.get_data()
        if not data.get("logo_path"): await c.answer("Сначала загрузите логотип", show_alert=True); return
        await c.answer(); await c.message.edit_text(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")

    @router.callback_query(F.data == "logo_save")
    async def logo_save(c, state):
        data=await state.get_data(); logo=data.get("logo_path")
        if not logo: await c.answer("Сначала загрузите логотип", show_alert=True); return
        w={"type":"image","logo":str(logo),"position":data.get("logo_position","br"),"logo_size":int(data.get("logo_size",20)),"logo_opacity":float(data.get("logo_opacity",0.8))}; cid=data.get("channel")
        try:
            if cid is not None: await db.aset_channel_watermark(cid,c.from_user.id,w)
            else: await db.aset_user_watermark(c.from_user.id,w)
        except Exception as e: await c.answer(str(e), show_alert=True); return
        await state.clear(); await c.answer("Сохранено")
        await c.message.edit_text("✅ Логотип сохранён и будет применяться к новым видео.", reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data == "logo_cancel")
    async def logo_cancel(c, state):
        data=await state.get_data(); logo=data.get("logo_path")
        if logo: Path(str(logo)).unlink(missing_ok=True)
        await state.clear(); await c.answer("Отменено"); await c.message.edit_text("Настройка логотипа отменена.", reply_markup=friendly_main_menu(c.from_user.id))
