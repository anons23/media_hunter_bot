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

# TeleAds ad network (teleads.pro). SDK key from the TeleAds dashboard;
# empty disables ads. Ads are delivered by TeleAds itself via the bot token.
TELEADS_SDK_KEY = os.getenv("TELEADS_SDK_KEY", "").strip()

# Telegram Mini App (plate editor). Public HTTPS base URL, e.g.
# https://app.example.com — empty disables the Mini App (button settings
# are used instead). The bot serves it on WEBAPP_HOST:WEBAPP_PORT behind
# an HTTPS reverse proxy (nginx).
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8090"))
# Plate (logo) upload limits.
MAX_LOGO_GIF_MB = int(os.getenv("MAX_LOGO_GIF_MB", "10"))
MAX_LOGO_GIF_SECONDS = float(os.getenv("MAX_LOGO_GIF_SECONDS", "15"))

# Weak-server protection (1 CPU / small disk).
# Free disk space that must remain after a job; new jobs are refused below it.
MIN_FREE_DISK_MB = int(os.getenv("MIN_FREE_DISK_MB", "1500"))
# Longest video the bot processes (0 = no limit).
MAX_VIDEO_MINUTES = float(os.getenv("MAX_VIDEO_MINUTES", "30"))
# How often temporary files are cleaned, minutes.
CLEANER_INTERVAL_MIN = max(5, int(os.getenv("CLEANER_INTERVAL_MIN", "15")))
# Working dir of the local telegram-bot-api server (its --dir). When set, the
# bot deletes files it no longer needs there (the server never does).
LOCAL_BOT_API_DIR = os.getenv("LOCAL_BOT_API_DIR", "").strip()
LOCAL_BOT_API_FILE_TTL_MIN = max(10, int(os.getenv("LOCAL_BOT_API_FILE_TTL_MIN", "60")))
# Run ffmpeg / yt-dlp with lower CPU priority so the bot stays responsive.
LOW_PRIORITY_MEDIA = os.getenv("LOW_PRIORITY_MEDIA", "1").strip() not in {"0", "false", "no"}

# Media policy:
#   <= SOFT_UNIQUE_SIZE_MB: unique without forced compression.
#   SOFT_UNIQUE_SIZE_MB..MAX_UNIQUE_SIZE_MB: unique with compression to the
#       soft target (80 MB by default).
#   > MAX_UNIQUE_SIZE_MB: never unique-processed:
#       MAX_UNIQUE_SIZE_MB..ORIGINAL_SEND_MAX_MB: send the original as is;
#       > ORIGINAL_SEND_MAX_MB: gentle quality-preserving compression (CRF).
# MAX_SOURCE_DOWNLOAD_MB is the absolute source-size safety limit.
SOFT_UNIQUE_SIZE_MB = int(os.getenv("SOFT_UNIQUE_SIZE_MB", "80"))
MAX_UNIQUE_SIZE_MB = int(os.getenv("MAX_UNIQUE_SIZE_MB", "100"))
# Send ceiling for results of the <= MAX_UNIQUE_SIZE_MB unique pipeline.
MAX_SEND_MB = int(os.getenv("MAX_SEND_MB", str(MAX_UNIQUE_SIZE_MB)))
ORIGINAL_SEND_MAX_MB = int(os.getenv("ORIGINAL_SEND_MAX_MB", "130"))
# Hard upload ceiling of the local Telegram Bot API server (oversize results).
TELEGRAM_MAX_UPLOAD_MB = int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "2000"))
OVERSIZE_CRF = int(os.getenv("OVERSIZE_CRF", "22"))
OVERSIZE_PRESET = os.getenv("OVERSIZE_PRESET", "veryfast").strip() or "veryfast"
OVERSIZE_THREADS = max(0, int(os.getenv("OVERSIZE_THREADS", "0")))  # 0 = auto
OVERSIZE_MAX_SIDE = int(os.getenv("OVERSIZE_MAX_SIDE", "1080"))  # short-side cap, px; 0 = keep
OVERSIZE_AUDIO_BITRATE = os.getenv("OVERSIZE_AUDIO_BITRATE", "192k").strip() or "192k"
MAX_SOURCE_DOWNLOAD_MB = max(
    MAX_UNIQUE_SIZE_MB,
    int(os.getenv("MAX_SOURCE_DOWNLOAD_MB", "700")),
)
# Compatibility alias: the unique-processing ceiling is 100 MB, not 1.5 GB.
# Do not make this an independent configurable limit.
MAX_URL_LOGICAL_MB = MAX_UNIQUE_SIZE_MB
MAX_USER_UPLOAD_MB = int(os.getenv("MAX_USER_UPLOAD_MB", str(MAX_SOURCE_DOWNLOAD_MB)))
MAX_WATERMARK_MB = int(os.getenv("MAX_WATERMARK_MB", "5"))
MAX_WATERMARK_PX = int(os.getenv("MAX_WATERMARK_PX", "2000"))

MAX_CONCURRENT = max(1, int(os.getenv("MAX_CONCURRENT", "1")))
MAX_PLAYLIST_ITEMS = max(1, int(os.getenv("MAX_PLAYLIST_ITEMS", "40")))
CLEANER_AGE_HOURS = max(1, int(os.getenv("CLEANER_AGE_HOURS", "12")))
MAX_QUEUE_SIZE = max(1, int(os.getenv("MAX_QUEUE_SIZE", "100")))
MAX_USER_QUEUE = max(1, int(os.getenv("MAX_USER_QUEUE", "10")))

# Subscription policy.
FREE_MAX_CHANNELS = 1
PREMIUM_MAX_CHANNELS = 3
FREE_PLAYLIST_MAX_VIDEOS = 20
PREMIUM_PLAYLIST_MAX_VIDEOS = 40
FREE_PLAYLISTS_PER_MONTH = 3

if not 1 <= SOFT_UNIQUE_SIZE_MB <= MAX_UNIQUE_SIZE_MB:
    raise ValueError("SOFT_UNIQUE_SIZE_MB must be between 1 and MAX_UNIQUE_SIZE_MB")
if MAX_SOURCE_DOWNLOAD_MB < MAX_UNIQUE_SIZE_MB:
    raise ValueError("MAX_SOURCE_DOWNLOAD_MB must be >= MAX_UNIQUE_SIZE_MB")
if MAX_USER_UPLOAD_MB < MAX_UNIQUE_SIZE_MB:
    raise ValueError("MAX_USER_UPLOAD_MB must be >= MAX_UNIQUE_SIZE_MB")
if MAX_SEND_MB < 1:
    raise ValueError("MAX_SEND_MB must be >= 1")
if ORIGINAL_SEND_MAX_MB < MAX_UNIQUE_SIZE_MB:
    raise ValueError("ORIGINAL_SEND_MAX_MB must be >= MAX_UNIQUE_SIZE_MB")
if TELEGRAM_MAX_UPLOAD_MB < ORIGINAL_SEND_MAX_MB:
    raise ValueError("TELEGRAM_MAX_UPLOAD_MB must be >= ORIGINAL_SEND_MAX_MB")
if not 0 <= OVERSIZE_CRF <= 51:
    raise ValueError("OVERSIZE_CRF must be between 0 and 51")
if OVERSIZE_PRESET not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}:
    raise ValueError("OVERSIZE_PRESET must be a libx264 preset name")
if OVERSIZE_MAX_SIDE < 0:
    raise ValueError("OVERSIZE_MAX_SIDE must be >= 0")
if MAX_URL_LOGICAL_MB != MAX_UNIQUE_SIZE_MB:
    raise ValueError("MAX_URL_LOGICAL_MB must equal MAX_UNIQUE_SIZE_MB")

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
