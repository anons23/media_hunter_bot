"""Media processing — yt-dlp, ffmpeg, ffprobe.

Все функции синхронные (subprocess); вызывайте через asyncio.to_thread()
чтобы не блокировать event loop.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import (
    CLEANER_AGE_HOURS,
    COOKIES_PATH,
    MAX_WATERMARK_MB,
    MAX_WATERMARK_PX,
    MEDIA_DIR,
)

logger = logging.getLogger(__name__)

# ── helpers ─────────────────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command, capture output, raise on non-zero after logging."""
    logger.debug("Running: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        logger.warning("Command failed (%d): %s", proc.returncode, proc.stderr[:500])
    return proc


# ── cleanup ─────────────────────────────────────────────────────────────────


def cleanup_media(age_hours: int, protected_paths: set[str]) -> None:
    """Remove files under MEDIA_DIR older than age_hours, skipping protected_paths."""
    if not MEDIA_DIR.exists():
        return
    now = time.time()
    cutoff = now - (age_hours * 3600)

    for root, dirs, files in os.walk(str(MEDIA_DIR), topdown=False):
        for name in files:
            fp = Path(root) / name
            if str(fp) in protected_paths:
                continue
            try:
                if fp.stat().st_mtime < cutoff:
                    fp.unlink()
            except OSError:
                pass

        for name in dirs:
            dp = Path(root) / name
            try:
                if not any(dp.iterdir()):
                    dp.rmdir()
            except OSError:
                pass


# ── yt-dlp ──────────────────────────────────────────────────────────────────


def playlist_items(url: str, max_items: int) -> list[str]:
    """Return a list of video URLs if *url* is a playlist, otherwise empty list."""
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(webpage_url)s",
        "--playlist-end", str(max_items),
        "--quiet",
        url,
    ]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])

    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        return []
    lines = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
    # If we got exactly one line and it matches the input URL, treat as single video
    if len(lines) == 1 and lines[0] == url:
        return []
    return lines


def download(url: str, work_dir: Path, register: Callable[[Any], None]) -> Path:
    """Download best MP4 (<= 1080p to save RAM) into work_dir. Returns Path to file."""
    out_template = str(work_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", out_template,
        "--no-progress",
    ]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    cmd.append(url)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    register(proc)
    try:
        stdout, stderr = proc.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("yt-dlp timed out (10 min)")
    finally:
        register(None)

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace")[:800]
        raise RuntimeError(f"yt-dlp error: {err}")

    # Find the downloaded file
    candidates = list(work_dir.glob("source.*"))
    if not candidates:
        raise RuntimeError("yt-dlp finished but no file found")
    # Prefer mp4, otherwise take the largest file
    mp4s = [c for c in candidates if c.suffix.lower() == ".mp4"]
    if mp4s:
        return mp4s[0]
    return max(candidates, key=lambda p: p.stat().st_size)


# ── ffprobe / metadata ──────────────────────────────────────────────────────


def ffprobe(path: Path) -> tuple[dict[str, Any], int]:
    """Return (ffprobe JSON dict, file_size_bytes)."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[:500]}")
    info: dict[str, Any] = json.loads(proc.stdout)
    size = int(info.get("format", {}).get("size", path.stat().st_size))
    return info, size


def metadata(path: Path) -> dict[str, str]:
    """Extract title / description from media tags."""
    info, _ = ffprobe(path)
    fmt = info.get("format", {})
    tags = fmt.get("tags", {})
    return {
        "title": tags.get("title") or tags.get("TITLE") or path.stem,
        "description": tags.get("description") or tags.get("DESCRIPTION") or "",
    }
# ── ffmpeg processing ───────────────────────────────────────────────────────


# ── color validation ────────────────────────────────────────────────────────

# Whitelist: named colors ffmpeg understands + hex colors
_VALID_COLOR_NAMES = frozenset({
    "white", "black", "red", "green", "blue", "yellow", "cyan", "magenta",
    "orange", "pink", "purple", "brown", "gray", "grey", "silver", "gold",
    "lime", "navy", "teal", "olive", "maroon", "violet", "indigo", "turquoise",
})


def _is_valid_color(color: str) -> bool:
    """Validate color: named color or #RRGGBB / #RGB."""
    c = color.lower().strip()
    if c in _VALID_COLOR_NAMES:
        return True
    if c.startswith("#"):
        # #RGB or #RRGGBB
        hex_part = c[1:]
        if len(hex_part) == 3 and all(ch in "0123456789abcdef" for ch in hex_part):
            return True
        if len(hex_part) == 6 and all(ch in "0123456789abcdef" for ch in hex_part):
            return True
    return False


def _build_watermark_filter(wm: dict[str, Any], width: int, height: int) -> str | None:
    """Build ffmpeg drawtext/overlay filter string from watermark config."""
    wtype = wm.get("type")
    if wtype == "text":
        text = wm.get("text", "")
        if not text:
            return None
        pos = wm.get("position", "br")
        size = int(wm.get("size", 28))
        raw_color = wm.get("color", "white")
        color = raw_color if _is_valid_color(raw_color) else "white"
        opacity = float(wm.get("opacity", 0.8))

        # Position mapping
        positions = {
            "tl": "x=10:y=10",
            "tr": f"x=w-text_w-10:y=10",
            "bl": f"x=10:y=h-text_h-10",
            "br": f"x=w-text_w-10:y=h-text_h-10",
            "c":  f"x=(w-text_w)/2:y=(h-text_h)/2",
        }
        pos_str = positions.get(pos, positions["br"])

        # Escape colons and single quotes for drawtext
        safe_text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        return (
            f"drawtext=text='{safe_text}':{pos_str}:"
            f"fontsize={size}:fontcolor={color}@alpha={opacity:.2f}:"
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
    elif wtype == "image":
        logo_path = wm.get("logo", "")
        if not logo_path or not Path(logo_path).exists():
            return None
        pos = wm.get("position", "br")
        positions = {
            "tl": "x=10:y=10",
            "tr": "x=W-w-10:y=10",
            "bl": "x=10:y=H-h-10",
            "br": "x=W-w-10:y=H-h-10",
            "c":  "x=(W-w)/2:y=(H-h)/2",
        }
        pos_str = positions.get(pos, positions["br"])
        return f"movie={logo_path}[logo];[in][logo]overlay={pos_str}[out]"
    return None


def process_media(
    source: Path,
    work_dir: Path,
    watermark: dict[str, Any],
    audio_only: bool,
    compress: bool,
    register: Callable[[Any], None],
) -> Path:
    """Process source media: extract audio, compress, add watermark. Returns output Path."""
    if audio_only:
        output = work_dir / "output.mp3"
        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k",
            "-threads", "1",
            str(output),
        ]
    else:
        output = work_dir / "output.mp4"
        # Base command
        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-c:v", "libx264",
            "-preset", "fast",
            "-threads", "1",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
        ]

        if compress:
            # More aggressive compression for large files
            cmd.extend(["-crf", "28", "-preset", "fast"])
        else:
            cmd.extend(["-crf", "23", "-preset", "medium"])

        # Watermark
        filter_str = _build_watermark_filter(watermark, 0, 0)
        if filter_str:
            cmd.extend(["-vf", filter_str])

        cmd.append(str(output))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    register(proc)
    try:
        stdout, stderr = proc.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("ffmpeg timed out (10 min)")
    finally:
        register(None)

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace")[:800]
        raise RuntimeError(f"ffmpeg error: {err}")

    if not output.exists():
        raise RuntimeError("ffmpeg finished but output file missing")
    return output


# ── logo validation ─────────────────────────────────────────────────────────


def validate_logo(path: Path) -> tuple[bool, str]:
    """Check logo file size and dimensions. Returns (ok, error_message)."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return False, f"Cannot read file: {e}"

    if size > MAX_WATERMARK_MB * 1024 * 1024:
        return False, f"Logo too large ({size // 1024 // 1024} MB, max {MAX_WATERMARK_MB} MB)"

    # Use ffprobe to get width/height
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(path),
    ]
    proc = _run(cmd, timeout=30)
    if proc.returncode != 0:
        return False, "Invalid image file (ffprobe failed)"

    dims = proc.stdout.strip()
    if "x" not in dims:
        return False, "Cannot read image dimensions"

    try:
        w, h = map(int, dims.split("x", 1))
    except ValueError:
        return False, f"Unexpected dimensions format: {dims}"

    if w > MAX_WATERMARK_PX or h > MAX_WATERMARK_PX:
        return False, f"Image too large ({w}x{h}, max {MAX_WATERMARK_PX}x{MAX_WATERMARK_PX})"

    return True, ""
