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
- ✅ Добавлен `media_hunter_bot/process_cache.py`: кэш результата ограничен комбинацией source/work/watermark/audio_only/compress, поэтому повторно используется только результат внутри того же job и только при полностью совпадающем профиле.
- ✅ `media_hunter_bot/__init__.py` оборачивает оптимизированный `process_media` через этот cache до импорта `handlers.py`.
- ✅ Разные watermark и разные режимы compression получают независимые FFmpeg outputs.
- ⬜ Production проверить, что private + channel с одинаковым watermark дают один FFmpeg run.

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

## Регрессия process_media wrapper — 2026-09-02
- Первый production smoke test после deploy показал `TypeError: <lambda>() takes 3 positional arguments but 6 were given` в `wm_wizard.py:148`.
- Причина: bootstrap cache wrapper в `__init__.py` объявлял `audio_only`, `compress`, `register` только keyword-only, а watermark wrapper вызывает `process_media` позиционно шестью аргументами.
- Логотип при этом уже загружался успешно; падение происходило на этапе запуска обработки.
- ✅ Заменён lambda на `_cached_process_entry(...)`, принимающий legacy positional вызов и передающий параметры в cache именованно.
- Commit: `eac7b433970f4136ecbd53b5edf591b1b9dfb989`.
- Commit test: `c190963d167c633acd9c11956664ae1a7898bf9d`.
- CI на эти изменения ранее был зелёным.

## Новый production bug: удалённые runtime globals — 2026-09-02
- После deploy branch head `ef86b3d8f85751d8af5c8b6b5165adbae8235daf` production повторно упал при запуске обработки.
- Первый traceback: `TypeError: <lambda>() takes 3 positional arguments but 6 were given` был уже исправлен в коде, после restart он сменился на:
  `NameError: name '_cached_process_media' is not defined. Did you mean: '_cached_process_entry'?`
- Точная причина: `_cached_process_entry()` разрешает `_cached_process_media` и `_optimized_process_media` во время реального вызова, но внизу `__init__.py` обе переменные были удалены через `del`. Это было не покрыто предыдущим regression test, потому что тест проверял только сигнатуру.
- ❌ Это production-only ошибка bootstrap-кода, не FFmpeg и не проблема уникализации.
- ✅ Убрано удаление `_cached_process_media` и `_optimized_process_media`; добавлен regression test, который реально вызывает `_cached_process_entry` шестью позиционными аргументами с подменёнными зависимостями и ловит NameError-класс регрессии.
- Fix commit: `d82cb3c4c2d45f396831ccb9cd2ba16cb06174c9`.
- Test commit: `7d76f3cb03917e0a14d8704189151f2ca267c1ae`.
- ⬜ CI после этих commits.
- ⬜ Production smoke test `Моё видео`.
- ⬜ Production smoke test YouTube.
- ⬜ Production smoke test video+logo.
- ⬜ Production проверить autopost и отсутствие второго encode при совпадающем профиле.

## Tests / CI
- `.github/workflows/tests.yml`: install dependencies → compile → `unittest discover`.
- Run `33648480341` — ✅ success.
- Run `33651556824` — ✅ success.
- Run `33653931005` — ✅ success.
- Run `33655342998` на `046fbb3e...` — ✅ success.
- Run `33655394965` на `bc8f2e37...` — Local Bot API regression.
- Run `33655799262` на `1fab8a9a...` — ✅ success.
- ⬜ CI для commits `d82cb3c4...`, `7d76f3cb...`.

## Последние commits
- `7d76f3cb03917e0a14d8704189151f2ca267c1ae` — Test process wrapper runtime dependencies.
- `d82cb3c4c2d45f396831ccb9cd2ba16cb06174c9` — Fix process wrapper runtime globals.
- `c190963d167c633acd9c11956664ae1a7898bf9d` — Add regression test for process wrapper arguments.
- `eac7b433970f4136ecbd53b5edf591b1b9dfb989` — Fix process_media wrapper positional arguments.
- `a26db9ec361e2fa9bd58be3ccd069e9894fd7838` — Avoid duplicate media processing for identical watermark profiles.
- `2c8dd1ca4a20ead1f32a826fe0e50edc1b4f69c5` — Reuse identical processing results during autopost.
- `dacd9e387a65377e1e8bf2933155d4f2613fb8ab` — Test reuse of identical processing results.
- `046fbb3efc38873deb07df28ca07249b96a66ac3` — Fix Local Bot API file downloads.

## Handoff
1. ⬜ CI для текущего head (`7d76f3cb...`).
2. ⬜ Deploy branch head to VPS и restart `media-hunter.service`.
3. ⬜ Проверить `Моё видео`.
4. ⬜ Проверить YouTube.
5. ⬜ Проверить PNG logo и video+logo.
6. ⬜ Проверить enabled autopost.
7. ⬜ Проверить, что одинаковый watermark не запускает второй FFmpeg.
8. ⬜ Улучшить stderr logging FFmpeg.
9. 🔐 Перевыпустить Bot Token через BotFather из-за раскрытия в логах.
