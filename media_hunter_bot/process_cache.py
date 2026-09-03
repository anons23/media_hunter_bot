"""Per-job process result cache used to avoid duplicate FFmpeg runs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger("media_hunter_bot.process_cache")
_MAX_ENTRIES = 256
_cache: dict[tuple[str, str, bool, bool], Path] = {}


def cached_process_media(
    processor: Callable[..., Path],
    source: Path,
    work: Path,
    watermark: Any,
    *,
    audio_only: bool,
    compress: bool,
    register: Callable[..., Any],
) -> Path:
    """Process once per source/work/options and reuse the exact result.

    The cache is deliberately scoped by the temporary work directory, so a
    result can only be reused inside the same job. Watermark is intentionally
    NOT part of the key: after the bot has created and sent the user's final
    video, enabled autopost channels receive that exact same Telegram media
    instead of triggering another FFmpeg encode. This means channel-specific
    watermark settings are not applied to autopost copies.

    Different compression modes still get independent outputs because a
    compression retry may legitimately require another encode.
    """
    key = (str(source.resolve()), str(work.resolve()), audio_only, compress)
    cached = _cache.get(key)
    if cached is not None and cached.exists():
        logger.info(
            "PROCESS_CACHE_HIT work=%s audio_only=%s compress=%s",
            work,
            audio_only,
            compress,
        )
        return cached

    logger.info(
        "PROCESS_CACHE_MISS work=%s audio_only=%s compress=%s",
        work,
        audio_only,
        compress,
    )
    result = processor(
        source,
        work,
        watermark,
        audio_only=audio_only,
        compress=compress,
        register=register,
    )
    if len(_cache) >= _MAX_ENTRIES:
        _cache.pop(next(iter(_cache)))
    _cache[key] = result
    return result


def clear() -> None:
    _cache.clear()
