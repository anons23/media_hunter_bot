"""Temporary diagnostic handler for logo-upload FSM routing.

The handler only logs the current FSM state and media fields, then raises
SkipHandler so the real logo upload handler can continue processing the update.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .wm_wizard import LogoStates

logger = logging.getLogger(__name__)


def patch_router(router: Router) -> None:
    if getattr(router, "_media_hunter_logo_debug", False):
        return

    @router.message(LogoStates.upload)
    async def _logo_debug(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        document = message.document
        animation = message.animation
        logger.warning(
            "LOGO_DEBUG state=%s photo=%s document=%s animation=%s "
            "doc_name=%s doc_mime=%s anim_name=%s anim_mime=%s",
            current_state,
            bool(message.photo),
            bool(document),
            bool(animation),
            document.file_name if document else None,
            document.mime_type if document else None,
            animation.file_name if animation else None,
            animation.mime_type if animation else None,
        )
        raise SkipHandler

    router._media_hunter_logo_debug = True
