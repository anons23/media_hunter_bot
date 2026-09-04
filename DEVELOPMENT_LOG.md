# Media Hunter — журнал разработки и передачи контекста

> Единая точка правды для продолжения проекта другим ИИ.
> Рабочая ветка: `Media_hanter-v3-security`.
> Журнал хранится в GitHub и не копируется на VPS.

## Правила
1. Всегда работать в `Media_hanter-v3-security`.
2. Перед правкой читать журнал и проверять текущий код.
3. Не менять архитектуру без необходимости.
4. После каждой правки кода запускать CI/тесты.
5. После правки дописывать сюда что изменено, почему, CI-результат и что осталось `⬜`.
6. Серверные изменения сначала `⬜`, после фактической проверки `✅`.
7. Не записывать секреты, токены, пароли или `.env`.

## Production
- Python + aiogram 3.x + yt-dlp + FFmpeg + SQLite.
- VPS: `/opt/mediahunter/app`.
- Python: `/opt/mediahunter/venv/bin/python`.
- Service: `media-hunter.service`.
- Local Bot API: `127.0.0.1:8081`.
- DB path: `data/media_hunter.sqlite3`, фактический путь учитывает `MEDIA_HUNTER_HOME`.
- Source/upload absolute limit: 1024 MB.
- **Все видео <=100 MB обязательно уникализируются.**
- Видео >100 MB проходят compression-only и не получают искусственную uniqueness.

## Безопасность / базовая логика
- ✅ SSRF `validate_source_url`; остаточный DNS rebinding/redirect risk mitigated unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Queue/restart race через `asyncio.Lock`, корректный accounting и `task_done()`.
- ✅ Restart/shutdown завершают subprocess и чистят временные файлы.
- ✅ Upload проверяет очередь до скачивания Telegram-файла.
- ✅ Payment activation атомарна; `telegram_charge_id` unique.
- ✅ Referral assignment через `AND referred_by IS NULL`.
- ✅ OPP private invite fail-closed.
- ✅ User-facing ошибки через `user_errors.py`.
- ✅ `download()` использует `--write-info-json`.
- ✅ `safe_media_filename()` сохраняет исходное название.

## FFmpeg / уникализация
- VPS FFmpeg 6.1.1.
- Старый fractional scale давал нечётные размеры и `ffmpeg failed (code=187)` / `width not divisible by 2`.
- ✅ Safe even-dimension filter: `trunc(iw*0.998/2)*2` / `trunc(ih*0.998/2)*2`.
- ✅ `optimized_processor.py`: лёгкий `eq`, без `unsharp`/`noise`, `-threads 2`, preset `superfast`, CRF 27 для обычной uniqueness, CRF 30 для compression.
- ✅ `process_media()` создаёт `work_dir` до FFmpeg.

## Local Bot API / logo
- ✅ `TelegramAPIServer.from_base()` patched in `media_hunter_bot/__init__.py` to default `is_local=True`.
- Причина: Local Bot API отдаёт абсолютный filesystem path; без local mode aiogram строил HTTP `/file/.../<absolute path>`.
- 🔐 Bot token ранее попал в диагностический вывод; не хранить токен в журнале, перед production перевыпустить через BotFather.

## UI / watermark
- ✅ Русские подписи, `Моё видео`.
- ✅ Text watermark + logo wizard; logo sizes 10/20/30/40/50%.
- ✅ Главные кнопки `💧 Водяной знак` и `⚙️ Настройки` скрыты; настройки доступны через `📥 Скачать`.
- ✅ Channel watermark callback `cwmx:`; stale middleware больше не перезаписывает экран.
- ⚠️ В `handlers.py` есть исторические watermark участки; не делать широких rewrite.
- ✅ About/`🤖 Возможности` без сырого HTML.
- ✅ При открытии watermark flow показывается текущее значение.
- ✅ Autopost toggle использует async `aset_channel_enabled()`.

## Legacy watermark `Мой канал` — 2026-09-03
- Поиск исходников показал `Мой канал` только как пример ввода в `wm_wizard.py`; в проверенной БД значения не было.
- Добавлен `legacy_watermark_guard.py`: один раз проверяет фактический `config.DB_PATH` и удаляет только точный legacy placeholder `type=text,text=Мой канал` из `users.watermark`/`channels.watermark`.
- Marker: `settings.legacy_watermark_cleanup_v1=done`.
- Commits: `51e0650457efc08ad394a7b4e762ce88ec586f92`, `af09e27fd8f18459557dcd9b06bfb0cfed8dec6b`, `ae8c6192c8c92289e611378a3ffd1cc669fb7b50`, `8d9d4712bfcb6714cdfdfaa224bc85d78cbf4aa0`.
- CI runs `33775146383` and `33775162559` — ✅.

## Telegram command menu
- `media_hunter_bot/__init__.py` после успешного `Bot.get_me()` вызывает `delete_my_commands()`.
- Commit: `59c20fb4ae8183e210c5521c1172640d5f1300a5`.
- ⬜ Если старые команды ещё видны, проверить scoped commands/languages через BotFather/API.

## Autopost / cache
- Exact-copy: для 0/1 enabled channel второй FFmpeg не выполняется; cache key учитывает source/work/audio_only/compress, без watermark.
- Commits: `95ea3fcf8903ac29489a06816512b21b6d9e33fe`, test fix `a90d72b3bc7a3a6474fe27d45cef165d130316e3`; CI `33765082009` — ✅.
- Multi-channel: один frozen `unique_base.mp4` без watermark, затем watermark-only variants для каналов; uniqueness повторно не запускается.
- First enabled channel watermark используется и для private результата пользователя.
- `process_cache.py` содержит channel/frozen-base helpers; `optimized_processor.apply_watermark()` применяет logo size/opacity через `scale2ref` + `colorchannelmixer`.
- Code commit: `3d7df138a9603f68319fa4a68097f91ece401193`; tests: `1694e97ddd033e47c15cd85d78b2aeaf87e74753`.

## YouTube playlists
- Playlist = одна логическая задача; каждый элемент: download → unique → watermark → send/autopost → следующий.
- Continuation priority `2`; Free ordinary `1`; Premium ordinary `0`.
- Premium не прерывает уже выполняющийся FFmpeg/yt-dlp.
- Free: 20 videos/request + 3 playlist requests/month.
- Premium: 40 videos/request, без monthly playlist-request limit.
- Playlist original limit: 80 MB; обычные URL и `Моё видео` новый 80 MB лимит не получили.
- ⬜ Production smoke playlist/fairness/quota/channel limits.

## Тарифы / каналы
- Free: **1 канал**, **20 playlist videos/request**, **3 playlist requests/month**.
- Premium: **3 канала**, **40 playlist videos/request**, без monthly playlist limit.
- Оба тарифа: uniqueness, watermark, autopost.
- Playlist video original limit 80 MB.
- `db.add_channel()` проверяет premium и запрещает Free >1 / Premium >3; повторное сохранение существующего канала разрешено.
- DB commit: `0fda8a1756d32abd7733d5b571e278f65ca6048e`.
- ⬜ Production smoke channel limits.

## Важная история `handlers.py`
- ❌ Неполная массовая замена ранее вырезала функциональность.
- ✅ Рабочий вариант восстановлен из точки `6842889`.
- Restore commit: `a559a8dc79447a0e65a04009226b9d0123b5bc78`.
- Не делать широких rewrite.

## Logo upload fix — 2026-09-04
- Причина production silence: legacy wizard принимал только `LogoStates.upload + F.document`, а обычная gallery photo приходит как `Message.photo`.
- `logo_upload_fix.py` теперь регистрирует **state-wide handler `LogoStates.upload`**: photo проходит download → JPEG→PNG → validate → FSM settings → save; неподдерживаемое сообщение получает ответ вместо silent ignore.
- Bootstrap дополнительно гарантируется через package initialization, потому что production entrypoint `/opt/mediahunter/venv/bin/python /opt/mediahunter/app/main.py`/поддерживаемые bootstrap paths должны получить patch независимо от порядка импортов.
- Commit: `60eb109feeefc3e349aa9d97b1e69e8a30f2081b`.
- Registration test: `bdfd0e267a56cbb1501216dc868ad71116e48202`.
- Logo rendering regression tests добавлены; logo size/opacity теперь применяются непосредственно в optimized FFmpeg graph.
- ⬜ Production smoke: обычное фото → settings → save → проверить `data/logos` и watermark на коротком видео.

## Videos >100 MB — 2026-09-04
- Production bug: Engine сначала показывал stage `process`/«Уникализация», затем оставлял `result = source`; общий Telegram send limit 100 MB отклонял оригинал.
- Добавлен `media_hunter_bot/oversize_processor.py`: **compression-only**, без uniqueness filter; bitrate рассчитывается по duration с запасом и при необходимости уменьшается итеративно; watermark сохраняется.
- `handlers.Engine._run_job()` напрямую использует `compress_for_send()` для `>100 MB`; autopost использует уже подготовленный result и не повторяет uniqueness.
- `media_hunter_bot/__init__.py` имеет защитный routing для внешних `process_media` вызовов.
- `<=100 MB` остаются на обязательном uniqueness path.
- Commits: handlers `1527d12053d9553ec474c104ed8e4762feaaf5cd`; defensive init `ac8250ed5e69a54a86d6ea9b83d6005d6d1ab1ef`; logo `60eb109feeefc3e349aa9d97b1e69e8a30f2081b`; registration test `bdfd0e267a56cbb1501216dc868ad71116e48202`.
- Regression test: `tests/test_oversize_routing.py`.
- Early CI failures `33892994401`, `33893100311` были исправлены Path/string compatibility.
- CI `33893116282` — ✅ Compile + Regression для промежуточного исправления.
- CI run `33893496690` выявил только ошибку mock в тесте (`AsyncMock` вместо sync); исправлено commit `b22f34bf2ffbd434909ea43f2be7ecac968d69ba`.

## Final CI verification — 2026-09-04
- Для реального запуска CI создан временный draft PR #1; после проверки закрыт, не merge.
- CI run **`33895607263` (#268)** на commit `8e94da5e3a4075f2fe3125e03bd60b6f5e93b6fd` — **✅ success**.
- Job `tests` `101097388680` — Compile ✅, Regression tests ✅, весь job success.
- Это подтверждает текущий набор тестов после oversized-video test mock fix.
- Временный `CI_TRIGGER.md` после проверки удалён commit `facec9f54e46f2a206b4fcc461f397a51da60316`.
- Draft PR #1 закрыт, не merge. Тестовый branch `ci-trigger-test` остаётся только техническим артефактом и не содержит production merge.
- Workflow `.github/workflows/tests.yml` запускается на push/PR ветки `Media_hanter-v3-security`, плюс `workflow_dispatch`; compile включает `oversize_processor.py` и runtime patch modules.

## Current handoff / status
1. Branch: `Media_hanter-v3-security`.
2. **CI verification: ✅ green run `33895607263` (#268).**
3. `<=100 MB`: mandatory uniqueness preserved.
4. `>100 MB`: compression-only path to fit 100 MB send ceiling.
5. Logo upload: state-wide state handler fix; ⬜ production smoke.
6. Legacy `Мой канал`: one-shot cleanup guard; ⬜ production verification.
7. 1-channel autopost: exact-copy/no second FFmpeg; ⬜ production verification.
8. Multi-channel autopost: frozen unique base + watermark variants; ⬜ production verification.
9. Playlist: fairness/80 MB/quota logic implemented; ⬜ production smoke.
10. Free/Premium channel limits implemented; ⬜ production smoke.
11. **VPS has not been marked deployed/verified by the assistant.** Deployment must be performed and checked on the real VPS.

## VPS deployment commands
```bash
cd /opt/mediahunter/app
git fetch origin
git reset --hard origin/Media_hanter-v3-security
git log -3 --oneline
systemctl restart media-hunter.service
systemctl status media-hunter.service --no-pager -l
journalctl -u media-hunter.service --since "2 minutes ago" --no-pager | grep -E "ERROR|Error|Traceback|CRITICAL"
```

After deployment smoke-test:
- Logo: send normal gallery photo in logo flow → settings → save → verify persisted PNG → short video watermark.
- >100 MB: must not report uniqueness failure; must compress/send successfully below 100 MB.
- Verify old `Мой канал` is absent.
- Verify 1-channel autopost reuses same processed file/no second FFmpeg.
- Verify multi-channel creates `UNIQUE_BASE_CREATE` once and variants without repeated uniqueness.
- Verify playlist fairness, 80 MB guard, Free 3-request quota, Premium 40 videos, Free/Premium channel limits.

Never record bot tokens or `.env` contents here.
