"""Processing for source videos above the uniqueness ceiling (> 100 MB).

Videos above MAX_UNIQUE_SIZE_MB are never passed through the uniqueness
filter. Policy (defaults):

* 100–130 MB (``ORIGINAL_SEND_MAX_MB``): the original is sent as is. Non-MP4
  containers are only remuxed to MP4 (stream copy, no re-encode).
* Nothing is ever overlaid on > 100 MB videos (no plate, logo or text).
* > 130 MB: gentle quality-first compression. Constant-quality H.264
  (``-crf 22``), resolution kept, only sources whose short side is above
  1080 px are downscaled to 1080p. AAC/MP3 audio is copied untouched, other
  codecs are re-encoded to AAC 192k. No target-size squeezing, so picture and
  sound are not destroyed. If re-encoding does not make the file smaller, the
  original is sent instead.

The local Telegram Bot API accepts uploads up to ``TELEGRAM_MAX_UPLOAD_MB``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from . import mediarun
from . import processor as base
from .config import (
    OVERSIZE_AUDIO_BITRATE,
    OVERSIZE_CRF,
    OVERSIZE_MAX_SIDE,
    OVERSIZE_PRESET,
    OVERSIZE_THREADS,
    ORIGINAL_SEND_MAX_MB,
    TELEGRAM_MAX_UPLOAD_MB,
)
from .optimized_processor import _validate_processed_media

_MB = 1024 * 1024
_COPY_AUDIO_CODECS = frozenset({"aac", "mp3"})
_MIN_TIMEOUT = 30 * 60
_MAX_TIMEOUT = 2 * 60 * 60


class _EncodeFailed(RuntimeError):
    """FFmpeg exited with an error."""


class _EncodeTimeout(RuntimeError):
    """FFmpeg did not finish in time (retrying would only double the wait)."""


def _streams(info: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [s for s in info.get("streams") or [] if s.get("codec_type") == kind]


def _duration_seconds(info: dict[str, Any]) -> float:
    try:
        return max(0.0, float((info.get("format") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        return 0.0


def _timeout_for(duration: float) -> int:
    # veryfast CRF encodes usually run faster than real time; keep a wide
    # margin for slow VPS CPUs and long videos instead of a fixed 15 minutes.
    return int(min(_MAX_TIMEOUT, max(_MIN_TIMEOUT, duration * 3)))


def _run(cmd: list[str], output: Path, register: Callable[[Any], None], timeout: int, duration: float = 0.0) -> Path:
    code, err, timed_out = mediarun.run_ffmpeg(cmd, register, timeout, duration)
    if timed_out:
        base.logger.warning("OVERSIZE_TIMEOUT output=%s timeout=%ss", output.name, timeout)
        raise _EncodeTimeout("Превышено время ожидания при сжатии видео.")
    if code != 0:
        base.logger.warning("OVERSIZE_FFMPEG_FAIL output=%s code=%s: %s", output.name, code, err)
        raise _EncodeFailed("Не удалось обработать видео при сжатии.")
    if not output.exists() or output.stat().st_size <= 0:
        raise _EncodeFailed("Не удалось получить сжатое видео.")
    return output


def _send_original(source: Path, work_dir: Path, register: Callable[[Any], None]) -> Path:
    """Return the original; remux non-MP4 containers to MP4 without re-encoding."""
    if source.suffix.lower() == ".mp4":
        return source
    output = work_dir / "original.mp4"
    output.unlink(missing_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
        "-movflags", "+faststart", str(output),
    ]
    try:
        _run(cmd, output, register, timeout=_MIN_TIMEOUT)
        _validate_processed_media(output, audio_only=False)
        return output
    except RuntimeError as exc:
        base.logger.warning("OVERSIZE_REMUX_SKIPPED source=%s err=%s", source.name, exc)
        output.unlink(missing_ok=True)
        return source


def _video_chain() -> str:
    """Scale only when the short side is above the cap; keep even dimensions."""
    cap = OVERSIZE_MAX_SIDE
    if cap > 0:
        scale = (
            f"scale=w='if(gte(iw,ih),-2,min({cap},trunc(iw/2)*2))'"
            f":h='if(gte(iw,ih),min({cap},trunc(ih/2)*2),-2)'"
        )
    else:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    return f"{scale},format=yuv420p"


def _audio_args(info: dict[str, Any]) -> list[str]:
    audio = _streams(info, "audio")
    if not audio:
        return []
    if str(audio[0].get("codec_name") or "").lower() in _COPY_AUDIO_CODECS:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", OVERSIZE_AUDIO_BITRATE]


def _build_cmd(source: Path, output: Path, info: dict[str, Any]) -> list[str]:
    return [
        "ffmpeg", "-y", "-hide_banner", "-i", str(source),
        "-vf", _video_chain(), "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", OVERSIZE_PRESET,
        "-crf", str(OVERSIZE_CRF),
        "-profile:v", "high",
        "-threads", str(OVERSIZE_THREADS),
        *_audio_args(info),
        "-max_muxing_queue_size", "4096",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-metadata", "comment=media_hunter oversize-compress",
        str(output),
    ]


def compress_for_send(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any] | None,
    register: Callable[[Any], None],
) -> Path:
    """Return a sendable file for a > 100 MB source (never unique-processed).

    ``watermark`` is accepted for call compatibility and deliberately ignored.
    """
    source = Path(source)
    work_dir.mkdir(parents=True, exist_ok=True)
    register = register or (lambda _p: None)
    size = source.stat().st_size

    if size <= ORIGINAL_SEND_MAX_MB * _MB:
        base.logger.info("OVERSIZE_ORIGINAL source=%s size=%s", source.name, size)
        return _send_original(source, work_dir, register)

    info, _ = base.ffprobe(source)
    if not _streams(info, "video"):
        raise RuntimeError("Не удалось прочитать видеопоток для сжатия.")
    timeout = _timeout_for(_duration_seconds(info))

    # > 100 MB videos never get a plate, logo or text watermark: they are
    # only (gently) compressed and sent as they are.
    output = work_dir / "oversize_plain.mp4"
    output.unlink(missing_ok=True)
    cmd = _build_cmd(source, output, info)
    base.logger.info(
        "OVERSIZE_COMPRESS_START source=%s size=%s crf=%s preset=%s timeout=%ss",
        source.name, size, OVERSIZE_CRF, OVERSIZE_PRESET, timeout,
    )
    result: Path | None = None
    try:
        _run(cmd, output, register, timeout, _duration_seconds(info))
        _validate_processed_media(output, audio_only=False)
        result = output
    except _EncodeTimeout:
        output.unlink(missing_ok=True)
        raise
    except RuntimeError as exc:
        output.unlink(missing_ok=True)
        raise RuntimeError("Не удалось обработать видео при сжатии.") from exc
    out_size = result.stat().st_size
    base.logger.info(
        "OVERSIZE_COMPRESSED source=%s src_size=%s out_size=%s",
        source.name, size, out_size,
    )
    if out_size >= size and size <= TELEGRAM_MAX_UPLOAD_MB * _MB:
        # Re-encoding did not help: the original is the better file.
        base.logger.info("OVERSIZE_KEEP_ORIGINAL source=%s", source.name)
        result.unlink(missing_ok=True)
        return _send_original(source, work_dir, register)
    if out_size > TELEGRAM_MAX_UPLOAD_MB * _MB:
        raise RuntimeError(f"Видео после сжатия превышает лимит Telegram {TELEGRAM_MAX_UPLOAD_MB} МБ")
    return result
