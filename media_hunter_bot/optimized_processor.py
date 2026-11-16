"""CPU-friendly media processing override.

Keeps uniqueness for every video handled by the <=100 MB path while
avoiding the expensive unsharp/noise filters and unlimited encoder threads.

Audio: AAC 192k + soft filters (not copy). Quality stays close to typical
social-media sources; bitstream is still re-encoded (not an exact duplicate).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import mediarun
from . import plate as plate_mod
from . import processor as base
from .config import SOFT_UNIQUE_SIZE_MB
from .unique_filter import unique_video_filters

_UNIQUE_AUDIO_FILTER = "volume=1.02,highpass=f=40,lowpass=f=16000"
_AUDIO_BITRATE = "192k"
_MP3_BITRATE = "192k"


def _unique_video_filters() -> str:
    """Return a safe, lightly varied visual uniqueness filter."""
    return unique_video_filters()


def _validate_processed_media(path: Path, audio_only: bool) -> None:
    """Validate that FFmpeg produced a usable media file before delivery."""
    if not path.exists() or path.stat().st_size <= 0:
        base.logger.warning("processed output missing or empty: %s", path)
        raise RuntimeError("Обработанный файл не создан или пуст.")

    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        base.logger.warning("ffprobe validation failed (code=%s): %s", proc.returncode, proc.stderr[-2000:])
        raise RuntimeError("Обработанный файл не прошёл проверку FFmpeg.")
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError:
        base.logger.warning("ffprobe validation returned invalid JSON for %s", path)
        raise RuntimeError("Обработанный файл не прошёл проверку FFmpeg.")

    streams = info.get("streams") or []
    kind = "audio" if audio_only else "video"
    matching = [stream for stream in streams if stream.get("codec_type") == kind]
    if not matching:
        base.logger.warning("ffprobe validation found no %s stream: %s", kind, path)
        raise RuntimeError("Обработанный файл не содержит ожидаемый медиапоток.")

    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        base.logger.warning("ffprobe validation found invalid duration=%s: %s", duration, path)
        raise RuntimeError("Обработанный файл имеет некорректную длительность.")

    if not audio_only:
        stream = matching[0]
        try:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            base.logger.warning("ffprobe validation found invalid dimensions=%sx%s: %s", width, height, path)
            raise RuntimeError("Обработанный файл имеет некорректные размеры кадра.")


_MIN_TIMEOUT = 10 * 60
_MAX_TIMEOUT = 3 * 60 * 60


def _input_duration(cmd: list[str]) -> float:
    """Duration of the first ffmpeg input, 0 if unknown."""
    try:
        info, _ = base.ffprobe(Path(cmd[cmd.index("-i") + 1]))
        return max(0.0, float((info.get("format") or {}).get("duration") or 0))
    except Exception:
        return 0.0


def _timeout_for(duration: float) -> int:
    """Scale the ffmpeg timeout with media length (10 min .. 3 h)."""
    return int(min(_MAX_TIMEOUT, max(_MIN_TIMEOUT, duration * 2)))


def _probe_frame(source: Path) -> tuple[int, int, float]:
    """Displayed (rotation-aware) width, height and duration of a video."""
    try:
        info, _ = base.ffprobe(Path(source))
    except Exception:
        return 1280, 720, 0.0
    video = next((s for s in info.get("streams") or [] if s.get("codec_type") == "video"), {})
    w, h = int(video.get("width") or 1280), int(video.get("height") or 720)
    rotation = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    rotation = int(float((video.get("tags") or {}).get("rotate", rotation)))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return w, h, duration


def _final_frame_size(w: int, h: int, unique: bool, max_side: int | None) -> tuple[int, int]:
    """Frame size after the unique scale and optional short-side cap."""
    if unique:
        w, h = int(w * 0.998 / 2) * 2, int(h * 0.998 / 2) * 2
    if max_side:
        if w >= h and h > max_side:
            w, h = int(round(w * max_side / h / 2)) * 2, max_side
        elif h > w and w > max_side:
            w, h = max_side, int(round(h * max_side / w / 2)) * 2
    return max(2, w), max(2, h)


def _run_ffmpeg(
    cmd: list[str],
    output: Path,
    work_dir: Path,
    register: Callable[[Any], None],
    timeout: int | None = None,
) -> Path:
    duration = _input_duration(cmd)
    if timeout is None:
        timeout = _timeout_for(duration)
    code, err_text, timed_out = mediarun.run_ffmpeg(cmd, register, timeout, duration)
    if timed_out:
        base.logger.warning("ffmpeg timed out (%ss) for work_dir=%s", timeout, work_dir)
        raise RuntimeError("Превышено время ожидания при обработке видео. Попробуйте позже или пришлите видео короче.")
    if code != 0:
        base.logger.warning("ffmpeg failed (code=%s): %s", code, err_text)
        raise RuntimeError("Не удалось обработать медиа. Файл повреждён или формат не поддерживается.")
    _validate_processed_media(output, audio_only=output.suffix.lower() == ".mp3")
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

    output = work_dir / "output.mp4"
    if not compress:
        cmd = _video_cmd(source, output, watermark, work_dir, crf=27)
        return _run_ffmpeg(cmd, output, work_dir, register)

    # 80–100 MB path: must land under the soft target. Step down gently
    # instead of failing after the first attempt.
    target = SOFT_UNIQUE_SIZE_MB * 1024 * 1024
    timeout = _timeout_for(_input_duration(["-i", str(source)]))
    result = output
    for attempt, (crf, max_side) in enumerate(_COMPRESS_STEPS, start=1):
        cmd = _video_cmd(source, output, watermark, work_dir, crf=crf, max_side=max_side)
        result = _run_ffmpeg(cmd, output, work_dir, register, timeout=timeout)
        size = result.stat().st_size
        if size <= target:
            if attempt > 1:
                base.logger.info("UNIQUE_COMPRESS_STEP_OK attempt=%s crf=%s side=%s size=%s", attempt, crf, max_side, size)
            return result
        base.logger.info("UNIQUE_COMPRESS_TOO_BIG attempt=%s crf=%s side=%s size=%s target=%s", attempt, crf, max_side, size, target)
    return result


# (crf, short-side cap) for the compress path; None = keep resolution.
_COMPRESS_STEPS: tuple[tuple[int, int | None], ...] = ((30, None), (33, None), (33, 720))


def _side_cap_filter(max_side: int) -> str:
    return (
        f"scale=w='if(gte(iw,ih),-2,min({max_side},trunc(iw/2)*2))'"
        f":h='if(gte(iw,ih),min({max_side},trunc(ih/2)*2),-2)'"
    )


def _video_cmd(
    source: Path,
    output: Path,
    watermark: dict[str, Any],
    work_dir: Path,
    crf: int,
    max_side: int | None = None,
) -> list[str]:
    logo = base._logo_path(watermark) if watermark.get("type") == "image" else None
    has_text = watermark.get("type") == "text" and bool(watermark.get("text"))
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if logo:
        cmd += plate_mod.input_args(logo)
    cmd += [
        "-c:v", "libx264", "-threads", "2",
        "-c:a", "aac", "-b:a", _AUDIO_BITRATE, "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-map_metadata", "-1", "-metadata", "comment=media_hunter",
    ]
    cmd += ["-crf", str(crf), "-preset", "superfast"]
    base_vf = _unique_video_filters()
    if max_side:
        base_vf = f"{base_vf},{_side_cap_filter(max_side)}"
    if logo:
        w, h, duration = _probe_frame(source)
        frame_w = _final_frame_size(w, h, unique=True, max_side=max_side)[0]
        fc = plate_mod.overlay_graph(base_vf, plate_mod.normalize(watermark), frame_w, duration)
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-af", _UNIQUE_AUDIO_FILTER, "-shortest"]
    else:
        vf_parts = [base_vf]
        if has_text:
            w, h, _ = _probe_frame(source)
            frame_h = _final_frame_size(w, h, unique=True, max_side=max_side)[1]
            text_filter = base._build_text_filter(watermark, work_dir, frame_h)
            if text_filter:
                vf_parts.append(text_filter)
        cmd += ["-vf", ",".join(vf_parts), "-af", _UNIQUE_AUDIO_FILTER]
    cmd.append(str(output))
    return cmd


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
        cmd += plate_mod.input_args(logo)
    cmd += [
        "-c:v", "libx264", "-threads", "2",
        "-c:a", "aac", "-b:a", _AUDIO_BITRATE, "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-map_metadata", "-1", "-metadata", "comment=media_hunter",
        "-crf", "30" if compress else "27", "-preset", "superfast",
    ]
    if logo:
        w, h, duration = _probe_frame(source)
        frame_w = _final_frame_size(w, h, unique=False, max_side=None)[0]
        fc = plate_mod.overlay_graph("", plate_mod.normalize(watermark), frame_w, duration)
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-af", _UNIQUE_AUDIO_FILTER, "-shortest"]
    elif has_text:
        w, h, _ = _probe_frame(source)
        text_filter = base._build_text_filter(watermark, work_dir, _final_frame_size(w, h, unique=False, max_side=None)[1])
        if not text_filter:
            return source
        cmd += ["-vf", text_filter, "-af", _UNIQUE_AUDIO_FILTER]
    else:
        return source
    cmd.append(str(output))
    base.logger.info("WATERMARK_VARIANT_CREATE work=%s file=%s", work_dir, output.name)
    return _run_ffmpeg(cmd, output, work_dir, register)
