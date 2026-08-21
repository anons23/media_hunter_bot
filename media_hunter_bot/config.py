"""Конфигурация Media Hunter Bot.

Все чувствительные значения читаются из переменных окружения.
Для локального запуска создайте файл .env рядом с ботом.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Base directories ────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("MEDIA_HUNTER_HOME", "/root/media_hunter_bot"))
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"
LOGO_DIR = DATA_DIR / "logos"
DB_PATH = DATA_DIR / "media_hunter.sqlite3"
COOKIES_PATH = Path(os.getenv("YTDLP_COOKIES", str(DATA_DIR / "cookies.txt")))

# ── Telegram ────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
LOCAL_BOT_API = os.getenv("LOCAL_BOT_API", "http://127.0.0.1:8081")

# ── Limits ──────────────────────────────────────────────────────────────────
MAX_URL_LOGICAL_MB = int(os.getenv("MAX_URL_LOGICAL_MB", "49"))
MAX_USER_UPLOAD_MB = int(os.getenv("MAX_USER_UPLOAD_MB", "49"))
MAX_WATERMARK_MB = int(os.getenv("MAX_WATERMARK_MB", "5"))
MAX_WATERMARK_PX = int(os.getenv("MAX_WATERMARK_PX", "2000"))

# ── Engine tuning (optimised for 1 vCPU / 4 GB RAM) ─────────────────────────
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
MAX_PLAYLIST_ITEMS = int(os.getenv("MAX_PLAYLIST_ITEMS", "50"))
CLEANER_AGE_HOURS = int(os.getenv("CLEANER_AGE_HOURS", "12"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "100"))

# ── Premium plans (days: stars) ─────────────────────────────────────────────
PREMIUM_PLANS: dict[int, int] = {
    30: 150,
    60: 285,
    90: 405,
    180: 720,
}

# ── Ensure directories exist ────────────────────────────────────────────────
for p in (DATA_DIR, MEDIA_DIR, LOGO_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ── Validation ──────────────────────────────────────────────────────────────
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured. Set the BOT_TOKEN environment variable.")
if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID is not configured. Set the ADMIN_ID environment variable.")
