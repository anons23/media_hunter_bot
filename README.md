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

### Quality choice for big links

Before downloading a single link the bot reads the format list from yt-dlp (no
download, ~2 s). If the default 1080p pick is larger than
`MAX_SOURCE_DOWNLOAD_MB`, the user gets buttons with lower qualities that fit
(720p/480p/… with an estimated size). The chosen quality is downloaded as is,
without re-encoding. When the size is only a rough estimate (HLS streams), a
"try the best quality" button is offered too; the download still enforces the
real limit. Playlist items and uploaded files are not affected
(`media_hunter_bot/quality.py`).

The 100 MB value is the logical unique-processing threshold, not the Telegram transport limit. A local Telegram Bot API can accept larger files according to its configured capabilities.

### Small VPS (1 CPU, 4 GB RAM, 10 GB disk)

- New jobs are refused while free disk space is below `MIN_FREE_DISK_MB` (+ the job's own needs) with a friendly "server is busy" message.
- Sources are capped at 700 MB and `MAX_VIDEO_MINUTES` (30); over-long links are skipped before downloading.
- Temporary files are cleaned every 15 min (every hour-old file when the disk is low); with `LOCAL_BOT_API_DIR` set, the bot also cleans the local Bot API server's files, which that server never deletes.
- ffmpeg / yt-dlp run with `nice`/`ionice`, so buttons stay responsive during encodes.
- One-time server setup (swap, log limits, auto-restart): `sudo bash deploy/server_setup.sh`.

### Mini App editors (plate and text watermark)

The bot serves two Telegram Mini Apps from its own process: the plate editor
(`/`) — drag, resize, opacity, when it appears/disappears, fade — and the text
watermark editor (`/text`) — text, 15 bundled Cyrillic fonts, colour palette,
shadow / outline / background box, ready-made styles, drag and resize.
Telegram opens Mini Apps only over HTTPS:

1. Point a (sub)domain to the VPS, e.g. `app.example.com`.
2. nginx + Let's Encrypt:

```nginx
server {
    server_name app.example.com;
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
    }
    listen 80;
}
```
```bash
sudo certbot --nginx -d app.example.com
```
3. In `.env`: `WEBAPP_URL=https://app.example.com` and restart the bot.

Without `WEBAPP_URL` the bot keeps the old button-based settings. Every API
call is checked with Telegram `initData` (HMAC of the bot token), so users can
only edit their own plates/texts and their own channels.

Fonts live in `media_hunter_bot/fonts` (OFL, licences in `fonts/licenses`);
rebuild them with `tools/build_fonts.py` from a google/fonts checkout.

### Keeping yt-dlp fresh

Sites change often and old yt-dlp versions stop downloading. Update it about once a week:

```bash
cd /opt/mediahunter/app && .venv/bin/pip install -U yt-dlp && systemctl restart media-hunter.service
```

or via cron: `0 5 * * 1 cd /opt/mediahunter/app && .venv/bin/pip install -qU yt-dlp && systemctl restart media-hunter.service`.

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
