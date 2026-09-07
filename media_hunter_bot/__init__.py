"""Media Hunter Bot — Telegram bot for downloading and processing media."""

__version__ = "3.0.0"

from pathlib import Path

# Patch processing before handlers import process_media directly.
from . import processor as _processor
from .optimized_processor import process_media as _optimized_process_media
from .unique_filter import unique_video_filters as _safe_unique_video_filters
from .process_cache import cached_process_media as _cached_process_media
from .oversize_processor import compress_for_send as _compress_for_send
from .config import MAX_UNIQUE_SIZE_MB


def _cached_process_entry(source, work, watermark, audio_only=False, compress=False, register=None):
    # Videos above the 100 MB uniqueness ceiling must NOT be unique-processed.
    # They still need a sendable copy because Telegram upload is capped at the
    # configured MAX_SEND_MB. Use the dedicated compression-only pipeline.
    source_path = Path(source)
    if (
        not audio_only
        and source_path.exists()
        and source_path.stat().st_size > MAX_UNIQUE_SIZE_MB * 1024 * 1024
    ):
        return _compress_for_send(source_path, work, watermark, register)
    return _cached_process_media(
        _optimized_process_media,
        source,
        work,
        watermark,
        audio_only=audio_only,
        compress=compress,
        register=register,
    )


_processor._unique_video_filters = _safe_unique_video_filters
_processor.process_media = _cached_process_entry

from . import db as _db

_original_get_user_watermark = _db.aget_user_watermark


async def _first_channel_watermark(uid):
    try:
        channels = await _db.alist_channels(uid)
        enabled = [ch for ch in channels if bool(ch["enabled"])]
        if enabled:
            return await _db.aget_channel_watermark(enabled[0]["channel_id"], uid)
    except Exception:
        pass
    return await _original_get_user_watermark(uid)


_db.aget_user_watermark = _first_channel_watermark

from aiogram.client.telegram import TelegramAPIServer as _TelegramAPIServer
_original_api_from_base = _TelegramAPIServer.from_base


@classmethod
def _local_api_from_base(cls, base, **kwargs):
    kwargs.setdefault("is_local", True)
    return _original_api_from_base(base, **kwargs)


_TelegramAPIServer.from_base = _local_api_from_base

from . import wm_wizard as _wm_wizard
_original_register_wm_wizard = _wm_wizard.register_wm_wizard


def _filtered_menu(menu_fn, uid):
    original = menu_fn(uid)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    hidden = {"wm", "settings"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b.text, callback_data=b.callback_data, url=b.url)
         for b in row if b.callback_data not in hidden]
        for row in original.inline_keyboard
        if any(b.callback_data not in hidden for b in row)
    ])


def _patched_register_wm_wizard(router, menu_fn):
    result = _original_register_wm_wizard(router, lambda uid: _filtered_menu(menu_fn, uid))
    try:
        from .logo_upload_fix import patch_router as _patch_logo_router
        _patch_logo_router(router)
    except Exception:
        pass
    try:
        from .logo_photo_fallback import patch_router as _patch_logo_fallback
        _patch_logo_fallback(router)
    except Exception:
        pass
    try:
        from .logo_debug import patch_router as _patch_logo_debug
        _patch_logo_debug(router)
    except Exception:
        pass
    try:
        from .logo_state_trace import patch_router as _patch_logo_state_trace
        _patch_logo_state_trace(router)
    except Exception:
        pass
    return result


async def _patched_middleware_call(self, handler, event, data):
    return await handler(event, data)


_wm_wizard.register_wm_wizard = _patched_register_wm_wizard
_wm_wizard._MainMenuInfoMiddleware.__call__ = _patched_middleware_call

from aiogram import Bot as _Bot
_original_bot_get_me = _Bot.get_me


async def _get_me_and_clear_legacy_commands(self, *args, **kwargs):
    result = await _original_bot_get_me(self, *args, **kwargs)
    try:
        await self.delete_my_commands()
    except Exception:
        pass

    return result


_Bot.get_me = _get_me_and_clear_legacy_commands

del _processor
del _safe_unique_video_filters
del _TelegramAPIServer
del _wm_wizard
