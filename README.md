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
- over **100 MB**: never unique-processed:
  - **100–130 MB** (`ORIGINAL_SEND_MAX_MB`): the original is sent as is (non-MP4 is only remuxed to MP4, no re-encode);
  - **over 130 MB**: gentle quality-first compression — H.264 `-crf 22 -preset veryfast` (`OVERSIZE_CRF`, `OVERSIZE_PRESET`), resolution kept, only sources above 1080p (short side, `OVERSIZE_MAX_SIDE`) are downscaled to 1080p, AAC/MP3 audio copied untouched (other codecs → AAC 192k). If re-encoding does not shrink the file, the original is sent. Timeout scales with duration (30 min … 6 h);
  - results are sent through the local Bot API up to `TELEGRAM_MAX_UPLOAD_MB` (2000 MB); send request timeout scales with file size;
- source/user uploads are capped at **1024 MB (1 GB)** by default.

The 100 MB value is the logical unique-processing threshold, not the Telegram transport limit. A local Telegram Bot API can accept larger files according to its configured capabilities.

### SSRF / network isolation

`validate_source_url()` is defense in depth only:
- allows only HTTP/HTTPS;
- rejects credential-bearing URLs;
- rejects known local/internal hostnames (`localhost`, `metadata`, `*.local`, `*.internal`, …);
- rejects non-global literal IPs;
- resolves the hostname and rejects any non-global address.

This is **not** a complete guarantee against DNS rebinding or redirect-to-internal attacks, because `yt-dlp` performs its own network resolution and may follow redirects in a subprocess.

**Production requirement:** run the bot under a dedicated unprivileged system user and apply outbound (egress) firewall rules that block private, loopback and link-local destinations for that user. Do not run the bot as root. Without egress isolation a rebinding or redirect result can still reach internal services.

### Temporary files

Downloaded and processed media is stored temporarily under `MEDIA_DIR`. Job cleanup removes its working directory after processing, including after successful delivery. The periodic cleaner is a second safety net for abandoned files.

V3 security verification should be run after changes to the branch.
