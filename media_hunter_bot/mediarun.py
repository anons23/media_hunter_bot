"""Running ffmpeg / yt-dlp on a weak server.

* Children run with ``nice`` (and ``ionice`` when available) so the bot's
  event loop keeps answering buttons while a video is being encoded.
* ffmpeg progress (``-progress pipe:1``) is parsed and forwarded to the
  current job's progress sink (a ContextVar copied into worker threads by
  ``asyncio.to_thread``), which updates the "Обработка 47%" message.
* Disk-space helpers used to refuse jobs before the disk fills up.
"""
from __future__ import annotations

import collections
import contextvars
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import LOW_PRIORITY_MEDIA

# Called with a fraction 0..1 from worker threads; must be thread-safe.
progress_sink: contextvars.ContextVar[Callable[[float], None] | None] = contextvars.ContextVar(
    "media_hunter_progress_sink", default=None
)

_NICE = shutil.which("nice")
_IONICE = shutil.which("ionice")


def low_priority(cmd: list[str]) -> list[str]:
    """Prefix a command with nice/ionice when enabled and available."""
    if not LOW_PRIORITY_MEDIA or os.name != "posix":
        return list(cmd)
    prefix: list[str] = []
    if _IONICE:
        prefix += [_IONICE, "-c", "2", "-n", "7"]
    if _NICE:
        prefix += [_NICE, "-n", "10"]
    return prefix + list(cmd)


def report_progress(fraction: float) -> None:
    sink = progress_sink.get()
    if sink is not None:
        try:
            sink(max(0.0, min(1.0, fraction)))
        except Exception:
            pass


def with_progress(cmd: list[str]) -> list[str]:
    """Ask ffmpeg to print machine-readable progress to stdout."""
    if not cmd or Path(cmd[0]).name != "ffmpeg" or "-progress" in cmd:
        return list(cmd)
    return [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]


def run_ffmpeg(
    cmd: list[str],
    register: Callable[[Any], None],
    timeout: float,
    duration: float = 0.0,
) -> tuple[int, str, bool]:
    """Run ffmpeg with progress reporting.

    Returns (returncode, stderr tail, timed_out).
    """
    full = low_priority(with_progress(cmd))
    tail: collections.deque[str] = collections.deque(maxlen=60)
    timed_out = threading.Event()
    with subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace") as proc:
        register(proc)

        def drain_stderr() -> None:
            for line in proc.stderr:  # type: ignore[union-attr]
                tail.append(line)

        def kill_on_timeout() -> None:
            if proc.poll() is None:
                timed_out.set()
                proc.kill()

        err_thread = threading.Thread(target=drain_stderr, daemon=True)
        err_thread.start()
        timer = threading.Timer(timeout, kill_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            last = 0.0
            for line in proc.stdout:  # type: ignore[union-attr]
                if duration > 0 and line.startswith("out_time_us="):
                    try:
                        done = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    now = time.monotonic()
                    if now - last >= 1.0:
                        last = now
                        report_progress(done / duration)
            proc.wait()
        finally:
            timer.cancel()
            err_thread.join(timeout=5)
            register(None)
    return proc.returncode, "".join(tail)[-2000:], timed_out.is_set()


def free_disk_mb(path: Path) -> int:
    """Free space of the filesystem holding ``path`` (nearest existing parent)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return int(shutil.disk_usage(p).free / (1024 * 1024))
    except OSError:
        return 1 << 30


def cleanup_bot_api_dir(root: str, ttl_minutes: int) -> int:
    """Delete files older than the TTL inside a telegram-bot-api --dir.

    The local Bot API server keeps every downloaded/uploaded file forever.
    Only regular files under ``<dir>/<bot token>/<kind>/`` are touched.
    """
    base = Path(root)
    if not root or not base.is_dir():
        return 0
    cutoff = time.time() - ttl_minutes * 60
    removed = 0
    for token_dir in base.iterdir():
        if not token_dir.is_dir() or ":" not in token_dir.name:
            continue
        for fp in token_dir.rglob("*"):
            try:
                if fp.is_file() and not fp.is_symlink() and fp.stat().st_mtime < cutoff:
                    fp.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


def remove_bot_api_file(root: str, file_path: str | None) -> None:
    """Delete one file of the local Bot API server once the bot has a copy."""
    if not root or not file_path:
        return
    try:
        p = Path(file_path).resolve()
        p.relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass
