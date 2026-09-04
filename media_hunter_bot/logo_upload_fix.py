"""Reliable Telegram gallery-photo upload for the logo wizard.

The legacy wizard accepts PNG documents. Normal Telegram gallery images are
Message.photo, so this module handles the whole upload state explicitly.
The handler intentionally uses the FSM state as the primary filter rather
than relying on the photo content filter alone.
"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path

from aiogram.types import Message

from .config import LOGO_DIR, MAX_WATERMARK_MB
from .processor import validate_logo
from .wm_wizard import LogoStates, _logo_summary


def _logo_settings_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [
        [InlineKeyboardButton(text="📏 Размер", callback_data="logosize_menu"),
         InlineKeyboardButton(text="📍 Позиция", callback_data="logopos_menu")],
        [InlineKeyboardButton(text="👁 Прозрачность", callback_data="logoop_menu")],
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="logo_save")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="logo_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _handle_photo(message: Message, bot, state) -> bool:
    if not message.photo:
        return False
    size = message.photo[-1]
    p = LOGO_DIR / f"logo_{message.from_user.id}_{uuid.uuid4().hex}.png"
    jpg = p.with_suffix(".jpg")
    try:
        if size.file_size and size.file_size > MAX_WATERMARK_MB * 1024 * 1024:
            await message.answer(f"❌ Нужен логотип до {MAX_WATERMARK_MB} МБ.")
            return True
        await asyncio.wait_for(asyncio.to_thread(LOGO_DIR.mkdir, parents=True, exist_ok=True), timeout=5)
        f = await asyncio.wait_for(bot.get_file(size.file_id), timeout=60)
        await asyncio.wait_for(bot.download_file(f.file_path, destination=jpg), timeout=300)
        if not jpg.exists() or jpg.stat().st_size <= 0:
            raise RuntimeError("Telegram не вернул файл изображения.")
        if jpg.stat().st_size > MAX_WATERMARK_MB * 1024 * 1024:
            raise ValueError(f"Изображение превышает максимальный размер {MAX_WATERMARK_MB} МБ.")

        proc = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", str(jpg), "-frames:v", "1", "-pix_fmt", "rgba", str(p)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0 or not p.exists() or p.stat().st_size <= 0:
            raise RuntimeError("Не удалось подготовить изображение логотипа.")
        jpg.unlink(missing_ok=True)
        if p.stat().st_size > MAX_WATERMARK_MB * 1024 * 1024:
            raise ValueError(f"PNG превышает максимальный размер {MAX_WATERMARK_MB} МБ.")
        ok, msg = await asyncio.to_thread(validate_logo, p)
        if not ok:
            raise ValueError(msg)

        data = await state.get_data()
        await state.update_data(
            logo_path=str(p),
            logo_size=int(data.get("logo_size", 20)),
            logo_position=data.get("logo_position", "br"),
            logo_opacity=float(data.get("logo_opacity", 0.8)),
        )
        await state.set_state(LogoStates.settings)
        data = await state.get_data()
        await message.answer(_logo_summary(data), reply_markup=_logo_settings_keyboard(), parse_mode="HTML")
    except ValueError as exc:
        p.unlink(missing_ok=True)
        jpg.unlink(missing_ok=True)
        await message.answer(f"❌ {exc}")
    except Exception as exc:
        p.unlink(missing_ok=True)
        jpg.unlink(missing_ok=True)
        await message.answer(f"❌ Не удалось загрузить логотип: {exc}")
    return True


def patch_router(router):
    if getattr(router, "_media_hunter_logo_photo_patched", False):
        return

    # Register on the complete LogoStates.upload state. This avoids depending
    # on Message.photo's optional content filter and guarantees that a photo
    # received while the wizard is waiting for a logo reaches this handler.
    @router.message(LogoStates.upload)
    async def _logo_photo_message(message: Message, bot, state):
        if message.photo:
            await _handle_photo(message, bot, state)
        else:
            await message.answer("❌ Отправьте изображение логотипа как фото из галереи или PNG-файл.")

    router._media_hunter_logo_photo_patched = True
