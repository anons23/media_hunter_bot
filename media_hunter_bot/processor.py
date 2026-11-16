"""Media processing — yt-dlp, ffmpeg, ffprobe.

All functions are synchronous (subprocess); callers should use
asyncio.to_thread() so the event loop is not blocked.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import COOKIES_PATH, LOGO_DIR, MAX_WATERMARK_MB, MAX_WATERMARK_PX, MEDIA_DIR, MAX_SOURCE_DOWNLOAD_MB

logger = logging.getLogger(__name__)

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_FONT_STYLE_PATHS = {
    "sans": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ),
    "bold": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "serif": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "mono": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
}

# Hostnames rejected before DNS resolution (defense in depth).
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "metadata.google.com",
})
_BLOCKED_HOSTNAME_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".intranet",
    ".corp",
    ".home",
    ".lan",
)


def _find_font(style: str | None = None) -> str:
    style_key = str(style or "sans")
    for candidate in _FONT_STYLE_PATHS.get(style_key, _FONT_STYLE_PATHS["sans"]):
        if os.path.exists(candidate):
            return candidate
    for candidate in _FONT_PATHS:
        if os.path.exists(candidate):
            return candidate
    try:
        proc = subprocess.run(["fc-match", "-f", "%{file}", "sans"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    logger.debug("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        logger.warning("Command failed (%d): %s", proc.returncode, proc.stderr[:500])
    return proc


def cleanup_media(age_hours: int, protected_paths: set[str]) -> None:
    if not MEDIA_DIR.exists():
        return
    cutoff = time.time() - age_hours * 3600
    protected: set[str] = set()
    for p in protected_paths:
        try:
            protected.add(str(Path(p).resolve()))
        except OSError:
            continue
    for root, dirs, files in os.walk(str(MEDIA_DIR), topdown=False):
        for name in files:
            fp = Path(root) / name
            try:
                if str(fp.resolve()) in protected:
                    continue
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


def cleanup_logos(age_hours: int, active_logos: set[str]) -> None:
    if not LOGO_DIR.exists():
        return
    cutoff = time.time() - age_hours * 3600
    active: set[str] = set()
    for p in active_logos:
        try:
            active.add(str(Path(p).resolve()))
        except OSError:
            continue
    for f in LOGO_DIR.iterdir():
        if not f.is_file():
            continue
        try:
            if str(f.resolve()) in active:
                continue
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def validate_source_url(url: str) -> str:
    """Validate a downloader URL and reject local/private network targets.

    This is defense in depth only. yt-dlp performs its own DNS resolution
    and may follow redirects. A production deployment MUST run the bot under
    an unprivileged user with egress firewall rules that block private,
    loopback and link-local destinations. Without network isolation the
    application-level checks cannot fully prevent DNS rebinding or
    redirect-to-internal attacks.
    """
    raw = str(url).strip()
    if "\r" in raw or "\n" in raw:
        logger.warning("Rejected source URL with control characters")
        raise ValueError("Недопустимые символы в URL")

    from urllib.parse import urlparse
    parsed = urlparse(raw)

    if parsed.scheme.lower() not in {"http", "https"}:
        logger.warning("Rejected non-HTTP(S) source URL scheme=%s", parsed.scheme)
        raise ValueError("Разрешены только HTTP/HTTPS ссылки")
    if parsed.username or parsed.password:
        logger.warning("Rejected source URL with embedded credentials")
        raise ValueError("Ссылки с учётными данными запрещены")

    host = parsed.hostname
    if not host:
        raise ValueError("Некорректный URL")

    host_l = host.lower().rstrip(".")
    if host_l in _BLOCKED_HOSTNAMES or any(host_l.endswith(suf) for suf in _BLOCKED_HOSTNAME_SUFFIXES):
        logger.warning("Rejected blocked hostname in source URL: %s", host_l)
        raise ValueError("Ссылки на локальные или внутренние адреса запрещены")

    try:
        literal_ip = ipaddress.ip_address(host_l)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        logger.warning("Rejected non-global literal IP in source URL: %s", host_l)
        raise ValueError("Ссылки на локальные или внутренние адреса запрещены")

    try:
        addresses = {ai[4][0] for ai in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exp:
        logger.warning("Failed to resolve source URL host=%s: %s", host, exp)
        raise ValueError("Не удалось разрешить адрес ссылки") from exp

    if not addresses:
        logger.warning("Empty address set for source URL host=%s", host)
        raise ValueError("Не удалось разрешить адрес ссылки")

    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global:
            logger.warning("Rejected non-global resolved address host=%s addr=%s", host, addr)
            raise ValueError("Ссылки на локальные или внутренние адреса запрещены")

    return raw


def playlist_items(url: str, max_items: int) -> list[str]:
    url = validate_source_url(url)
    cmd = ["yt-dlp", "--flat-playlist", "--print", "%(webpage_url)s", "--playlist-end", str(max_items), "--quiet", url]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        logger.warning("playlist_items failed for %s: %s", url, proc.stderr[:500])
        return []
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0] == url:
        return []
    return lines


def safe_media_filename(title: str, ext: str = ".mp4") -> str:
    """Build a Telegram-safe download filename from a media title."""
    name = str(title or "").strip() or "video"
    forbidden = set('\\/:*?"<>|')
    cleaned = []
    for ch in name:
        o = ord(ch)
        if ch in forbidden or ch in "\n\r\t":
            cleaned.append(" ")
        elif o < 32:
            continue
        else:
            cleaned.append(ch)
    name = "".join(cleaned)
    name = " ".join(name.split())
    name = name.strip(" .") or "video"
    if len(name) > 80:
        name = name[:80].rstrip(" .")
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{name}{ext}"


def _title_from_info_json(work_dir: Path) -> str:
    for info in work_dir.glob("*.info.json"):
        try:
            data = json.loads(info.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        title = str(data.get("title") or data.get("fulltitle") or "").strip()
        if title:
            return title[:200]
    return ""


def download(url: str, work_dir: Path, register: Callable[[Any], None]) -> tuple[Path, str]:
    """Download media and return (file_path, title).

    Title comes from yt-dlp info.json when available; otherwise a fallback name.
    """
    url = validate_source_url(url)
    out_template = str(work_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "-f",
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "--merge-output-format",
        "mp4",
        "--max-filesize",
        f"{MAX_SOURCE_DOWNLOAD_MB}M",
        "-o",
        out_template,
        "--write-info-json",
        "--no-progress",
    ]
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    cmd.append(url)
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        register(proc)
        try:
            _, stderr = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            logger.warning("yt-dlp timed out (10 min) for work_dir=%s", work_dir)
            raise RuntimeError("Превышено время ожидания при скачивании. Попробуйте позже.")
        finally:
            register(None)
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")[:2000]
            logger.warning("yt-dlp failed (code=%s): %s", proc.returncode, err_text)
            raise RuntimeError("Не удалось скачать медиа. Проверьте ссылку или попробуйте позже.")
    candidates = [c for c in work_dir.glob("source.*") if c.suffix.lower() != ".json" and not c.name.endswith(".info.json")]
    candidates = [c for c in candidates if c.is_file() and c.suffix.lower() in {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".mov"}]
    if not candidates:
        candidates = [c for c in work_dir.iterdir() if c.is_file() and c.suffix.lower() in {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".mov"}]
    if not candidates:
        logger.warning("yt-dlp finished but no file found in %s", work_dir)
        raise RuntimeError("Не удалось скачать медиа. Файл не получен.")
    mp4s = [c for c in candidates if c.suffix.lower() == ".mp4"]
    result = mp4s[0] if mp4s else max(candidates, key=lambda p: p.stat().st_size)
    if result.stat().st_size > MAX_SOURCE_DOWNLOAD_MB * 1024 * 1024:
        result.unlink(missing_ok=True)
        raise RuntimeError(f"Исходный файл превышает абсолютный лимит {MAX_SOURCE_DOWNLOAD_MB} МБ")
    title = _title_from_info_json(work_dir)
    if not title:
        title = "video"
    return result, title


def ffprobe(path: Path) -> tuple[dict[str, Any], int]:
    proc = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    if proc.returncode != 0:
        logger.warning("ffprobe failed (code=%s): %s", proc.returncode, (proc.stderr or "")[:2000])
        raise RuntimeError("Не удалось прочитать медиафайл. Формат не поддерживается или файл повреждён.")
    try:
        info: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("ffprobe returned invalid JSON")
        raise RuntimeError("Не удалось прочитать медиафайл. Формат не поддерживается или файл повреждён.")
    size = int(info.get("format", {}).get("size", path.stat().st_size))
    return info, size


def metadata(path: Path) -> dict[str, str]:
    info, _ = ffprobe(path)
    tags = info.get("format", {}).get("tags", {})
    return {"title": tags.get("title") or tags.get("TITLE") or path.stem, "description": tags.get("description") or tags.get("DESCRIPTION") or ""}


_VALID_COLOR_NAMES = frozenset({"white", "black", "red", "green", "blue", "yellow", "cyan", "magenta", "orange", "pink", "purple", "brown", "gray", "grey", "silver", "gold", "lime", "navy", "teal", "olive", "maroon", "violet", "indigo", "turquoise"})


def _is_valid_color(color: str) -> bool:
    c = str(color).lower().strip()
    if c in _VALID_COLOR_NAMES:
        return True
    if c.startswith("#"):
        h = c[1:]
        return len(h) in (3, 6) and all(ch in "0123456789abcdef" for ch in h)
    return False


def _positions_text(pos: str) -> str:
    return {"tl": "x=10:y=10", "tr": "x=w-text_w-10:y=10", "bl": "x=10:y=h-text_h-10", "br": "x=w-text_w-10:y=h-text_h-10", "c": "x=(w-text_w)/2:y=(h-text_h)/2"}.get(pos, "x=w-text_w-10:y=h-text_h-10")


def _positions_overlay(pos: str) -> str:
    return {"tl": "x=10:y=10", "tr": "x=W-w-10:y=10", "bl": "x=10:y=H-h-10", "br": "x=W-w-10:y=H-h-10", "c": "x=(W-w)/2:y=(H-h)/2"}.get(pos, "x=W-w-10:y=H-h-10")


def _build_text_filter(wm: dict[str, Any], work_dir: Path, frame_h: int | None = None) -> str | None:
    from . import textmark
    if textmark.is_new_format(wm):
        return textmark.drawtext_filter(textmark.normalize(wm), frame_h or 1080, work_dir)
    text = str(wm.get("text", ""))
    if not text:
        return None
    size = max(1, min(int(wm.get("size", 28)), 200))
    color = str(wm.get("color", "white"))
    if not _is_valid_color(color):
        color = "white"
    opacity = max(0.0, min(float(wm.get("opacity", 0.8)), 1.0))
    textfile = work_dir / "wm_text.txt"
    textfile.write_text(text, encoding="utf-8")
    font = _find_font(str(wm.get("font", "sans")))
    font_opt = f":fontfile='{font}'" if font else ""
    return f"drawtext=textfile='{textfile}':expansion=none:{_positions_text(str(wm.get('position', 'br')))}:fontsize={size}:fontcolor={color}@{opacity:.2f}{font_opt}"


def _logo_path(wm: dict[str, Any]) -> Path | None:
    raw = str(wm.get("logo", "")).strip()
    if not raw:
        return None
    root = LOGO_DIR.resolve()
    p = Path(raw).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        logger.warning("Rejected logo path outside LOGO_DIR: %s", raw)
        return None
    if not p.exists() or not p.is_file():
        return None
    return p


def _unique_video_filters() -> str:
    """Light fingerprint change without mirroring/flipping.

    Platforms see a re-encoded file that is not a byte-identical copy.
    Changes are subtle: tiny scale bounce, mild color/noise, no hflip.
    """
    return (
        "scale=iw*0.998:ih*0.998,"
        "scale=iw*1.002004:ih*1.002004,"
        "eq=contrast=1.012:brightness=0.004:saturation=1.015,"
        "unsharp=3:3:0.4:3:3:0.0,"
        "noise=alls=1:allf=t"
    )


def process_media(source: Path, work_dir: Path, watermark: dict[str, Any], audio_only: bool, compress: bool, register: Callable[[Any], None]) -> Path:
    if audio_only:
        output = work_dir / "output.mp3"
        cmd = ["ffmpeg", "-y", "-i", str(source), "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", "-threads", "1", str(output)]
    else:
        logo = _logo_path(watermark) if watermark.get("type") == "image" else None
        has_text = watermark.get("type") == "text" and bool(watermark.get("text"))
        # Always re-encode for uniqueness (no plain copy). Applies to all ≤100 MB jobs from handlers.
        output = work_dir / "output.mp4"
        cmd = ["ffmpeg", "-y", "-i", str(source)]
        if logo:
            cmd += ["-i", str(logo)]
        cmd += [
            "-c:v", "libx264",
            "-threads", "1",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            "-metadata", "comment=media_hunter",
        ]
        cmd += ["-crf", "28", "-preset", "fast"] if compress else ["-crf", "23", "-preset", "medium"]
        base_vf = _unique_video_filters()
        if logo:
            # Uniqueize first, then overlay logo (no mirror).
            fc = (
                f"[0:v]{base_vf}[base];"
                f"[base][1:v]overlay={_positions_overlay(str(watermark.get('position', 'br')))}[v]"
            )
            cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-shortest"]
        else:
            vf_parts = [base_vf]
            if has_text:
                text_filter = _build_text_filter(watermark, work_dir)
                if text_filter:
                    vf_parts.append(text_filter)
            # Slight audio gain so audio stream is not identical either.
            cmd += ["-vf", ",".join(vf_parts), "-af", "volume=1.01"]
        cmd.append(str(output))
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        register(proc)
        try:
            _, stderr = proc.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            logger.warning("ffmpeg timed out (10 min) for work_dir=%s", work_dir)
            raise RuntimeError("Не удалось обработать медиа. Файл повреждён или формат не поддерживается.")
        finally:
            register(None)
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")[:2000]
            logger.warning("ffmpeg failed (code=%s): %s", proc.returncode, err_text)
            raise RuntimeError("Не удалось обработать медиа. Файл повреждён или формат не поддерживается.")
    if not output.exists():
        logger.warning("ffmpeg finished but output missing in %s", work_dir)
        raise RuntimeError("Не удалось обработать медиа. Результат не получен.")
    return output


def validate_logo(path: Path, max_mb: int | None = None) -> tuple[bool, str]:
    """Validate logo file; messages are safe to show to Telegram users."""
    max_mb = max_mb or MAX_WATERMARK_MB
    try:
        size = path.stat().st_size
    except OSError as e:
        logger.warning("validate_logo cannot stat %s: %s", path, e)
        return False, "Не удалось прочитать файл логотипа."
    if size > max_mb * 1024 * 1024:
        return False, f"Логотип слишком большой (макс. {max_mb} МБ)."
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(path),
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        logger.warning("validate_logo probe failed for %s: %s", path, (proc.stderr or "")[:500])
        return False, "Некорректный файл изображения."
    dims = proc.stdout.strip()
    try:
        w, h = map(int, dims.split("x", 1))
    except ValueError:
        logger.warning("validate_logo unexpected dimensions %r for %s", dims, path)
        return False, "Некорректный файл изображения."
    if w > MAX_WATERMARK_PX or h > MAX_WATERMARK_PX:
        return False, f"Изображение слишком большое (макс. {MAX_WATERMARK_PX}×{MAX_WATERMARK_PX} px)."
    return True, ""
