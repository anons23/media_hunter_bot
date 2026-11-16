"""Small UI/runtime fixes layered on top of the existing handlers.

This module intentionally avoids rewriting handlers.py. It intercepts a few
callbacks before the legacy handlers so the user-facing watermark and
autopost controls have deterministic behaviour.
"""
from __future__ import annotations

import html
from pathlib import Path

from aiogram import BaseMiddleware, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import db
from .wm_wizard import WmStates


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _b(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def _channel_id_from_state(data: dict) -> int | None:
    value = data.get("channel")
    if value is None:
        value = data.get("cid")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _get_watermark(uid: int, channel_id: int | None):
    if channel_id is None:
        # The user's own watermark (the async getter is overridden in
        # __init__ to return the first channel's one).
        import asyncio
        return await asyncio.to_thread(db.get_user_watermark, uid)
    return await db.aget_channel_watermark(channel_id, uid)


async def _set_watermark(uid: int, channel_id: int | None, value: dict):
    if channel_id is None:
        await db.aset_user_watermark(uid, value)
    else:
        await db.aset_channel_watermark(channel_id, uid, value)


async def _edit_or_answer(c: CallbackQuery, text: str, markup):
    if c.message:
        try:
            await c.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    await c.answer(text[:180], show_alert=True)


def _scope_from_callback(c: CallbackQuery, data: dict) -> int | None:
    """wm* buttons = user's own watermark, cwm* = the channel opened via cwmx:<id>."""
    if not (c.data or "").startswith("cwm"):
        return None
    try:
        return int(data["cid"]) if data.get("cid") is not None else _channel_id_from_state(data)
    except (TypeError, ValueError):
        return None


async def _show_text_config(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _scope_from_callback(c, data)
    await state.update_data(channel=cid)
    watermark = await _get_watermark(c.from_user.id, cid)
    text = str(watermark.get("text") or "").strip() if watermark.get("type") == "text" else ""
    from .config import WEBAPP_URL
    editor_row = []
    if WEBAPP_URL:
        from aiogram.types import WebAppInfo
        from .webapp import editor_url
        editor_row = [[InlineKeyboardButton(text="🎛 Настроить надпись", web_app=WebAppInfo(url=editor_url(cid, "text")))]]
    if text:
        scope = "для этого канала" if cid is not None else "для ваших видео"
        await c.answer()
        await _edit_or_answer(
            c,
            "💧 <b>Текст водяного знака уже настроен</b>\n\n"
            f"📝 Сейчас {scope}: <code>{html.escape(text)}</code>\n\n"
            + ("Место, размер, шрифт и цвет меняются в редакторе. " if WEBAPP_URL else "")
            + "Можно изменить текст или удалить. После удаления видео будут без этого водяного знака.",
            _kb(editor_row + [
                [_b("✏️ Изменить текст", "wmtext_edit")],
                [_b("🗑 Удалить водяной знак", "wmtext_delete")],
                [_b("◀️ Назад", "wm" if cid is None else "channels")],
            ]),
        )
        return

    replaces = "\n\n⚠️ Сейчас у вас плашка — новая надпись заменит её." if watermark.get("type") == "image" else ""
    await c.answer()
    await _edit_or_answer(
        c,
        "📝 <b>Текстовый водяной знак</b>\n\nСейчас текст не настроен. Пришлите его одним сообщением"
        + (" или откройте редактор." if WEBAPP_URL else ".") + replaces,
        _kb(editor_row + [[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )
    await state.set_state(WmStates.text)
    await state.update_data(channel=cid, wm_text=None, wm_color="white", wm_size=28, wm_position="br", wm_opacity=0.8, wm_font="sans")


async def _start_text_edit(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    await state.set_state(WmStates.text)
    await state.update_data(channel=cid, wm_text=None, wm_color="white", wm_size=28, wm_position="br", wm_opacity=0.8, wm_font="sans")
    await c.answer()
    await _edit_or_answer(
        c,
        "✏️ <b>Изменение текста</b>\n\nПришлите новый текст водяного знака одним сообщением.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )


async def _delete_text(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    watermark = await _get_watermark(c.from_user.id, cid)
    if watermark.get("type") == "text":
        await _set_watermark(c.from_user.id, cid, {})
    await state.clear()
    await c.answer("Водяной знак удалён")
    await _edit_or_answer(
        c,
        "🗑 <b>Готово</b>\n\nТекстовый водяной знак удалён. Теперь видео можно обрабатывать без него.",
        _kb([[_b("💧 Водяной знак", "wm" if cid is None else f"cwmx:{cid}")], [_b("◀️ Назад", "back" if cid is None else "channels")]]),
    )


async def _show_logo_config(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # "wmlogo" is always the user's own watermark, "cwmlogo" the channel
    # opened via cwmx:<id>. Do not trust a stale "channel" key here.
    if c.data == "wmlogo":
        cid = None
    else:
        try:
            cid = int(data["cid"]) if data.get("cid") is not None else _channel_id_from_state(data)
        except (TypeError, ValueError):
            cid = None
    watermark = await _get_watermark(c.from_user.id, cid)
    logo = str(watermark.get("logo") or "").strip() if watermark.get("type") == "image" else ""
    exists = bool(logo and Path(logo).exists())
    if exists:
        # Remember the scope for the replace/delete buttons.
        await state.update_data(channel=cid)
        scope = "для этого канала" if cid is not None else "для ваших видео"
        from . import plate as plate_mod
        from .config import WEBAPP_URL
        rows = []
        if WEBAPP_URL:
            from aiogram.types import WebAppInfo
            from .webapp import editor_url
            rows.append([InlineKeyboardButton(text="🎛 Настроить плашку", web_app=WebAppInfo(url=editor_url(cid)))])
        rows += [
            [_b("🔄 Загрузить новую", "wmlogo_edit")],
            [_b("🗑 Удалить плашку", "wmlogo_delete")],
            [_b("◀️ Назад", "wm" if cid is None else "channels")],
        ]
        await c.answer()
        await _edit_or_answer(
            c,
            "🖼 <b>Плашка уже загружена</b>\n\n"
            f"Сейчас она сохранена {scope}: {html.escape(plate_mod.describe(plate_mod.normalize(watermark)))}.\n\n"
            "Место, размер и время показа меняются в редакторе. Новая загрузка заменит текущую плашку.",
            _kb(rows),
        )
        return

    # The bot must actually wait for the logo: without LogoStates.upload the
    # PNG/photo reaches no handler ("Update ... is not handled").
    await _enter_logo_upload(state, cid)
    await c.answer()
    await _edit_or_answer(
        c,
        "🖼 <b>Плашка</b>\n\nСейчас плашка не загружена. Отправьте картинку (PNG/JPG, до 5 МБ) или GIF-файл (до 10 МБ, до 15 с), чтобы добавить её на видео.\n\nGIF отправляйте как файл (📎 → Файл), иначе Telegram уберёт прозрачность.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )


async def _enter_logo_upload(state: FSMContext, cid: int | None) -> None:
    from .wm_wizard import LogoStates
    await state.set_state(LogoStates.upload)
    await state.update_data(
        channel=cid,
        logo_path=None,
        logo_format=None,
        logo_size=20,
        logo_position="br",
        logo_opacity=0.8,
    )


async def _start_logo_edit(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    await _enter_logo_upload(state, cid)
    await c.answer()
    await _edit_or_answer(
        c,
        "🖼 <b>Новый логотип</b>\n\nОтправьте PNG, GIF или фото из галереи.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )


async def _delete_logo(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    watermark = await _get_watermark(c.from_user.id, cid)
    if watermark.get("type") == "image":
        await _set_watermark(c.from_user.id, cid, {})
    await state.clear()
    await c.answer("Плашка удалена")
    await _edit_or_answer(
        c,
        "🗑 <b>Готово</b>\n\nПлашка удалена. Теперь видео будут без неё.",
        _kb([[_b("💧 Водяной знак", "wm" if cid is None else f"cwmx:{cid}")], [_b("◀️ Назад", "back" if cid is None else "channels")]]),
    )


async def _toggle_autopost(c: CallbackQuery):
    try:
        cid = int((c.data or "").split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        await c.answer("Некорректный канал", show_alert=True)
        return
    channels = await db.alist_channels(c.from_user.id)
    row = next((x for x in channels if int(x["channel_id"]) == cid), None)
    if not row:
        await c.answer("Канал больше не подключён", show_alert=True)
        return
    enabled = not bool(row["enabled"])
    await db.aset_channel_enabled(c.from_user.id, cid, enabled)
    status = "включён" if enabled else "выключен"
    await c.answer(f"Автопостинг {status}")
    await _edit_or_answer(
        c,
        f"📺 <b>{html.escape(str(row['title'] or 'Канал'))}</b>\n\n"
        f"🔄 Автопостинг: <b>{'ВКЛ' if enabled else 'ВЫКЛ'}</b>\n"
        "При включённом автопостинге обработанные видео будут отправляться в этот канал.",
        _kb([
            [_b("⏸ Выключить" if enabled else "▶️ Включить", f"toggle:{cid}")],
            [_b("💧 Водяной знак", f"cwmx:{cid}")],
            [_b("🗑 Удалить канал", f"del:{cid}")],
            [_b("◀️ Назад", "channels")],
        ]),
    )


class _UxCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        value = event.data or ""
        state = data.get("state")
        if value in {"wmtext", "cwmtext"}:
            await _show_text_config(event, state)
            return None
        if value == "wmtext_edit":
            await _start_text_edit(event, state)
            return None
        if value == "wmtext_delete":
            await _delete_text(event, state)
            return None
        if value in {"wmlogo", "cwmlogo"}:
            await _show_logo_config(event, state)
            return None
        if value == "wmlogo_edit":
            await _start_logo_edit(event, state)
            return None
        if value == "wmlogo_delete":
            await _delete_logo(event, state)
            return None
        if value.startswith("toggle:"):
            await _toggle_autopost(event)
            return None
        return await handler(event, data)


def patch_router(router):
    """Install the deterministic callback UX layer once."""
    if getattr(router, "_media_hunter_ux_patched", False):
        return
    router.callback_query.outer_middleware(_UxCallbackMiddleware())
    router._media_hunter_ux_patched = True
