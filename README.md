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

### Media size policy

With the default configuration:
- up to **80 MB**: process/unique without forced compression;
- **80–100 MB**: process, then use a compressed fallback if necessary;
- over **100 MB** and up to the source safety limit: send the original without unique processing;
- source/user uploads are capped at **1536 MB (1.5 GB)** by default.

The 100 MB value is the logical unique-processing threshold, not the Telegram transport limit. A local Telegram Bot API can accept larger files according to its configured capabilities.

### SSRF / network isolation

`validate_source_url()` rejects non-HTTP(S), credential-bearing and locally resolved/private/link-local targets. This is defense in depth, not a complete guarantee against DNS rebinding because `yt-dlp` performs its own network resolution in a subprocess.

For production, run the bot under a dedicated unprivileged system user and apply outbound (egress) firewall rules that block private, loopback and link-local destinations for that user. Do not run the bot as root. This prevents a DNS-rebinding result from reaching internal services even if the hostname changes after application-level validation.

### Temporary files

Downloaded and processed media is stored temporarily under `MEDIA_DIR`. Job cleanup removes its working directory after processing, including after successful delivery. The periodic cleaner is a second safety net for abandoned files.

V3 security verification should be run after changes to the branch.
