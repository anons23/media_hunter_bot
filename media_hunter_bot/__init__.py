"""Media Hunter Bot — Telegram bot for downloading and processing media."""

__version__ = "3.0.0"

# Patch processing before handlers import process_media directly.
from . import processor as _processor
from .optimized_processor import process_media as _optimized_process_media
from .unique_filter import unique_video_filters as _safe_unique_video_filters

_processor._unique_video_filters = _safe_unique_video_filters
_processor.process_media = _optimized_process_media

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
    return _original_register_wm_wizard(router, lambda uid: _filtered_menu(menu_fn, uid))


async def _patched_middleware_call(self, handler, event, data):
    # Handlers now own their final markup. In particular, do not mutate the
    # cwmx:* result after the channel watermark handler has rendered it.
    return await handler(event, data)


_wm_wizard.register_wm_wizard = _patched_register_wm_wizard
_wm_wizard._MainMenuInfoMiddleware.__call__ = _patched_middleware_call

del _processor
del _optimized_process_media
del _safe_unique_video_filters
del _wm_wizard
