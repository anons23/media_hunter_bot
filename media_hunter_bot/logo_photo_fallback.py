"""Last-resort FSM-safe router for Telegram gallery logo photos.

The normal logo wizard registers a state-filtered photo handler. This fallback
keeps gallery uploads working even if a router/bootstrap integration changes
the handler registration order. It never consumes ordinary photos because it
raises SkipHandler unless the current FSM state is exactly LogoStates.upload.
"""
from __future__ import annotations

import logging

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .logo_upload_fix import _handle_photo
from .wm_wizard import LogoStates

logger = logging.getLogger(__name__)


def patch_router(router: Router) -> None:
    if getattr(router, "_media_hunter_logo_photo_fallback", False):
        return

    @router.message(F.photo)
    async def _logo_photo_fallback(message: Message, state: FSMContext, bot) -> None:
        current_state = await state.get_state()
        if current_state != LogoStates.upload.state:
            raise SkipHandler
        logger.info("LOGO_PHOTO_FALLBACK uid=%s", message.from_user.id if message.from_user else None)
        await _handle_photo(message, bot, state)

    router._media_hunter_logo_photo_fallback = True
