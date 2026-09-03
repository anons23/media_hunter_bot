"""CPU-friendly media processing override.

Keeps uniqueness for every video handled by the <=100 MB path while
avoiding the expensive unsharp/noise filters and unlimited encoder threads.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from . import processor as base


def _unique_video_filters() -> str:
    """Lightweight visual fingerprint with H.264-safe even dimensions."""
    return (
        "scale=trunc(iw*0.998/2)*2:trunc(ih*0.998/2)*2,"
        "eq=contrast=1.012:brightness=0.004:saturation=1.015"
    )


def process_media(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    audio_only: bool,
    compress: bool,
    register: Callable[[Any], None],
) -> Path:
    # Be defensive: callers normally create the work directory, but the
    # processing layer must never fail merely because it disappeared between
    # queueing and FFmpeg startup.
    work_dir.mkdir(parents=True, exist_ok=True)

    if audio_only:
        output = work_dir / "output.mp3"
        cmd = [
            "ffmpeg", "-y", "-i", str(source), "-vn", "-ar", "44100", "-ac", "2",
            "-threads", "1", str(output),
        ]
    else:
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
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            "-metadata", "comment=media_hunter",
        ]
        # The VPS is CPU-bound on watermark/autopost re-encodes. superfast
        # substantially reduces wall-clock time while uniqueness remains
        # active through the filter above. Compression keeps a separate CRF.
        cmd += ["-crf", "30", "-preset", "superfast"] if compress else ["-crf", "27", "-preset", "superfast"]
        base_vf = _unique_video_filters()
        if logo:
            fc = (
                f"[0:v]{base_vf}[base];"
                f"[base][1:v]overlay={base._positions_overlay(str(watermark.get('position', 'br')))}[v]"
            )
            cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-shortest"]
        else:
            vf_parts = [base_vf]
            if has_text:
                text_filter = base._build_text_filter(watermark, work_dir)
                if text_filter:
                    vf_parts.append(text_filter)
            cmd += ["-vf", ",".join(vf_parts), "-af", "volume=1.01"]
        cmd.append(str(output))

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        register(proc)
        try:
            _, stderr = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            logger = base.logger
            logger.warning("ffmpeg timed out (10 min) for work_dir=%s", work_dir)
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
