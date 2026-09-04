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

# For autopost jobs, the first enabled channel is the source of truth for the
# watermark used on the video sent back to the user. The exact same processed
# file is then reused for that first channel, so an old user-level/legacy
# watermark cannot unexpectedly replace the channel's configured watermark.
from . import db as _db

_original_get_user_watermark = _db.aget_user_watermark


async def _first_channel_watermark(uid):
    try:
        channels = await _db.alist_channels(uid)
        enabled = [ch for ch in channels if bool(ch["enabled"])]
        if enabled:
            return await _db.aget_channel_watermark(enabled[0]["channel_id"], uid)
    except Exception:
        # Keep the existing user watermark path if channel lookup is not
        # available during startup/bootstrap or in a degraded DB state.
        pass
    return await _original_get_user_watermark(uid)


_db.aget_user_watermark = _first_channel_watermark

# Local Bot API returns absolute filesystem paths from getFile(). Tell aiogram
# to consume those paths locally instead of requesting /file/botTOKEN/<path>.
# This must happen before handlers.py constructs its AiohttpSession.
from aiogram.client.telegram import TelegramAPIServer as _TelegramAPIServer

_original_api_from_base = _TelegramAPIServer.from_base


@classmethod
def _local_api_from_base(cls, base, **kwargs):
    kwargs.setdefault("is_local", True)
    return _original_api_from_base(base, **kwargs)


_TelegramAPIServer.from_base = _local_api_from_base

# Keep only channel watermark controls in the UI. Format selection remains
# available from the Download screen, so the separate Settings button is not
# needed. Also disable the old middleware's post-handler menu mutation: it
# was overwriting the channel watermark screen immediately after cwmx:* was
# handled, making the user appear to be kicked back to the channel screen.
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
    # Register the photo handler at the same point as the watermark wizard so
    # it is present even when the service imports handlers.py directly instead
    # of going through the repository root main.py bootstrap.
    try:
        from .logo_upload_fix import patch_router as _patch_logo_router
        _patch_logo_router(router)
    except Exception:
        # Keep startup resilient; normal document uploads remain available.
        pass
    return result


async def _patched_middleware_call(self, handler, event, data):
    # Handlers now own their final markup. In particular, do not mutate the
    # cwmx:* result after the channel watermark handler has rendered it.
    return await handler(event, data)


_wm_wizard.register_wm_wizard = _patched_register_wm_wizard
_wm_wizard._MainMenuInfoMiddleware.__call__ = _patched_middleware_call

# Clear the old Telegram command menu. The mobile Telegram "Menu" button is
# populated by Bot API commands, not by the inline keyboard in menu().
# Clearing the default command scope removes legacy entries such as Hunter
# method, autopost and Premium that were left from the previous version.
from aiogram import Bot as _Bot

_original_bot_get_me = _Bot.get_me


async def _get_me_and_clear_legacy_commands(self, *args, **kwargs):
    result = await _original_bot_get_me(self, *args, **kwargs)
    try:
        await self.delete_my_commands()
    except Exception:
        # A temporary API error must not prevent the bot from starting.
        pass
    return result


_Bot.get_me = _get_me_and_clear_legacy_commands

# Keep these processing callables alive: _cached_process_entry is invoked later
# by handlers/wm_wizard in a worker thread and resolves them from its globals.
# Deleting them here causes production-only NameError after the service starts.
del _processor
del _safe_unique_video_filters
del _TelegramAPIServer
del _wm_wizard
