"""Interactive watermark setup with robust PNG/GIF logo uploads."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from pathlib import Path

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from . import db
from .config import LOGO_DIR, MAX_LOGO_GIF_MB, MAX_LOGO_GIF_SECONDS, MAX_WATERMARK_MB, WEBAPP_URL
from . import plate as plate_mod
from . import textmark
from .processor import _is_valid_color, validate_logo

logger = logging.getLogger(__name__)

COLORS = [("white", "⬜ Белый"), ("black", "⬛ Чёрный"), ("red", "🔴 Красный"), ("yellow", "🟡 Жёлтый"), ("orange", "🟠 Оранжевый"), ("green", "🟢 Зелёный"), ("blue", "🔵 Синий"), ("cyan", "🩵 Голубой"), ("pink", "🩷 Розовый"), ("purple", "🟣 Фиолетовый"), ("gold", "🥇 Золотой"), ("silver", "⚪ Серебристый")]
SIZES = [(18, "Мелкий"), (28, "Обычный"), (40, "Крупный"), (56, "Очень крупный"), (72, "Огромный")]
POSITIONS = [("tl", "↖ Верх слева"), ("tr", "↗ Верх справа"), ("c", "⏺ По центру"), ("bl", "↙ Низ слева"), ("br", "↘ Низ справа")]
OPACITIES = [(0.4, "Слабый (40%)"), (0.6, "Средний (60%)"), (0.8, "Заметный (80%)"), (1.0, "Яркий (100%)")]
FONTS = [("sans", "Обычный"), ("bold", "Жирный"), ("serif", "С засечками"), ("mono", "Моноширинный")]
LOGO_SIZES = [(10, "Очень маленький — 10%"), (20, "Маленький — 20%"), (30, "Средний — 30%"), (40, "Крупный — 40%"), (50, "Большой — 50%")]
LOGO_OPACITIES = OPACITIES
POS_RU, COLOR_RU, FONT_RU, LOGO_SIZE_RU = dict(POSITIONS), dict(COLORS), dict(FONTS), dict(LOGO_SIZES)

class _MainMenuInfoMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        return await handler(event, data)

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
    return [items[i:i+n] for i in range(0, len(items), n)]

def _friendly_menu(menu_fn, uid):
    original = menu_fn(uid)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=b.text, callback_data=b.callback_data, url=b.url) for b in row] for row in original.inline_keyboard])

def _summary(data):
    text, color, size = data.get("wm_text") or "—", data.get("wm_color", "white"), data.get("wm_size", 28)
    pos, opacity, font = data.get("wm_position", "br"), data.get("wm_opacity", 0.8), data.get("wm_font", "sans")
    label = next((lab for s, lab in SIZES if s == size), str(size))
    return ("💧 <b>Ваш водяной знак</b>\n\n" f"📝 Текст: <code>{text}</code>\n" f"🎨 Цвет: {COLOR_RU.get(color, color)}\n" f"🔤 Шрифт: {FONT_RU.get(font, font)}\n" f"📏 Размер: {label}\n" f"📍 Позиция: {POS_RU.get(pos, pos)}\n" f"👁 Прозрачность: {int(float(opacity)*100)}%\n\nТак надпись будет накладываться на видео.")

def _logo_summary(data):
    size, pos, opacity = int(data.get("logo_size", 20)), data.get("logo_position", "br"), float(data.get("logo_opacity", 0.8))
    fmt = str(data.get("logo_format", "PNG")).upper()
    return ("🖼 <b>Настройки логотипа</b>\n\n" f"📦 Формат: {fmt}\n" f"📏 Размер: {LOGO_SIZE_RU.get(size, f'{size}%')}\n" f"📍 Позиция: {POS_RU.get(pos, pos)}\n" f"👁 Прозрачность: {int(opacity*100)}%\n\nНастройки можно менять кнопками ниже.")

async def _save_text(uid, data):
    w = {"type":"text","text":str(data.get("wm_text", ""))[:200],"position":data.get("wm_position","br"),"size":int(data.get("wm_size",28)),"color":data.get("wm_color","white"),"opacity":float(data.get("wm_opacity",0.8)),"font":data.get("wm_font","sans")}
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

def _safe_logo_path(raw) -> Path:
    root = LOGO_DIR.resolve(); path = Path(str(raw)).resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError("Некорректный путь логотипа.") from exc
    if not path.exists() or not path.is_file(): raise ValueError("Файл логотипа больше недоступен.")
    return path

def _convert_photo_to_png(source: Path, target: Path) -> None:
    proc = subprocess.run(["ffmpeg","-y","-i",str(source),"-frames:v","1","-vf","format=rgba",str(target)],capture_output=True,text=True,timeout=120)
    if proc.returncode != 0 or not target.exists() or target.stat().st_size <= 0: raise RuntimeError("Не удалось подготовить изображение логотипа.")

def _gif_seconds(path: Path) -> float:
    proc = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(path)],capture_output=True,text=True,timeout=30)
    try: return float((proc.stdout or "0").strip() or 0)
    except ValueError: return 0.0

def plate_editor_keyboard(channel_id, back: str):
    """Mini App button (when configured) + back."""
    from .webapp import editor_url
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="🎛 Настроить плашку", web_app=WebAppInfo(url=editor_url(channel_id)))])
    rows.append([_B("◀️ Назад", back)])
    return _kb(rows)

async def _store_plate(uid, channel_id, logo: Path) -> dict:
    """Save a freshly uploaded plate, keeping placement/timing of the old one."""
    old = await (db.aget_channel_watermark(channel_id, uid) if channel_id else asyncio.to_thread(db.get_user_watermark, uid))
    keep = plate_mod.normalize(old) if isinstance(old, dict) and old.get("type") == "image" and "x" in old else None
    p = keep or {"x": 0.5, "y": 0.9, "w": 0.5, "opacity": 1.0, "timing": {"mode": "all", "start": 0, "duration": None}, "fade": True}
    w = {"type":"image","logo":str(logo),"x":p["x"],"y":p["y"],"w":p["w"],"logo_opacity":p["opacity"],"timing":p["timing"],"fade":p["fade"]}
    if channel_id:
        if not any(x["channel_id"] == channel_id for x in await db.alist_channels(uid)): raise ValueError("Канал больше не подключён.")
        await db.aset_channel_watermark(channel_id, uid, w)
    else:
        await db.aset_user_watermark(uid, w)
    return w

def text_editor_keyboard(channel_id, back: str):
    from .webapp import editor_url
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text="🎛 Настроить надпись", web_app=WebAppInfo(url=editor_url(channel_id, "text")))])
    rows.append([_B("◀️ Назад", back)])
    return _kb(rows)

async def _store_text(uid, channel_id, text: str) -> dict:
    """Save a new text watermark, keeping the style of the previous one."""
    old = await (db.aget_channel_watermark(channel_id, uid) if channel_id else asyncio.to_thread(db.get_user_watermark, uid))
    base = textmark.normalize(old) if textmark.is_new_format(old) else textmark.normalize({"type": "text", "x": 0.5, "y": 0.92, "style": "shadow"})
    w = textmark.to_watermark({**base, "text": text})
    if channel_id:
        if not any(x["channel_id"] == channel_id for x in await db.alist_channels(uid)): raise ValueError("Канал больше не подключён.")
        await db.aset_channel_watermark(channel_id, uid, w)
    else:
        await db.aset_user_watermark(uid, w)
    return w

_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")


def _sniff_image(path: Path) -> str | None:
    """'.png' / '.gif' by file signature, None for anything else."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def _document_logo_ext(doc, uid) -> str:
    """Expected extension of a logo sent as a file (name OR mime type).

    Phones often send files without an extension or with a generic name, so the
    MIME type counts too. The bytes are checked again after download.
    """
    name = (getattr(doc, "file_name", None) or "").lower()
    mime = (getattr(doc, "mime_type", None) or "").lower()
    suffix = Path(name).suffix
    logger.info("LOGO_DOCUMENT uid=%s ext=%s mime=%s size=%s", uid, suffix or "-", mime or "-", getattr(doc, "file_size", None))
    if suffix == ".png" or mime == "image/png":
        return ".png"
    if suffix == ".gif" or mime == "image/gif":
        return ".gif"
    if suffix in _VIDEO_EXTS or mime.startswith("video"):
        raise ValueError("Это видео, а не GIF. Нужен файл .gif или .png — анимацию в формате MP4 бот как логотип не принимает.")
    if not suffix and not mime:
        # Unknown: let the signature check after download decide.
        return ".gif"
    what = suffix.lstrip(".").upper() or "этот формат"
    raise ValueError(f"Нужен PNG или GIF-файл, а пришёл {what}.")


async def _download_logo_message(message: Message, bot) -> tuple[Path,str]:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    uid = message.from_user.id if message.from_user else 0; token = uuid.uuid4().hex
    kind = "photo"
    if message.photo:
        file_id, ext, fmt, raw = message.photo[-1].file_id, ".jpg", "PNG", LOGO_DIR/f".upload_{uid}_{token}.jpg"
    elif message.document:
        ext = _document_logo_ext(message.document, uid)
        file_id, fmt, raw = message.document.file_id, ext[1:].upper(), LOGO_DIR/f".upload_{uid}_{token}{ext}"
        kind = "document"
    elif message.animation:
        name = (message.animation.file_name or "").lower()
        if not name.endswith(".gif"): raise ValueError("Telegram превратил GIF в видео без прозрачности. Отправьте GIF как файл: 📎 → Файл.")
        file_id, ext, fmt, raw = message.animation.file_id, ".gif", "GIF", LOGO_DIR/f".upload_{uid}_{token}.gif"
        kind = "animation"
    else:
        raise ValueError("Отправьте PNG, GIF или изображение из галереи.")
    telegram_size = message.document.file_size if message.document else message.animation.file_size if message.animation else None
    max_mb = MAX_LOGO_GIF_MB if ext == ".gif" else MAX_WATERMARK_MB
    if telegram_size is not None and telegram_size > max_mb*1024*1024: raise ValueError(f"Файл слишком большой. Максимум {max_mb} МБ для {'GIF' if ext == '.gif' else 'картинки'}.")
    logger.info("LOGO_RECEIVE uid=%s kind=%s format=%s",uid,kind,fmt)
    try:
        info = await asyncio.wait_for(bot.get_file(file_id), timeout=60)
        await asyncio.wait_for(bot.download_file(info.file_path, destination=raw), timeout=300)
        if raw.stat().st_size > max_mb*1024*1024: raise ValueError(f"Файл слишком большой. Максимум {max_mb} МБ.")
        if message.photo:
            final = LOGO_DIR/f"logo_{uid}_{token}.png"
            await asyncio.to_thread(_convert_photo_to_png, raw, final); raw.unlink(missing_ok=True)
        else:
            # Trust the bytes, not the file name: a GIF named "logo" or a
            # PNG named ".gif" must still work; an MP4 named ".gif" must not.
            real = _sniff_image(raw)
            if real is None:
                raise ValueError("Файл не похож на PNG или GIF. Пришлите настоящий PNG или GIF.")
            ext = real
            max_mb = MAX_LOGO_GIF_MB if ext == ".gif" else MAX_WATERMARK_MB
            if raw.stat().st_size > max_mb*1024*1024: raise ValueError(f"Файл слишком большой. Максимум {max_mb} МБ.")
            final = LOGO_DIR/f"logo_{uid}_{token}{ext}"; raw.rename(final)
        ok,msg = await asyncio.to_thread(validate_logo, final, max_mb)
        if not ok: final.unlink(missing_ok=True); raise ValueError(msg)
        if final.suffix.lower() == ".gif":
            seconds = await asyncio.to_thread(_gif_seconds, final)
            if seconds > MAX_LOGO_GIF_SECONDS:
                final.unlink(missing_ok=True)
                raise ValueError(f"GIF слишком длинный: {seconds:.0f} с. Максимум {MAX_LOGO_GIF_SECONDS:.0f} с.")
        logger.info("LOGO_VALIDATED uid=%s path=%s format=%s",uid,final.name,final.suffix[1:].upper())
        return final, final.suffix[1:].upper()
    except Exception:
        raw.unlink(missing_ok=True); raise

def _logo_settings_keyboard():
    return _kb([[_B("📏 Размер","logosize_menu"),_B("📍 Позиция","logopos_menu")],[_B("👁 Прозрачность","logoop_menu")],[_B("✅ Сохранить","logo_save"),_B("❌ Отмена","logo_cancel")]])

def register_wm_wizard(router: Router, menu_fn):
    base_menu_fn = menu_fn
    router.callback_query.middleware(_MainMenuInfoMiddleware())
    friendly_main_menu = lambda uid: _friendly_menu(base_menu_fn, uid)
    try:
        from . import handlers as hm; hm.menu = friendly_main_menu
    except Exception: pass

    @router.callback_query(F.data.in_({"wmtext","cwmtext"}))
    async def wm_start_text(c,state):
        cid = None if c.data == "wmtext" else (await state.get_data()).get("cid")
        if cid is not None and not any(x["channel_id"] == cid for x in await db.alist_channels(c.from_user.id)): await c.answer("Канал не найден",show_alert=True); return
        await state.set_state(WmStates.text); await state.update_data(channel=cid,wm_text=None,wm_color="white",wm_size=28,wm_position="br",wm_opacity=0.8,wm_font="sans"); await c.answer()
        await c.message.edit_text("📝 Введите текст водяного знака одним сообщением.\nНапример: <code>Мой канал</code>",reply_markup=_kb([[_B("◀️ Назад","wm" if cid is None else "channels")]]),parse_mode="HTML")

    @router.message(WmStates.text)
    async def wm_got_text(m,state):
        if not m.text or not m.text.strip(): await m.answer("❌ Пришлите обычный текст (не файл)."); return
        text=m.text.strip()[:200]
        if WEBAPP_URL:
            cleaned=textmark.clean_text(text)
            if not cleaned: await m.answer("❌ В тексте нет символов, которые можно вывести на видео (эмодзи не поддерживаются)."); return
            data=await state.get_data(); cid=data.get("channel")
            try: w=await _store_text(m.from_user.id, cid, cleaned)
            except ValueError as e: await state.clear(); await m.answer(f"❌ {e}"); return
            await state.clear()
            await m.answer(f"✅ <b>Надпись сохранена</b>\n\nТеперь откройте редактор: перетащите текст на нужное место, выберите шрифт, цвет и эффект.\n\nСейчас: {textmark.describe(textmark.normalize(w))}.",reply_markup=text_editor_keyboard(cid,"wm" if cid is None else "channels"),parse_mode="HTML")
            return
        await state.update_data(wm_text=text); await state.set_state(None)
        rows=[[ _B(lab,f"wmcolor:{code}") for code,lab in pair] for pair in _chunk(COLORS,2)]+[[_B("❌ Отмена","wm_cancel")]]
        await m.answer(f"Текст: <b>{text}</b>\n\n🎨 Выберите цвет:",reply_markup=_kb(rows),parse_mode="HTML")

    @router.callback_query(F.data.startswith("wmcolor:"))
    async def wm_color(c,state):
        color=c.data.split(":",1)[1]
        if color not in COLOR_RU: await c.answer("Некорректный цвет",show_alert=True); return
        if not (await state.get_data()).get("wm_text"): await c.answer("Сначала введите текст",show_alert=True); return
        await state.update_data(wm_color=color); await c.answer(); await c.message.edit_text(f"Цвет: {COLOR_RU[color]}\n\n🔤 Выберите стиль шрифта:",reply_markup=_kb([[_B(lab,f"wmfont:{code}")] for code,lab in FONTS]+[[_B("❌ Отмена","wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmfont:"))
    async def wm_font(c,state):
        font=c.data.split(":",1)[1]
        if font not in FONT_RU: await c.answer("Некорректный шрифт",show_alert=True); return
        await state.update_data(wm_font=font); await c.answer(); await c.message.edit_text(f"Шрифт: {FONT_RU[font]}\n\n📏 Выберите размер:",reply_markup=_kb([[_B(f"{lab} ({sz})",f"wmsize:{sz}")] for sz,lab in SIZES]+[[_B("❌ Отмена","wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmsize:"))
    async def wm_size(c,state):
        try: size=int(c.data.split(":",1)[1])
        except ValueError: await c.answer("Некорректный размер",show_alert=True); return
        if size not in dict(SIZES): await c.answer("Некорректный размер",show_alert=True); return
        await state.update_data(wm_size=size); await c.answer(); await c.message.edit_text(f"Размер: {next(l for s,l in SIZES if s==size)}\n\n📍 Где показать надпись на видео?",reply_markup=_kb([[_B(lab,f"wmpos:{pos}")] for pos,lab in POSITIONS]+[[_B("❌ Отмена","wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmpos:"))
    async def wm_pos(c,state):
        pos=c.data.split(":",1)[1]
        if pos not in POS_RU: await c.answer("Некорректная позиция",show_alert=True); return
        await state.update_data(wm_position=pos); await c.answer(); await c.message.edit_text(f"Позиция: {POS_RU[pos]}\n\n👁 Насколько яркой сделать надпись?",reply_markup=_kb([[_B(lab,f"wmop:{op}")] for op,lab in OPACITIES]+[[_B("❌ Отмена","wm_cancel")]]))

    @router.callback_query(F.data.startswith("wmop:"))
    async def wm_opacity(c,state):
        try: opacity=float(c.data.split(":",1)[1])
        except ValueError: await c.answer("Некорректное значение",show_alert=True); return
        if opacity not in dict(OPACITIES): await c.answer("Некорректное значение",show_alert=True); return
        await state.update_data(wm_opacity=opacity); data=await state.get_data(); await c.answer(); await c.message.edit_text(_summary(data),reply_markup=_kb([[_B("✅ Сохранить","wm_save"),_B("❌ Отмена","wm_cancel")]]),parse_mode="HTML")

    @router.callback_query(F.data == "wm_save")
    async def wm_save(c,state):
        data=await state.get_data()
        if not data.get("wm_text"): await c.answer("Нет текста для сохранения",show_alert=True); return
        try: await _save_text(c.from_user.id,data)
        except ValueError as e: await c.answer(str(e),show_alert=True); await state.clear(); return
        await state.clear(); await c.answer("Сохранено"); await c.message.edit_text("✅ Водяной знак сохранён.\nОн будет на новых обработанных видео.",reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data == "wm_cancel")
    async def wm_cancel(c,state):
        await state.clear(); await c.answer("Отменено"); await c.message.edit_text("Настройка водяного знака отменена.",reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data.in_({"wmlogo","cwmlogo"}))
    async def logo_start(c,state):
        current=await state.get_data(); cid=None if c.data=="wmlogo" else current.get("cid")
        if cid is not None and not any(x["channel_id"]==cid for x in await db.alist_channels(c.from_user.id)): await c.answer("Канал не найден",show_alert=True); return
        await state.set_state(LogoStates.upload); await state.update_data(channel=cid,logo_path=None,logo_format=None,logo_size=20,logo_position="br",logo_opacity=0.8); await c.answer()
        await c.message.edit_text(f"🖼 <b>Загрузка логотипа</b>\n\nОтправьте <b>PNG</b>, <b>GIF</b> или обычное изображение из галереи.\nМаксимальный размер — {MAX_WATERMARK_MB} МБ.\n\nGIF сохранит анимацию логотипа.",reply_markup=_kb([[_B("◀️ Назад","wm" if cid is None else "channels")]]),parse_mode="HTML")

    @router.message(LogoStates.upload, F.photo | F.document | F.animation)
    async def logo_upload(m,bot,state):
        try:
            logo,fmt=await _download_logo_message(m,bot)
            if WEBAPP_URL:
                # Mini App flow: one plate per scope, a new upload replaces the old one.
                data=await state.get_data(); cid=data.get("channel")
                w=await _store_plate(m.from_user.id, cid, logo); await state.clear()
                logger.info("PLATE_UPLOADED uid=%s channel=%s format=%s",m.from_user.id,cid,fmt)
                await m.answer(f"✅ <b>Плашка загружена</b> ({fmt})\n\nТеперь откройте редактор: перетащите её на нужное место, растяните и задайте, когда она появляется и исчезает.\n\nСейчас: {plate_mod.describe(plate_mod.normalize(w))}.",reply_markup=plate_editor_keyboard(cid,"wm" if cid is None else "channels"),parse_mode="HTML")
                return
            await state.update_data(logo_path=str(logo),logo_format=fmt); await state.set_state(LogoStates.settings); data=await state.get_data(); logger.info("LOGO_SETTINGS uid=%s format=%s",m.from_user.id if m.from_user else None,fmt); await m.answer(_logo_summary(data),reply_markup=_logo_settings_keyboard(),parse_mode="HTML")
        except ValueError as e: await m.answer(f"❌ {e}")
        except Exception:
            logger.exception("LOGO_UPLOAD_FAILED uid=%s",m.from_user.id if m.from_user else None); await m.answer("❌ Не удалось загрузить логотип. Попробуйте PNG или GIF ещё раз.")

    @router.callback_query(F.data == "logosize_menu")
    async def logo_size_menu(c,state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип",show_alert=True); return
        await c.answer(); await c.message.edit_text("📏 Выберите размер логотипа относительно видео:",reply_markup=_kb([[_B(label,f"logosize:{size}")] for size,label in LOGO_SIZES]+[[_B("◀️ Назад","logo_settings")]]))

    @router.callback_query(F.data.startswith("logosize:"))
    async def logo_size(c,state):
        try: size=int(c.data.split(":",1)[1])
        except ValueError: await c.answer("Некорректный размер",show_alert=True); return
        if size not in LOGO_SIZE_RU: await c.answer("Некорректный размер",show_alert=True); return
        await state.update_data(logo_size=size); data=await state.get_data(); await c.answer("Размер сохранён"); await c.message.edit_text(_logo_summary(data),reply_markup=_logo_settings_keyboard(),parse_mode="HTML")

    @router.callback_query(F.data == "logopos_menu")
    async def logo_pos_menu(c,state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип",show_alert=True); return
        await c.answer(); await c.message.edit_text("📍 Выберите положение логотипа:",reply_markup=_kb([[_B(label,f"logopos:{pos}")] for pos,label in POSITIONS]+[[_B("◀️ Назад","logo_settings")]]))

    @router.callback_query(F.data.startswith("logopos:"))
    async def logo_pos(c,state):
        pos=c.data.split(":",1)[1]
        if pos not in POS_RU: await c.answer("Некорректная позиция",show_alert=True); return
        await state.update_data(logo_position=pos); data=await state.get_data(); await c.answer("Позиция сохранена"); await c.message.edit_text(_logo_summary(data),reply_markup=_logo_settings_keyboard(),parse_mode="HTML")

    @router.callback_query(F.data == "logoop_menu")
    async def logo_op_menu(c,state):
        if not (await state.get_data()).get("logo_path"): await c.answer("Сначала загрузите логотип",show_alert=True); return
        await c.answer(); await c.message.edit_text("👁 Выберите прозрачность логотипа:",reply_markup=_kb([[_B(label,f"logoop:{op}")] for op,label in LOGO_OPACITIES]+[[_B("◀️ Назад","logo_settings")]]))

    @router.callback_query(F.data.startswith("logoop:"))
    async def logo_opacity(c,state):
        try: opacity=float(c.data.split(":",1)[1])
        except ValueError: await c.answer("Некорректное значение",show_alert=True); return
        if opacity not in dict(LOGO_OPACITIES): await c.answer("Некорректное значение",show_alert=True); return
        await state.update_data(logo_opacity=opacity); data=await state.get_data(); await c.answer("Прозрачность сохранена"); await c.message.edit_text(_logo_summary(data),reply_markup=_logo_settings_keyboard(),parse_mode="HTML")

    @router.callback_query(F.data == "logo_settings")
    async def logo_settings(c,state):
        data=await state.get_data()
        if not data.get("logo_path"): await c.answer("Сначала загрузите логотип",show_alert=True); return
        await c.answer(); await c.message.edit_text(_logo_summary(data),reply_markup=_logo_settings_keyboard(),parse_mode="HTML")

    @router.callback_query(F.data == "logo_save")
    async def logo_save(c,state):
        data=await state.get_data(); logo=data.get("logo_path")
        if not logo: await c.answer("Сначала загрузите логотип",show_alert=True); return
        logo=_safe_logo_path(logo); w={"type":"image","logo":str(logo),"position":data.get("logo_position","br"),"logo_size":int(data.get("logo_size",20)),"logo_opacity":float(data.get("logo_opacity",0.8))}; cid=data.get("channel")
        if cid is not None:
            if not any(x["channel_id"]==cid for x in await db.alist_channels(c.from_user.id)): await c.answer("Канал больше не подключён",show_alert=True); return
            await db.aset_channel_watermark(cid,c.from_user.id,w)
        else: await db.aset_user_watermark(c.from_user.id,w)
        logger.info("LOGO_SAVED uid=%s path=%s format=%s size=%s pos=%s opacity=%s",c.from_user.id,logo.name,logo.suffix.lower(),w["logo_size"],w["position"],w["logo_opacity"])
        await state.clear(); await c.answer("Сохранено"); await c.message.edit_text("✅ Логотип сохранён.\nОн будет применяться к новым видео.",reply_markup=friendly_main_menu(c.from_user.id))

    @router.callback_query(F.data == "logo_cancel")
    async def logo_cancel(c,state):
        data=await state.get_data(); logo=data.get("logo_path")
        if logo: Path(str(logo)).unlink(missing_ok=True)
        await state.clear(); await c.answer("Отменено"); await c.message.edit_text("Настройка логотипа отменена.",reply_markup=friendly_main_menu(c.from_user.id))
