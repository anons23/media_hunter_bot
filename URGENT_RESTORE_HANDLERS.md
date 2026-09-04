# URGENT: handlers.py was overwritten with PLACEHOLDER

## What already landed on the branch (good)
- `media_hunter_bot/progress.py` — stage label `Обработка`
- `media_hunter_bot/logo_upload_fix.py` — no double-answer on documents
- `media_hunter_bot/oversize_processor.py` — watermark fallback + 720/480 downscale
- `patches/remove_legacy_logo_handlers.patch` — removes `wmlogo`/`logovalue`/`S.logo`

## Broken right now
- `media_hunter_bot/handlers.py` is the literal string `PLACEHOLDER` (accidental write during push).

## Restore on VPS (run this now)

```bash
cd /opt/mediahunter/app
git fetch origin
# 1) restore full handlers from last good commit before PLACEHOLDER
git show 6491a9a90b3e1fac6fad5a91508ce7f4b70efbf4:media_hunter_bot/handlers.py > media_hunter_bot/handlers.py
# 2) apply logo silence fix
patch -p1 < patches/remove_legacy_logo_handlers.patch
# 3) sanity
grep -n 'async def wmlogo\|async def logovalue\|PLACEHOLDER' media_hunter_bot/handlers.py || echo 'OK: legacy logo handlers gone'
# 4) pull other fixes if needed and restart
git checkout origin/Media_hanter-v3-security -- media_hunter_bot/progress.py media_hunter_bot/logo_upload_fix.py media_hunter_bot/oversize_processor.py
systemctl restart media-hunter.service
systemctl status media-hunter.service --no-pager -l
```

## After restore smoke
1. Logo: open watermark → logo → send **gallery photo** → settings → save.
2. >100 MB URL: must compress (possibly without watermark on fallback) and send under 100 MB.
