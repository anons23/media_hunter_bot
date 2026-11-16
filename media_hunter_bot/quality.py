"""Quality choice for link downloads that exceed the source size limit.

Before downloading a single (non-playlist) link the bot asks yt-dlp for the
format list (no download). If the default 1080p selection would be larger than
MAX_SOURCE_DOWNLOAD_MB, the user gets buttons with lower qualities that fit,
each with an estimated size. Picking one queues the link again with that height
cap; the download then simply fetches the smaller stream (no re-encoding).

Only links are covered. Uploaded files are what they are.
"""
from __future__ import annotations

import json
import logging
import secrets
import subprocess
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass

from .config import COOKIES_PATH, MAX_SOURCE_DOWNLOAD_MB

logger = logging.getLogger(__name__)

DEFAULT_HEIGHT = 1080
CHOICE_HEIGHTS = (720, 480, 360, 240, 144)
# Estimates are approximate; offer only qualities that fit with some margin.
FIT_RATIO = 0.95
PENDING_TTL_S = 3600
CHOICE_TTL_S = 3600
_MB = 1024 * 1024

# Height cap for the current download (set by the job, read by processor.download).
MAX_HEIGHT: ContextVar[int | None] = ContextVar("quality_max_height", default=None)


def format_selector(max_height: int | None) -> str:
    """yt-dlp -f expression. The default keeps the historical selector."""
    if not max_height or max_height >= DEFAULT_HEIGHT:
        return "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best"
    h = int(max_height)
    return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best[height<={h}]"


# --------------------------------------------------------------------------- size estimation

def _size(fmt: dict, duration: float) -> tuple[int, bool] | None:
    """(bytes, exact?) — HLS/m3u8 streams only have a rough filesize_approx."""
    value = fmt.get("filesize")
    if isinstance(value, (int, float)) and value > 0:
        return int(value), True
    value = fmt.get("filesize_approx")
    if isinstance(value, (int, float)) and value > 0:
        return int(value), False
    tbr = fmt.get("tbr")
    if isinstance(tbr, (int, float)) and tbr > 0 and duration > 0:
        return int(tbr * 1000 / 8 * duration), False
    return None


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _has(fmt: dict, key: str) -> bool:
    value = fmt.get(key)
    return bool(value) and value != "none"


def estimate(info: dict, max_height: int) -> tuple[int, int] | None:
    """(estimated bytes, real height) of what format_selector(max_height) picks."""
    found = _estimate(info, max_height)
    return (found[0], found[1]) if found else None


def _estimate(info: dict, max_height: int) -> tuple[int, int, bool] | None:
    """(estimated bytes, real height, exact?) of what format_selector picks.

    yt-dlp returns ``formats`` sorted from worst to best by its own preference
    (resolution, fps, codec: AV1 > VP9 > H.264, …), and "best…" in a selector
    means the last matching entry. Mirroring that order matters: an AV1 1080p
    stream is often half the size of the H.264 one.
    """
    formats = [f for f in (info.get("formats") or []) if isinstance(f, dict)]
    duration = _num(info.get("duration"))
    videos = [
        f for f in formats
        if _has(f, "vcodec") and not _has(f, "acodec") and f.get("ext") == "mp4"
        and 0 < _num(f.get("height")) <= max_height
    ]
    audios = [f for f in formats if _has(f, "acodec") and not _has(f, "vcodec") and f.get("ext") == "m4a"]
    if videos and audios:
        video, audio = videos[-1], audios[-1]
        vs, as_ = _size(video, duration), _size(audio, duration)
        if vs is None or as_ is None:
            return None
        return vs[0] + as_[0], int(_num(video.get("height"))), vs[1] and as_[1]
    combined = [
        f for f in formats
        if _has(f, "vcodec") and _has(f, "acodec") and 0 < _num(f.get("height")) <= max_height
    ]
    if not combined:
        return None
    mp4 = [f for f in combined if f.get("ext") == "mp4"]
    best = (mp4 or combined)[-1]
    size = _size(best, duration)
    return (size[0], int(_num(best.get("height"))), size[1]) if size is not None else None


# A rough (non-exact) size may be well above the real one (YouTube HLS streams
# came out ~2x too big). Up to this factor over the limit the user may still
# try the best quality; the download itself enforces the real limit.
APPROX_TRY_FACTOR = 2.0


@dataclass
class Plan:
    best_mb: int
    options: list[tuple[int, int]]  # (height, estimated MB), highest first
    try_best: int | None = None  # height of the best quality worth trying anyway


def plan(info: dict, limit_mb: int = MAX_SOURCE_DOWNLOAD_MB) -> Plan | None:
    """None when no choice is needed (fits, or size unknown)."""
    found = _estimate(info, DEFAULT_HEIGHT)
    if found is None or found[0] <= limit_mb * _MB:
        return None
    best = found[:2]
    try_best = found[1] if not found[2] and found[0] <= limit_mb * _MB * APPROX_TRY_FACTOR else None
    options: list[tuple[int, int]] = []
    seen: set[int] = set()
    for h in CHOICE_HEIGHTS:
        if h >= best[1]:
            continue
        est = estimate(info, h)
        if est is None or est[1] in seen or est[1] >= best[1]:
            continue
        seen.add(est[1])
        if est[0] <= limit_mb * _MB * FIT_RATIO:
            options.append((est[1], max(1, round(est[0] / _MB))))
    return Plan(max(1, round(best[0] / _MB)), options, try_best)


def probe(url: str) -> dict | None:
    """Format list without downloading. None if yt-dlp fails (then no choice)."""
    cmd = ["yt-dlp", "-J", "--no-playlist", "--no-warnings", "--skip-download", url]
    if COOKIES_PATH.exists():
        cmd[1:1] = ["--cookies", str(COOKIES_PATH)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("_type") == "playlist":
        return None
    return data


# --------------------------------------------------------------------------- pending choices

_lock = threading.Lock()
_pending: dict[str, tuple[int, str, float]] = {}   # token -> (uid, url, created)
_chosen: dict[tuple[int, str], tuple[int, float]] = {}  # (uid, url) -> (height, created)


def _prune(now: float) -> None:
    for token, (_, _, created) in list(_pending.items()):
        if now - created > PENDING_TTL_S:
            _pending.pop(token, None)
    for key, (_, created) in list(_chosen.items()):
        if now - created > CHOICE_TTL_S:
            _chosen.pop(key, None)


def offer(uid: int, url: str) -> str:
    """Remember the link waiting for a quality choice; returns a short token."""
    now = time.time()
    token = secrets.token_hex(4)
    with _lock:
        _prune(now)
        _pending[token] = (uid, url, now)
    return token


def take_offer(token: str, uid: int) -> str | None:
    """URL for this user's pending choice (one-shot)."""
    with _lock:
        _prune(time.time())
        item = _pending.get(token)
        if not item or item[0] != uid:
            return None
        _pending.pop(token, None)
        return item[1]


def remember_choice(uid: int, url: str, height: int) -> None:
    with _lock:
        _chosen[(uid, url)] = (int(height), time.time())


def forget_choice(uid: int, url: str) -> None:
    with _lock:
        _chosen.pop((uid, url), None)


def take_choice(uid: int, url: str) -> int | None:
    with _lock:
        _prune(time.time())
        item = _chosen.pop((uid, url), None)
    return item[0] if item else None


def needs_choice(p: Plan) -> bool:
    return bool(p.options or p.try_best)


def choice_text(p: Plan) -> str:
    if not needs_choice(p):
        return (
            f"Видео слишком большое: ~{p.best_mb} МБ, максимум {MAX_SOURCE_DOWNLOAD_MB} МБ. "
            "Даже в низком качестве оно не помещается в лимит."
        )
    text = f"⚠️ В лучшем качестве видео весит ~{p.best_mb} МБ — это больше лимита {MAX_SOURCE_DOWNLOAD_MB} МБ.\n"
    if p.try_best:
        text += "Размер оценён неточно — можно попробовать скачать как есть или выбрать качество поменьше:"
    else:
        text += "Выберите качество поменьше (размер примерный):"
    return text


def choice_rows(token: str, p: Plan) -> list[list[tuple[str, str]]]:
    """Button rows as (text, callback_data); handlers turn them into a keyboard."""
    rows = []
    if p.try_best:
        rows.append([(f"🎲 Попробовать {p.try_best}p", f"q:{token}:{p.try_best}")])
    rows += [[(f"{h}p (~{mb} МБ)", f"q:{token}:{h}")] for h, mb in p.options]
    rows.append([("✖️ Отмена", f"q:{token}:x")])
    return rows
