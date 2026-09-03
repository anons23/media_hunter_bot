"""Detailed timing diagnostics for the media pipeline.

This module only wraps existing functions/methods for logging; it does not
change processing or queue semantics.
"""
from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger("media_hunter_bot.pipeline")


def patch_handlers(handlers_module):
    """Trace download/probe/process stages and outbound Telegram sends."""
    if getattr(handlers_module, "_pipeline_stage_diagnostics_patched", False):
        return

    original_download = handlers_module.download
    original_ffprobe = handlers_module.ffprobe
    original_process = handlers_module.process_media
    handlers_module._pipeline_originals = (original_download, original_ffprobe, original_process)

    def timed_sync(name, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            logger.info("%s_START", name)
            try:
                result = func(*args, **kwargs)
                logger.info("%s_DONE elapsed_ms=%d", name, int((time.monotonic() - started) * 1000))
                return result
            except Exception:
                logger.exception("%s_FAILED elapsed_ms=%d", name, int((time.monotonic() - started) * 1000))
                raise
        return wrapper

    handlers_module.download = timed_sync("DOWNLOAD", original_download)
    handlers_module.ffprobe = timed_sync("FFPROBE", original_ffprobe)
    handlers_module.process_media = timed_sync("PROCESS", original_process)

    handlers_module._pipeline_stage_diagnostics_patched = True


def patch_bot_sends(bot_cls):
    """Trace outbound Telegram media/message calls without changing behavior."""
    if getattr(bot_cls, "_pipeline_send_diagnostics_patched", False):
        return

    async def wrap_async(name, original, *args, **kwargs):
        started = time.monotonic()
        chat_id = kwargs.get("chat_id")
        if chat_id is None and args:
            chat_id = args[0]
        logger.info("%s_START chat_id=%s", name, chat_id)
        try:
            result = await original(*args, **kwargs)
            logger.info("%s_DONE chat_id=%s elapsed_ms=%d", name, chat_id, int((time.monotonic() - started) * 1000))
            return result
        except Exception:
            logger.exception("%s_FAILED chat_id=%s elapsed_ms=%d", name, chat_id, int((time.monotonic() - started) * 1000))
            raise

    for name in ("send_video", "send_document", "send_audio", "send_message"):
        original = getattr(bot_cls, name)
        if getattr(original, "_pipeline_wrapped", False):
            continue

        def make_wrapper(method_name, method):
            @wraps(method)
            async def wrapper(self, *args, **kwargs):
                return await wrap_async(method_name, method.__get__(self, type(self)), *args, **kwargs)
            wrapper._pipeline_wrapped = True
            return wrapper

        setattr(bot_cls, name, make_wrapper(name.upper(), original))

    bot_cls._pipeline_send_diagnostics_patched = True
