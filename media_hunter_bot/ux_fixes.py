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
        return await db.aget_user_watermark(uid)
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


async def _show_text_config(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    watermark = await _get_watermark(c.from_user.id, cid)
    text = str(watermark.get("text") or "").strip() if watermark.get("type") == "text" else ""
    if text:
        scope = "для этого канала" if cid is not None else "для ваших видео"
        await c.answer()
        await _edit_or_answer(
            c,
            "💧 <b>Текст водяного знака уже настроен</b>\n\n"
            f"📝 Сейчас {scope}: <code>{html.escape(text)}</code>\n\n"
            "Можно изменить его или удалить. После удаления видео будут без этого водяного знака.",
            _kb([
                [_b("✏️ Изменить текст", "wmtext_edit")],
                [_b("🗑 Удалить водяной знак", "wmtext_delete")],
                [_b("◀️ Назад", "wm" if cid is None else "channels")],
            ]),
        )
        return

    await c.answer()
    await _edit_or_answer(
        c,
        "📝 <b>Текстовый водяной знак</b>\n\nСейчас текст не настроен. Пришлите его одним сообщением.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
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
    cid = _channel_id_from_state(data)
    watermark = await _get_watermark(c.from_user.id, cid)
    logo = str(watermark.get("logo") or "").strip() if watermark.get("type") == "image" else ""
    exists = bool(logo and Path(logo).exists())
    if exists:
        scope = "для этого канала" if cid is not None else "для ваших видео"
        await c.answer()
        await _edit_or_answer(
            c,
            "🖼 <b>Логотип уже настроен</b>\n\n"
            f"Сейчас логотип сохранён {scope}. Он будет добавляться к видео автоматически.\n\n"
            "Можно заменить логотип или удалить его. После удаления видео будут без логотипа.",
            _kb([
                [_b("🔄 Заменить логотип", "wmlogo_edit")],
                [_b("🗑 Удалить логотип", "wmlogo_delete")],
                [_b("◀️ Назад", "wm" if cid is None else "channels")],
            ]),
        )
        return

    await c.answer()
    await _edit_or_answer(
        c,
        "🖼 <b>Логотип</b>\n\nСейчас логотип не настроен. Отправьте PNG-файл, чтобы добавить его к видео.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )


async def _start_logo_edit(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    from .wm_wizard import LogoStates
    await state.set_state(LogoStates.upload)
    await state.update_data(channel=cid)
    await c.answer()
    await _edit_or_answer(
        c,
        "🖼 <b>Новый логотип</b>\n\nОтправьте PNG-файл логотипа.",
        _kb([[_b("◀️ Назад", "wm" if cid is None else "channels")]]),
    )


async def _delete_logo(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = _channel_id_from_state(data)
    watermark = await _get_watermark(c.from_user.id, cid)
    if watermark.get("type") == "image":
        await _set_watermark(c.from_user.id, cid, {})
    await state.clear()
    await c.answer("Логотип удалён")
    await _edit_or_answer(
        c,
        "🗑 <b>Готово</b>\n\nЛоготип удалён. Теперь видео можно обрабатывать без него.",
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
