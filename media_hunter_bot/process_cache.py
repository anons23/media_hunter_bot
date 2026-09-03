"""Per-job processing cache with a frozen uniqueness base for multi-channel autopost."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from . import db
from .optimized_processor import apply_watermark

logger = logging.getLogger("media_hunter_bot.process_cache")
_MAX_ENTRIES = 256
_cache: dict[tuple[str, str, bool, bool], Path] = {}
_base_cache: dict[tuple[str, str, bool, bool], Path] = {}


def _enabled_channel_count(work: Path) -> int:
    """Get enabled autopost channel count from the per-job work directory."""
    try:
        uid = int(work.name.split("_", 1)[0])
    except (TypeError, ValueError):
        return 1
    try:
        return sum(1 for row in db.list_channels(uid) if bool(row["enabled"]))
    except Exception:
        # Fail safe to the old exact-copy behaviour if DB inspection is not
        # available in a test/bootstrap context.
        return 1


def _remember(key: tuple[str, str, bool, bool], result: Path) -> None:
    if len(_cache) >= _MAX_ENTRIES:
        _cache.pop(next(iter(_cache)))
    _cache[key] = result


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
    """Return a processed result while keeping uniqueness to one pass.

    With zero or one enabled autopost channel, the exact-copy optimisation is
    retained: the first final result is reused for the channel.

    With multiple enabled channels, the first call creates and retains
    ``unique_base.mp4`` with NO watermark. The caller's requested watermark
    (private delivery or a channel) is then rendered from that frozen base by
    ``apply_watermark()``. Subsequent calls for different channel watermark
    profiles never run the uniqueness filter again.

    The work directory owns the lifecycle: handlers keep it alive until all
    private/autopost sends finish, then their existing cleanup removes the
    base and variants together. This is the intentional temporary "pause" /
    fixation of the unique result.
    """
    key = (str(source.resolve()), str(work.resolve()), audio_only, compress)

    if audio_only or _enabled_channel_count(work) <= 1:
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
        _remember(key, result)
        return result

    base_result = _base_cache.get(key)
    if base_result is None or not base_result.exists():
        logger.info("UNIQUE_BASE_CREATE work=%s channels=%s", work, _enabled_channel_count(work))
        # The uniqueness processor is deliberately called with an empty
        # watermark. That freezes the unique visual/audio result before any
        # channel-specific watermarking starts.
        base_result = processor(
            source,
            work,
            {},
            audio_only=False,
            compress=compress,
            register=register,
        )
        frozen = work / "unique_base.mp4"
        if base_result != frozen:
            try:
                base_result.replace(frozen)
            except OSError:
                # Keep the processor's path if replacement is unavailable.
                frozen = base_result
        base_result = frozen
        _base_cache[key] = base_result
        logger.info("UNIQUE_BASE_READY work=%s file=%s", work, base_result.name)
    else:
        logger.info("UNIQUE_BASE_HIT work=%s file=%s", work, base_result.name)

    if not watermark or not watermark.get("type"):
        return base_result

    variant = apply_watermark(base_result, work, dict(watermark), compress, register)
    _cache[key] = variant
    return variant


def clear() -> None:
    _cache.clear()
    _base_cache.clear()
