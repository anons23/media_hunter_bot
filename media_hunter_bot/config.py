"""Configuration for Media Hunter Bot.

Importing this module is side-effect free: secrets are validated and runtime
folders are created by the application entry point.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(os.getenv("MEDIA_HUNTER_HOME", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"
LOGO_DIR = DATA_DIR / "logos"
DB_PATH = DATA_DIR / "media_hunter.sqlite3"
COOKIES_PATH = Path(os.getenv("YTDLP_COOKIES", str(DATA_DIR / "cookies.txt"))).expanduser()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

LOCAL_BOT_API = os.getenv("LOCAL_BOT_API", "").strip()

# Media policy:
#   MAX_URL_LOGICAL_MB: largest source that still gets normal unique processing.
#   MAX_SEND_MB: output-size threshold that triggers the compressed fallback.
# MAX_SOURCE_DOWNLOAD_MB is the absolute source-size safety limit.
SOFT_UNIQUE_SIZE_MB = int(os.getenv("SOFT_UNIQUE_SIZE_MB", "80"))
# Kept for compatibility with existing deployments/configuration.
MAX_UNIQUE_SIZE_MB = int(os.getenv("MAX_UNIQUE_SIZE_MB", "100"))
MAX_SEND_MB = int(os.getenv("MAX_SEND_MB", str(MAX_UNIQUE_SIZE_MB)))
MAX_SOURCE_DOWNLOAD_MB = max(
    MAX_UNIQUE_SIZE_MB,
    int(os.getenv("MAX_SOURCE_DOWNLOAD_MB", "1536")),
)
# The logical unique-processing limit is intentionally independent from the
# send threshold. Default: 1.5 GiB.
MAX_URL_LOGICAL_MB = int(os.getenv("MAX_URL_LOGICAL_MB", "1536"))
MAX_USER_UPLOAD_MB = max(
    MAX_SOURCE_DOWNLOAD_MB,
    int(os.getenv("MAX_USER_UPLOAD_MB", str(MAX_SOURCE_DOWNLOAD_MB))),
)
MAX_WATERMARK_MB = int(os.getenv("MAX_WATERMARK_MB", "5"))
MAX_WATERMARK_PX = int(os.getenv("MAX_WATERMARK_PX", "2000"))

MAX_CONCURRENT = max(1, int(os.getenv("MAX_CONCURRENT", "1")))
MAX_PLAYLIST_ITEMS = max(1, int(os.getenv("MAX_PLAYLIST_ITEMS", "50")))
CLEANER_AGE_HOURS = max(1, int(os.getenv("CLEANER_AGE_HOURS", "12")))
MAX_QUEUE_SIZE = max(1, int(os.getenv("MAX_QUEUE_SIZE", "100")))
MAX_USER_QUEUE = max(1, int(os.getenv("MAX_USER_QUEUE", "10")))

if not 1 <= SOFT_UNIQUE_SIZE_MB <= MAX_UNIQUE_SIZE_MB:
    raise ValueError("SOFT_UNIQUE_SIZE_MB must be between 1 and MAX_UNIQUE_SIZE_MB")
if MAX_SOURCE_DOWNLOAD_MB < MAX_UNIQUE_SIZE_MB:
    raise ValueError("MAX_SOURCE_DOWNLOAD_MB must be >= MAX_UNIQUE_SIZE_MB")
if MAX_USER_UPLOAD_MB < MAX_UNIQUE_SIZE_MB:
    raise ValueError("MAX_USER_UPLOAD_MB must be >= MAX_UNIQUE_SIZE_MB")
if MAX_SEND_MB < 1:
    raise ValueError("MAX_SEND_MB must be >= 1")
if MAX_URL_LOGICAL_MB < 1 or MAX_URL_LOGICAL_MB > MAX_SOURCE_DOWNLOAD_MB:
    raise ValueError("MAX_URL_LOGICAL_MB must be between 1 and MAX_SOURCE_DOWNLOAD_MB")

PREMIUM_PLANS: dict[int, int] = {
    30: 150,
    60: 285,
    90: 405,
    180: 720,
}


def ensure_directories() -> None:
    for p in (DATA_DIR, MEDIA_DIR, LOGO_DIR):
        p.mkdir(parents=True, exist_ok=True)


def validate() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured. Set BOT_TOKEN in the environment or .env file.")
    if ADMIN_ID == 0:
        raise RuntimeError("ADMIN_ID is not configured or invalid.")
