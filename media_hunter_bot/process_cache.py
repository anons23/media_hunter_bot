"""Per-job processing cache with a frozen uniqueness base for multi-channel autopost."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from . import db
from .optimized_processor import apply_watermark

logger = logging.getLogger("media_hunter_bot.process_cache")
_MAX_ENTRIES = 256
_cache: dict[tuple[str, str, bool, bool], Path] = {}
_base_cache: dict[tuple[str, str, bool, bool], Path] = {}


def _channel_rows(work: Path) -> list[Any]:
    """Return enabled autopost channels for the user owning this job."""
    try:
        uid = int(work.name.split("_", 1)[0])
        return [row for row in db.list_channels(uid) if bool(row["enabled"])]
    except (TypeError, ValueError, KeyError, IndexError):
        return []
    except Exception:
        return []


def _enabled_channel_count(work: Path) -> int:
    """Get enabled autopost channel count from the per-job work directory."""
    rows = _channel_rows(work)
    if rows:
        return len(rows)
    try:
        uid = int(work.name.split("_", 1)[0])
    except (TypeError, ValueError):
        return 1
    try:
        return sum(1 for row in db.list_channels(uid) if bool(row["enabled"]))
    except Exception:
        return 1


def _first_channel_watermark(work: Path) -> dict[str, Any]:
    """Return the first enabled channel's configured watermark, if any."""
    rows = _channel_rows(work)
    if not rows:
        return {}
    try:
        raw = rows[0]["watermark"] or "{}"
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
        return {}


def _channel_watermarks(work: Path) -> list[dict[str, Any]]:
    """Return all enabled channel watermark profiles."""
    profiles: list[dict[str, Any]] = []
    for row in _channel_rows(work):
        try:
            raw = row["watermark"] or "{}"
            value = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(value, dict):
                profiles.append(value)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
            continue
    return profiles


def _watermark_key(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _use_first_channel_watermark(work: Path, watermark: Any) -> dict[str, Any]:
    """Use channel #1's watermark for the private result.

    Channel processing already passes its own profile. If the requested
    watermark is not one of the configured enabled-channel profiles, it is
    treated as the private/user profile and replaced by channel #1's profile.
    This deliberately makes the bot's delivered video identical to the first
    channel's autopost version instead of resurrecting a legacy user watermark.
    """
    if not _channel_rows(work):
        return dict(watermark) if isinstance(watermark, dict) else {}
    profiles = _channel_watermarks(work)
    requested_key = _watermark_key(watermark)
    if any(_watermark_key(profile) == requested_key for profile in profiles):
        return dict(watermark) if isinstance(watermark, dict) else {}
    return _first_channel_watermark(work)


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

    If at least one enabled autopost channel exists, the private/user result
    uses the first channel's watermark. For one channel this means the exact
    same processed file is reused for the channel, including its watermark.

    With multiple enabled channels, the first call creates and retains
    ``unique_base.mp4`` with NO watermark. The first channel's watermark is
    rendered for the user, while subsequent channel calls render their own
    profiles from the same frozen unique base. Uniqueness therefore still runs
    exactly once per job.
    """
    key = (str(source.resolve()), str(work.resolve()), audio_only, compress)

    if audio_only:
        cached = _cache.get(key)
        if cached is not None and cached.exists():
            logger.info("PROCESS_CACHE_HIT work=%s audio_only=%s compress=%s", work, audio_only, compress)
            return cached
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

    channel_count = _enabled_channel_count(work)
    effective_watermark = _use_first_channel_watermark(work, watermark) if channel_count >= 1 else (
        dict(watermark) if isinstance(watermark, dict) else {}
    )

    if channel_count <= 1:
        cached = _cache.get(key)
        if cached is not None and cached.exists():
            logger.info("PROCESS_CACHE_HIT work=%s channels=%s", work, channel_count)
            return cached
        logger.info("PROCESS_CACHE_MISS work=%s channels=%s", work, channel_count)
        result = processor(
            source,
            work,
            effective_watermark,
            audio_only=False,
            compress=compress,
            register=register,
        )
        _remember(key, result)
        return result

    base_result = _base_cache.get(key)
    if base_result is None or not base_result.exists():
        logger.info("UNIQUE_BASE_CREATE work=%s channels=%s", work, channel_count)
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
                frozen = base_result
        base_result = frozen
        _base_cache[key] = base_result
        logger.info("UNIQUE_BASE_READY work=%s file=%s", work, base_result.name)
    else:
        logger.info("UNIQUE_BASE_HIT work=%s file=%s", work, base_result.name)

    if not effective_watermark or not effective_watermark.get("type"):
        return base_result

    variant = apply_watermark(base_result, work, dict(effective_watermark), compress, register)
    _cache[key] = variant
    return variant


def clear() -> None:
    _cache.clear()
    _base_cache.clear()
