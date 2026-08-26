"""User-facing error messages without internal diagnostics leakage."""
from __future__ import annotations


def user_facing_error(exc: BaseException) -> str:
    """Map exceptions to safe Russian text for Telegram users.

    Controlled RuntimeError/ValueError messages (limits, download/process
    failures authored in processor/handlers) are shown as-is.
    Technical stderr, paths and tool diagnostics never reach users.
    """
    if not isinstance(exc, (RuntimeError, ValueError)):
        return "Не удалось обработать медиа. Попробуйте другую ссылку или позже."
    text = str(exc).strip()
    if not text or len(text) > 300:
        return "Не удалось обработать медиа. Попробуйте другую ссылку или позже."
    lowered = text.lower()
    forbidden = (
        "ffmpeg",
        "yt-dlp",
        "ytdlp",
        "ffprobe",
        "stderr",
        "traceback",
        "errno",
        "permission denied",
        "no such file",
        'file "',
        "line ",
        "calledprocesserror",
        "timeoutexpired",
    )
    if any(s in lowered for s in forbidden):
        return "Не удалось обработать медиа. Попробуйте другую ссылку или позже."
    # Block absolute/relative path hints
    if "/" in text or "\\" in text or ":\\" in text:
        return "Не удалось обработать медиа. Попробуйте другую ссылку или позже."
    return text
