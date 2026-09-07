"""CPU-friendly media processing override.

Keeps uniqueness for every video handled by the <=100 MB path while
avoiding the expensive unsharp/noise filters and unlimited encoder threads.

Audio: AAC 192k + soft filters (not copy). Quality stays close to typical
social-media sources; bitstream is still re-encoded (not an exact duplicate).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from . import processor as base

# Soft audio uniqueization: new AAC bitstream + tiny spectral change.
# Does NOT guarantee bypass of platform Content ID; aims for quality + non-identical stream.
_UNIQUE_AUDIO_FILTER = (
    "volume=1.02,"
    "highpass=f=40,"
    "lowpass=f=16000"
)
_AUDIO_BITRATE = "192k"
_MP3_BITRATE = "192k"


def _unique_video_filters() -> str:
    """Lightweight visual fingerprint with H.264-safe even dimensions."""
    return (
        "scale=trunc(iw*0.998/2)*2:trunc(ih*0.998/2)*2,"
        "eq=contrast=1.012:brightness=0.004:saturation=1.015"
    )


def _run_ffmpeg(cmd: list[str], output: Path, work_dir: Path, register: Callable[[Any], None]) -> Path:
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        register(proc)
        try:
            _, stderr = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            base.logger.warning("ffmpeg timed out (10 min) for work_dir=%s", work_dir)
            raise RuntimeError("Не удалось обработать медиа. Файл повреждён или формат не поддерживается.")
        finally:
            register(None)
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")
            base.logger.warning("ffmpeg failed (code=%s): %s", proc.returncode, err_text[-2000:])
            raise RuntimeError("Не удалось обработать медиа. Файл повреждён или формат не поддерживается.")
    if not output.exists():
        base.logger.warning("ffmpeg finished but output missing in %s", work_dir)
        raise RuntimeError("Не удалось обработать медиа. Результат не получен.")
    return output


def process_media(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    audio_only: bool,
    compress: bool,
    register: Callable[[Any], None],
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)

    if audio_only:
        output = work_dir / "output.mp3"
        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-vn", "-ar", "44100", "-ac", "2",
            "-c:a", "libmp3lame", "-b:a", _MP3_BITRATE,
            "-af", _UNIQUE_AUDIO_FILTER,
            "-threads", "1", str(output),
        ]
        return _run_ffmpeg(cmd, output, work_dir, register)

    logo = base._logo_path(watermark) if watermark.get("type") == "image" else None
    has_text = watermark.get("type") == "text" and bool(watermark.get("text"))
    output = work_dir / "output.mp4"
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if logo:
        cmd += ["-i", str(logo)]
    cmd += [
        "-c:v", "libx264",
        "-threads", "2",
        "-c:a", "aac",
        "-b:a", _AUDIO_BITRATE,
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-metadata", "comment=media_hunter",
    ]
    cmd += ["-crf", "30", "-preset", "superfast"] if compress else ["-crf", "27", "-preset", "superfast"]
    base_vf = _unique_video_filters()
    if logo:
        pct = max(5, min(int(watermark.get("logo_size", 20)), 80)) / 100.0
        opacity = max(0.05, min(float(watermark.get("logo_opacity", 0.8)), 1.0))
        fc = (
            f"[0:v]{base_vf}[base];"
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[logo0];"
            f"[logo0][base]scale2ref=w=main_w*{pct:.4f}:h=main_h*{pct:.4f}:force_original_aspect_ratio=decrease[logo][base2];"
            f"[base2][logo]overlay={base._positions_overlay(str(watermark.get('position', 'br')))}[v]"
        )
        # Soft af on mapped source audio (all uniqueness paths).
        cmd += [
            "-filter_complex", fc,
            "-map", "[v]",
            "-map", "0:a?",
            "-af", _UNIQUE_AUDIO_FILTER,
            "-shortest",
        ]
    else:
        vf_parts = [base_vf]
        if has_text:
            text_filter = base._build_text_filter(watermark, work_dir)
            if text_filter:
                vf_parts.append(text_filter)
        cmd += ["-vf", ",".join(vf_parts), "-af", _UNIQUE_AUDIO_FILTER]
    cmd.append(str(output))
    return _run_ffmpeg(cmd, output, work_dir, register)


def apply_watermark(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    compress: bool,
    register: Callable[[Any], None],
) -> Path:
    """Apply only the watermark to an already-unique video."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if not watermark or not watermark.get("type"):
        return source

    import hashlib
    import json

    profile = json.dumps(watermark, ensure_ascii=False, sort_keys=True, default=str)
    suffix = hashlib.sha1(profile.encode("utf-8")).hexdigest()[:12]
    output = work_dir / f"watermark_{suffix}.mp4"
    if output.exists():
        base.logger.info("WATERMARK_VARIANT_HIT work=%s file=%s", work_dir, output.name)
        return output

    logo = base._logo_path(watermark) if watermark.get("type") == "image" else None
    has_text = watermark.get("type") == "text" and bool(watermark.get("text"))
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if logo:
        cmd += ["-i", str(logo)]
    cmd += [
        "-c:v", "libx264",
        "-threads", "2",
        "-c:a", "aac",
        "-b:a", _AUDIO_BITRATE,
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-metadata", "comment=media_hunter",
        "-crf", "30" if compress else "27",
        "-preset", "superfast",
    ]
    if logo:
        pct = max(5, min(int(watermark.get("logo_size", 20)), 80)) / 100.0
        opacity = max(0.05, min(float(watermark.get("logo_opacity", 0.8)), 1.0))
        fc = (
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[logo0];"
            f"[logo0][0:v]scale2ref=w=main_w*{pct:.4f}:h=main_h*{pct:.4f}:force_original_aspect_ratio=decrease[logo][base];"
            f"[base][logo]overlay={base._positions_overlay(str(watermark.get('position', 'br')))}[v]"
        )
        cmd += [
            "-filter_complex", fc,
            "-map", "[v]",
            "-map", "0:a?",
            "-af", _UNIQUE_AUDIO_FILTER,
            "-shortest",
        ]
    elif has_text:
        text_filter = base._build_text_filter(watermark, work_dir)
        if not text_filter:
            return source
        cmd += ["-vf", text_filter, "-af", _UNIQUE_AUDIO_FILTER]
    else:
        return source
    cmd.append(str(output))
    base.logger.info("WATERMARK_VARIANT_CREATE work=%s file=%s", work_dir, output.name)
    return _run_ffmpeg(cmd, output, work_dir, register)
