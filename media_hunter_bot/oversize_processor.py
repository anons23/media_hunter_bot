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
            base.logger.warning("oversize compression failed (code=%s): %s", proc.returncode, err[-2000:])
            raise RuntimeError("Не удалось сжать видео до лимита отправки.")
    if not output.exists():
        raise RuntimeError("Не удалось получить сжатое видео.")
    return output


def compress_for_send(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    register: Callable[[Any], None],
) -> Path:
    """Create a sendable copy without uniqueness processing.

    A bitrate budget is derived from duration, leaving margin for the MP4
    container and audio. If the result is still over the limit, the video
    bitrate is reduced iteratively. Watermarks are preserved when configured.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    limit = MAX_SEND_MB * 1024 * 1024
    duration = _duration_seconds(source)

    # Keep ~8% headroom for container overhead. Audio is deliberately modest
    # so very long videos still have enough budget for the video stream.
    target_total_bps = int((limit * 8 * 0.92) / duration)
    audio_bps = min(64_000, max(24_000, target_total_bps // 8))
    video_bps = max(8_000, target_total_bps - audio_bps)

    logo = base._logo_path(watermark) if watermark.get("type") == "image" else None
    has_text = watermark.get("type") == "text" and bool(watermark.get("text"))

    for attempt in range(8):
        output = work_dir / f"oversize_send_{attempt}.mp4"
        output.unlink(missing_ok=True)
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

        if logo:
            pct = max(5, min(int(watermark.get("logo_size", 20)), 80)) / 100.0
            opacity = max(0.05, min(float(watermark.get("logo_opacity", 0.8)), 1.0))
            fc = (
                f"[0:v]setpts=PTS-STARTPTS[base];"
                f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[logo0];"
                f"[logo0][base]scale2ref=w=main_w*{pct:.4f}:h=main_h*{pct:.4f}:force_original_aspect_ratio=decrease[logo][base2];"
                f"[base2][logo]overlay={base._positions_overlay(str(watermark.get('position', 'br')))}[v]"
            )
            cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-shortest"]
        elif has_text:
            text_filter = base._build_text_filter(watermark, work_dir)
            if text_filter:
                cmd += ["-vf", text_filter, "-af", "volume=1.0"]
            else:
                cmd += ["-af", "volume=1.0"]
        else:
            cmd += ["-vf", "format=yuv420p", "-af", "volume=1.0"]

        result = _run(cmd, output, work_dir, register)
        if result.stat().st_size <= limit:
            base.logger.info(
                "OVERSIZE_COMPRESSED source=%s result=%s size=%s attempt=%s",
                source.name, result.name, result.stat().st_size, attempt + 1,
            )
            return result

        # Real encodes can overshoot the nominal bitrate because of container
        # overhead and stream variability. Re-encode progressively lower until
        # the hard Telegram ceiling is met. The low floor is intentional: the
        # alternative is returning an un-sendable >100 MB source.
        video_bps = max(4_000, int(video_bps * 0.65))
        audio_bps = max(16_000, int(audio_bps * 0.85))

    raise RuntimeError(f"Не удалось сжать видео до лимита отправки {MAX_SEND_MB} МБ")
