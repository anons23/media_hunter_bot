"""Per-job process result cache used to avoid duplicate FFmpeg runs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger("media_hunter_bot.process_cache")
_MAX_ENTRIES = 256
_cache: dict[tuple[str, str, bool, bool, str], Path] = {}


def _watermark_key(watermark: Any) -> str:
    return repr(watermark)


def cached_process_media(processor: Callable[..., Path], source: Path, work: Path, watermark: Any, *, audio_only: bool, compress: bool, register: Callable[..., Any]) -> Path:
    """Run processor once per source/work/watermark/options combination.

    The cache is deliberately scoped by the temporary work directory, so a
    result can only be reused inside the same job. Different watermark
    profiles (including per-channel profiles) still get independent outputs.
    """
    key = (str(source.resolve()), str(work.resolve()), audio_only, compress, _watermark_key(watermark))
    cached = _cache.get(key)
    if cached is not None and cached.exists():
        logger.info("PROCESS_CACHE_HIT work=%s audio_only=%s compress=%s", work, audio_only, compress)
        return cached

    logger.info("PROCESS_CACHE_MISS work=%s audio_only=%s compress=%s", work, audio_only, compress)
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
