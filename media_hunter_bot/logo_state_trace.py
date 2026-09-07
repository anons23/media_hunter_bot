"""Temporary non-consuming tracer for logo-upload media routing."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .wm_wizard import LogoStates

logger = logging.getLogger(__name__)


def patch_router(router: Router) -> None:
    if getattr(router, "_media_hunter_logo_state_trace", False):
        return

    @router.message(F.photo | F.document | F.animation)
    async def _trace(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state != LogoStates.upload.state:
            raise SkipHandler
        document = message.document
        animation = message.animation
        logger.warning(
            "LOGO_STATE_TRACE state=%s photo=%s document=%s animation=%s "
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

    router._media_hunter_logo_state_trace = True
