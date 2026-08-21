# Media Hunter Bot

## Media Hunter 3.0

Telegram bot for downloading, processing and autoposting media.

### Requirements
- Python 3.11+
- FFmpeg / ffprobe
- `yt-dlp`
- Optional local `telegram-bot-api`

### Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r media_hunter_bot/requirements.txt
cp .env.example .env
python main.py
```

`LOCAL_BOT_API` is optional. If it is empty, the bot uses the official Telegram Bot API.

The default media/upload logical limit is 49 MB.
