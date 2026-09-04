"""Compression-only processing for source videos above the uniqueness ceiling.

Videos at or below 100 MB keep the normal uniqueness pipeline. Larger videos
are never passed through the uniqueness filter; this module only makes a
Telegram-sendable copy when the source is above the 100 MB send ceiling.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from . import processor as base
from .config import MAX_SEND_MB


def _duration_seconds(source: Path) -> float:
    info, _ = base.ffprobe(source)
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise RuntimeError("Не удалось определить длительность видео для сжатия.")
    return duration


class _CompressFailed(RuntimeError):
    """Internal: ffmpeg encode failed (not a size-limit failure)."""


def _run(cmd: list[str], output: Path, work_dir: Path, register: Callable[[Any], None]) -> Path:
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        register(proc)
        try:
            _, stderr = proc.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError("Превышено время ожидания при сжатии видео.")
        finally:
            register(None)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace")
            base.logger.warning(
                "oversize compression failed (code=%s): %s",
                proc.returncode,
                err[-2000:],
            )
            raise _CompressFailed("Не удалось обработать видео при сжатии.")
    if not output.exists():
        raise RuntimeError("Не удалось получить сжатое видео.")
    return output


def _build_cmd(
    source: Path,
    output: Path,
    video_bps: int,
    audio_bps: int,
    watermark: dict[str, Any],
    use_logo: bool,
    scale_height: int | None,
) -> list[str]:
    logo = base._logo_path(watermark) if use_logo and watermark.get("type") == "image" else None
    has_text = watermark.get("type") == "text" and bool(watermark.get("text"))

    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if logo:
        cmd += ["-i", str(logo)]
    cmd += [
        "-c:v", "libx264",
        "-threads", "2",
        "-b:v", str(video_bps),
        "-maxrate", str(video_bps),
        "-bufsize", str(max(video_bps * 2, 16_000)),
        "-c:a", "aac",
        "-b:a", str(audio_bps),
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-metadata", "comment=media_hunter oversize-compress",
    ]

    # Late attempts may force a lower resolution so long/4K sources fit under
    # the Telegram send ceiling when bitrate alone is not enough.
    scale_prefix = ""
    if scale_height:
        scale_prefix = (
            f"scale=-2:{int(scale_height)}:force_original_aspect_ratio=decrease,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        )

    if logo:
        pct = max(5, min(int(watermark.get("logo_size", 20)), 80)) / 100.0
        opacity = max(0.05, min(float(watermark.get("logo_opacity", 0.8)), 1.0)
        )
        fc = (
            f"[0:v]setpts=PTS-STARTPTS,{scale_prefix}format=yuv420p[base];"
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[logo0];"
            f"[logo0][base]scale2ref=w=main_w*{pct:.4f}:h=main_h*{pct:.4f}:force_original_aspect_ratio=decrease[logo][base2];"
            f"[base2][logo]overlay={base._positions_overlay(str(watermark.get('position', 'br')))}[v]"
        )
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-shortest"]
    elif has_text:
        text_filter = base._build_text_filter(watermark, output.parent)
        vf = f"{scale_prefix}{text_filter}" if text_filter else f"{scale_prefix}format=yuv420p"
        if vf.endswith(","):
            vf = vf[:-1]
        cmd += ["-vf", vf, "-af", "volume=1.0"]
    else:
        vf = f"{scale_prefix}format=yuv420p" if scale_height else "format=yuv420p"
        cmd += ["-vf", vf, "-af", "volume=1.0"]

    cmd.append(str(output))
    return cmd


def _attempt_encode(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    register: Callable[[Any], None],
    use_logo: bool,
) -> Path:
    limit = MAX_SEND_MB * 1024 * 1024
    duration = _duration_seconds(source)

    target_total_bps = int((limit * 8 * 0.92) / duration)
    audio_bps = min(64_000, max(24_000, target_total_bps // 8))
    video_bps = max(8_000, target_total_bps - audio_bps)

    # attempt 0-3: bitrate only; 4-5: 720p; 6-7: 480p
    scale_schedule = [None, None, None, None, 720, 720, 480, 480]

    last_error: Exception | None = None
    for attempt in range(8):
        output = work_dir / f"oversize_send_{'logo' if use_logo else 'plain'}_{attempt}.mp4"
        output.unlink(missing_ok=True)
        scale_height = scale_schedule[attempt]
        cmd = _build_cmd(
            source, output, video_bps, audio_bps, watermark, use_logo, scale_height
        )
        try:
            result = _run(cmd, output, work_dir, register)
        except _CompressFailed as exc:
            last_error = exc
            base.logger.warning(
                "OVERSIZE_ATTEMPT_FAIL source=%s attempt=%s logo=%s scale=%s",
                source.name, attempt + 1, use_logo, scale_height,
            )
            video_bps = max(4_000, int(video_bps * 0.65))
            audio_bps = max(16_000, int(audio_bps * 0.85))
            continue

        size = result.stat().st_size
        if size <= limit:
            base.logger.info(
                "OVERSIZE_COMPRESSED source=%s result=%s size=%s attempt=%s logo=%s scale=%s",
                source.name, result.name, size, attempt + 1, use_logo, scale_height,
            )
            return result

        base.logger.info(
            "OVERSIZE_TOO_BIG source=%s size=%s limit=%s attempt=%s",
            source.name, size, limit, attempt + 1,
        )
        video_bps = max(4_000, int(video_bps * 0.65))
        audio_bps = max(16_000, int(audio_bps * 0.85))

    if last_error is not None:
        # All encode attempts failed (ffmpeg errors), not merely oversize.
        raise RuntimeError("Не удалось обработать видео при сжатии.") from last_error
    raise RuntimeError(
        f"Не удалось сжать видео до лимита отправки {MAX_SEND_MB} МБ"
    )


def compress_for_send(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    register: Callable[[Any], None],
) -> Path:
    """Create a sendable copy without uniqueness processing.

    Tries with the configured watermark first. If logo/text filters make
    FFmpeg fail, falls back to compression without watermark so the user
    still receives a sendable file under the Telegram ceiling.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    wants_logo = watermark.get("type") == "image" and bool(watermark.get("logo"))
    wants_text = watermark.get("type") == "text" and bool(watermark.get("text"))

    if wants_logo or wants_text:
        try:
            return _attempt_encode(source, work_dir, watermark, register, use_logo=True)
        except RuntimeError as first_exc:
            base.logger.warning(
                "OVERSIZE_WATERMARK_FALLBACK source=%s err=%s",
                source.name, first_exc,
            )
            # Retry plain compression without watermark filters.
            try:
                return _attempt_encode(source, work_dir, {}, register, use_logo=False)
            except RuntimeError:
                raise first_exc from None

    return _attempt_encode(source, work_dir, watermark, register, use_logo=False)
