# Media Hunter — журнал разработки и передачи контекста

> Единая точка правды для продолжения проекта другим ИИ.
> Рабочая ветка: `Media_hanter-v3-security`.
> Журнал хранится в GitHub и не копируется на VPS.

## Правила
1. Всегда работать в `Media_hanter-v3-security`.
2. Перед правкой читать этот журнал и проверять текущий код.
3. Не менять архитектуру без необходимости.
4. После каждой правки кода запускать CI/тесты.
5. После каждой правки дописывать сюда что изменено, почему, CI-результат и что осталось `⬜`.
6. Серверные изменения сначала `⬜`, после фактической проверки `✅`.
7. Не записывать секреты, токены, пароли или `.env`.

## Проект и production
- Python + aiogram 3.x + yt-dlp + FFmpeg + SQLite.
- Возможности: скачивание, уникализация, watermark, загрузка своего видео, автопостинг, Premium, ОПП, админка.
- VPS: `/opt/mediahunter/app`.
- Production Python: `/opt/mediahunter/venv/bin/python`.
- Media Hunter unit: `media-hunter.service`.
- Local Bot API: `127.0.0.1:8081`.
- Source/upload absolute limit: 1024 MB.
- **Бизнес-требование: все видео до 100 MB включительно должны проходить уникализацию.**
- Видео больше 100 MB не должны искусственно уникализироваться ради этого требования.

## Security / media baseline
- ✅ SSRF защита `validate_source_url`.
- ⚠️ Остаточный риск DNS rebinding/redirect-to-internal; mitigation — unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Queue/restart race через `asyncio.Lock`.
- ✅ Queue accounting и `task_done()` при restart.
- ✅ Restart завершает subprocess и чистит uploads.
- ✅ Upload проверяет очередь до скачивания.
- ✅ Payment activation атомарна; `telegram_charge_id` unique.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite fail-closed.
- ✅ User errors фильтруются через `user_errors.py`.
- ✅ `download()` использует `--write-info-json`.
- ✅ `safe_media_filename()` сохраняет исходное название.
- ✅ Text/logo watermark поддерживают настройки размера, позиции и прозрачности.
- ✅ Source/upload limit 1024 MB.

## Dependencies
- ✅ `aiogram==3.31.0`
- ✅ `aiohttp==3.14.3`
- ✅ `python-dotenv==1.1.1`
- ✅ `yt-dlp==2026.8.19`
- ✅ `curl-cffi==0.15.0`

## Серверный инцидент 2026-09-02
- ✅ `media-hunter.service` ранее терял `127.0.0.1:8081`.
- ✅ Причина: права `mediahunter` на `/var/lib/telegram-bot-api`.
- ✅ Исправлено владение каталогом и `temp` на `mediahunter:mediahunter`.
- ✅ Local Bot API стал `active/running`.
- ✅ Media Hunter вернулся в polling.
- 🔐 Bot Token был раскрыт в диагностическом выводе; перед production следует перевыпустить через BotFather. В журнал токен не писать.

## FFmpeg incident 2026-09-02
- FFmpeg 6.1.1 на VPS.
- Разные MP4 приводили к `ffmpeg failed (code=187)`.
- Подтверждённая причина старого фильтра: дробный `scale` мог давать нечётные размеры перед `libx264`, после чего кодирование падало.
- Старый фильтр был заменён безопасным even-dimension вариантом.
- Добавлен `optimized_processor.py`: лёгкий `eq`, без `unsharp`/`noise`, `-threads 2`, `-preset veryfast`, `crf 27` для обычной уникализации и `crf 30` для compression path.
- Требование `<=100 MB` не изменено: такие видео уникализируются.
- ⚠️ FFmpeg stderr стоит логировать диагностичнее, сохраняя хвост ошибки.

## UI / watermark
- ✅ Русские подписи.
- ✅ `Моё видео` — собственная загрузка.
- ✅ Text watermark wizard.
- ✅ Logo wizard.
- ✅ Logo presets 10/20/30/40/50%.
- ✅ Главные кнопки `💧 Водяной знак` и `⚙️ Настройки` скрыты; формат доступен через `📥 Скачать`.
- ✅ Channel watermark callback использует `cwmx:`.
- ✅ Исправлен middleware, который после `cwmx:*` подменял клавиатуру и возвращал пользователя назад.
- ⚠️ В проекте есть старые/новые участки watermark flow; не плодить новые дубликаты.

## Важная ошибка предыдущей попытки
- ❌ Неполная массовая замена `handlers.py` вырезала существующую функциональность и вызвала CI ошибки (`MAX_USER_QUEUE`, `metadata`, UI).
- ✅ Полный `handlers.py` восстановлен из рабочей точки `6842889`.
- Restore commit: `a559a8dc79447a0e65a04009226b9d0123b5bc78`.
- Не считать неполную замену частью production-кода.

## Autopost / двойная обработка
- Текущий `_run_job()` после private processing снова вызывает `process_media(source, ..., channel_wm)` для enabled channels.
- Это не повторная обработка уже созданного файла, потому что channel processing идёт от исходника, но для совпадающего watermark это всё равно лишний encode.
- Требуется рефакторинг: при совпадающем эффективном watermark переиспользовать private output; для разных watermark отдельный output допустим; одинаковые channel profiles должны использовать один результат.
- ⬜ Добавить regression test на количество `process_media` вызовов.

## Local Bot API upload/logo bug — 2026-09-02
- Production log показал, что `Моё видео` падает **до FFmpeg**.
- Ошибка: HTTP 404 на URL вида `/file/botTOKEN//var/lib/telegram-bot-api/...`.
- Local Bot API возвращает абсолютный filesystem path, но aiogram session была создана через `TelegramAPIServer.from_base(LOCAL_BOT_API)` без `is_local=True`.
- Поэтому `bot.download_file()` ошибочно пытался скачать локальный путь через HTTP.
- Та же цепочка используется при загрузке logo, поэтому logo upload имел тот же корень.
- ✅ В `media_hunter_bot/__init__.py` добавлен bootstrap fix: `TelegramAPIServer.from_base()` получает `is_local=True` по умолчанию.
- Fix выполняется до создания `AiohttpSession` в `handlers.py`.
- Commit: `046fbb3efc38873deb07df28ca07249b96a66ac3`.
- ⬜ Production smoke test `Моё видео`.
- ⬜ Production smoke test PNG logo.
- ⬜ Production smoke test video + logo.

## Tests / CI
- `.github/workflows/tests.yml`: install dependencies → compile → `unittest discover`.
- Run `33648480341` — ✅ success.
- Run `33651556824` — ✅ success.
- Run `33653931005` — ✅ success.
- Run `33655342998` на `046fbb3e...` — ✅ success.
- Run `33655394965` на `bc8f2e37...` — проверяет Local Bot API regression; результат на момент записи ещё не подтверждён.

## Последние commits
- `704be780aed7d80eb1cd58b05fb715375086bfcf` — Document FFmpeg optimization and UI fixes.
- `046fbb3efc38873deb07df28ca07249b96a66ac3` — Fix Local Bot API file downloads.
- `bc8f2e374227f78bffdc41f98744b28d7889a2eb` — Add Local Bot API regression test.

## Handoff
1. ⬜ Дождаться green CI для `bc8f2e37...`.
2. ⬜ Deploy branch head to VPS и restart `media-hunter.service`.
3. ⬜ Проверить `Моё видео`.
4. ⬜ Проверить PNG logo и video+logo.
5. ⬜ Проверить enabled autopost.
6. ⬜ Исправить/rework duplicate processing и добавить regression test.
7. ⬜ Улучшить stderr logging FFmpeg.
8. 🔐 Перевыпустить Bot Token через BotFather из-за раскрытия в логах.
