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

## Production
- Python + aiogram 3.x + yt-dlp + FFmpeg + SQLite.
- VPS: `/opt/mediahunter/app`.
- Production Python: `/opt/mediahunter/venv/bin/python`.
- Service: `media-hunter.service`.
- Local Bot API: `127.0.0.1:8081`.
- DB path по умолчанию: `data/media_hunter.sqlite3`; фактический путь определяется `MEDIA_HUNTER_HOME`.
- Source/upload absolute limit: 1024 MB.
- **Все видео <=100 MB обязательно уникализируются.**
- Видео >100 MB не уникализируются искусственно ради этого требования.

## Безопасность / базовая логика
- ✅ SSRF защита `validate_source_url`; остаточный риск DNS rebinding/redirect-to-internal mitigated unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Queue/restart race через `asyncio.Lock`, корректный queue accounting и `task_done()`.
- ✅ Restart/shutdown завершают subprocess и чистят временные файлы.
- ✅ Upload проверяет очередь до скачивания Telegram-файла.
- ✅ Payment activation атомарна; `telegram_charge_id` unique.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite fail-closed.
- ✅ User-facing ошибки проходят через `user_errors.py`.
- ✅ `download()` использует `--write-info-json`.
- ✅ `safe_media_filename()` сохраняет исходное название.

## FFmpeg / уникализация
- VPS использует FFmpeg 6.1.1.
- Старый fractional `scale` иногда давал нечётные размеры и `ffmpeg failed (code=187)` / `width not divisible by 2`.
- ✅ Безопасный even-dimension filter: `trunc(iw*0.998/2)*2` и `trunc(ih*0.998/2)*2`.
- ✅ `optimized_processor.py`: лёгкий `eq`, без `unsharp`/`noise`, `-threads 2`, preset `superfast`, CRF 27 для обычной уникализации и CRF 30 для compression path.
- Требование уникализации <=100 MB не ослаблено.
- ✅ `process_media()` defensively создаёт `work_dir` перед FFmpeg после production ошибки `Error writing trailer: No such file or directory`.

## Local Bot API / logo
- ✅ `TelegramAPIServer.from_base()` patched in `media_hunter_bot/__init__.py` to default `is_local=True`.
- Причина: Local Bot API возвращает абсолютный filesystem path; без `is_local=True` aiogram пытался запрашивать `/file/bot.../<absolute path>` через HTTP.
- Logo upload использует исправленную цепочку.
- 🔐 Bot Token ранее попал в диагностический вывод. Не записывать его в журнал; перед production требуется перевыпуск через BotFather.

## UI / watermark
- ✅ Русские подписи.
- ✅ `Моё видео`.
- ✅ Text watermark wizard и logo wizard, размеры logo 10/20/30/40/50%.
- ✅ Главные кнопки `💧 Водяной знак` и `⚙️ Настройки` скрыты; формат доступен через `📥 Скачать`.
- ✅ Channel watermark callback использует `cwmx:`.
- ✅ Убран middleware, который после `cwmx:*` перезаписывал экран.
- ⚠️ В `handlers.py` существуют старые/новые участки watermark flow; не плодить дубликаты и не делать широких rewrite.
- ✅ `🤖 Возможности`/about использует простые русские формулировки и иконки; сырой HTML `<b>` не должен показываться пользователю.
- ✅ При открытии text/logo watermark пользователь видит уже настроенное значение и может его изменить или удалить.
- ✅ Autopost toggle использует async DB API `aset_channel_enabled()`.

## Legacy watermark template — 2026-09-03
### Диагностика
- Пользователь сообщил, что бот автоматически добавляет старый watermark `Мой канал`, оставшийся от прежней кнопки watermark в главном меню.
- Поиск `/opt/mediahunter/app` нашёл `Мой канал` только в `wm_wizard.py` как текст примера ввода: `Например: <code>Мой канал</code>`.
- Проверка таблицы `settings` не обнаружила этот текст.
- Поиск по всем таблицам БД `data/media_hunter.sqlite3` также не обнаружил `Мой канал`.
- Важно: `config.DB_PATH` учитывает `MEDIA_HUNTER_HOME`, поэтому ручная проверка относительного `data/...` может отличаться от production DB, если переменная окружения задана.

### Исправление
- Добавлен `media_hunter_bot/legacy_watermark_guard.py`.
- При старте бот один раз проверяет **фактический `config.DB_PATH`** и удаляет из `users.watermark`/`channels.watermark` только точный legacy placeholder `type=text, text=Мой канал`.
- Устанавливается marker `settings.legacy_watermark_cleanup_v1=done`, поэтому пользователь может в будущем сознательно настроить текст `Мой канал`, и он больше не будет удаляться на каждом рестарте.
- Cleanup ничего не меняет, если placeholder отсутствует.
- В `main.py` migration вызывается перед `asyncio.run(main())`.
- Добавлены regression tests для one-shot cleanup и сохранения нового пользовательского значения.
- Commits:
  - `51e0650457efc08ad394a7b4e762ce88ec586f92` — guard module.
  - `af09e27fd8f18459557dcd9b06bfb0cfed8dec6b` — tests.
  - `ae8c6192c8c92289e611378a3ffd1cc669fb7b50` — initial main integration.
  - `8d9d4712bfcb6714cdfdfaa224bc85d78cbf4aa0` — simplified main integration.
- CI run `33775146383` for `ae8c6192...` — ✅ success.
- CI run `33775162559` for `8d9d4712...` — compile and regression tests completed successfully.

## Telegram command menu
- `media_hunter_bot/__init__.py` после успешного `Bot.get_me()` вызывает `delete_my_commands()` для очистки старого default command menu.
- Commit: `59c20fb4ae8183e210c5521c1172640d5f1300a5`.
- ⬜ Если старые команды Telegram всё ещё видны, проверить scoped commands/languages через BotFather/API.

## Autopost: exact-copy режим
- Первоначальная проблема: `_run_job()` мог повторно вызвать `process_media()` для каждого enabled channel, что давало второй FFmpeg encode.
- Cache key был изменён на `source + work + audio_only + compress`, без watermark, чтобы при 0/1 enabled channel канал получал тот же готовый результат.
- Exact-copy code commit: `95ea3fcf8903ac29489a06816512b21b6d9e33fe`.
- Test fix commit: `a90d72b3bc7a3a6474fe27d45cef165d130316e3`.
- Подтверждённый CI для test fix: run `33765082009` — ✅ green.

## Autopost: frozen unique base + channel variants — 2026-09-03
### Новая схема
- **0/1 enabled autopost channel:** exact-copy, один готовый результат используется повторно.
- **2–3 enabled autopost channels:** сначала один раз создаётся `unique_base.mp4` без watermark; затем из этой базы делаются watermark-only variants.
- Пользовательский результат и channel variants не запускают uniqueness повторно.
- `unique_base.mp4` живёт в текущем `work` каталоге до cleanup job.
- Варианты называются `watermark_<profile>.mp4`.

### Код
- `media_hunter_bot/optimized_processor.py`: общий FFmpeg runner + `apply_watermark()` без uniqueness filter.
- `media_hunter_bot/process_cache.py`: frozen base для нескольких каналов.
- `tests/test_process_cache.py`: проверки exact-copy, frozen base, empty watermark и compression cache.
- Commits:
  - `6004e6e3f62754ab2f3098128941934e1d5b0e11`
  - `64e220e667f5d83202cbe5081c39f74ccfb0c6bb`
  - `aa248aa50e0ee61d69c129ded0a8cc08d658c9f7`
  - `e8007d3ad84c7a76f748bd4290704c782b4c0e6d` — documentation/frozen-base handoff.
- ⬜ Важное замечание: текущий `apply_watermark()` для logo использует direct overlay и не проходит старый `wm_wizard` render pipeline; перед production нужно отдельно проверить размер/opacity logo для multi-channel режима.

## Autopost: first-channel watermark for user result — 2026-09-03
### Новое правило
- Если есть хотя бы один enabled autopost channel, видео, отправляемое пользователю, должно использовать watermark **первого enabled канала**.
- При одном канале это гарантирует: один обработанный файл → пользователю → exact-copy в канал. Старый пользовательский/legacy watermark больше не должен подменять канал.
- При нескольких каналах уникализация по-прежнему выполняется один раз в `unique_base.mp4`; пользователю создаётся variant первого канала, а каждому следующему каналу — его собственный variant из той же frozen base.
- Если у первого канала watermark не настроен, пользовательский результат также остаётся без watermark. Второй/третий канал при наличии собственного watermark получает свой вариант.

### Реализация
- `media_hunter_bot/process_cache.py` добавлены `_channel_rows()`, `_first_channel_watermark()`, `_channel_watermarks()` и `_use_first_channel_watermark()`.
- User/private watermark считается отдельным профилем только если он не совпадает ни с одним enabled channel profile; в этом случае для private результата берётся watermark первого канала.
- Для 1-channel режима cache сохраняет exact-copy: второй вызов возвращает тот же файл без второго FFmpeg.
- Для multi-channel режима frozen unique base сохраняется, а watermark variants создаются из неё; uniqueness повторно не запускается.
- Добавлены regression tests на реальный first-channel watermark и на multi-channel private result.
- Code commit: `e1d50d50ce3d19bf5643df502053590564fd5185`.
- Test commit: `733759976b88a34526acdaf4a21791f5a9965128`.
- ⬜ Production: обновить VPS, отправить видео с настроенным watermark первого канала и проверить, что в боте и канале виден один и тот же watermark; проверить отсутствие `Мой канал`.

## YouTube playlists — 2026-09-03
- Плейлист — одна логическая задача; следующий элемент ставится только после завершения предыдущего.
- Каждый элемент: скачать → уникализировать → watermark → отправить/autopost → следующий элемент.
- Continuation priority = `2`; обычный Free = `1`; обычный Premium = `0`.
- Premium не прерывает уже выполняющийся FFmpeg/yt-dlp, но после освобождения worker идёт раньше Free и playlist continuation.
- Free: максимум 20 видео/request и 3 playlist requests в календарный месяц.
- Premium: максимум 40 видео/request, без месячного лимита playlist requests.
- Playlist video source limit: 80 MB; при известном размере >80 MB загрузка не начинается; неизвестный размер проверяется после загрузки до FFmpeg.
- Обычные URL и `Моё видео` не получили новый 80 MB лимит.
- Continuation state в памяти; restart/cancel останавливает продолжение.
- ⬜ Production smoke: playlist 5–20 видео, Premium 40, fair interleaving, >80 MB guard, free monthly quota.

## Тарифы / каналы
- Free: **1 канал**, **20 playlist-видео/request**, **3 playlist requests/month**.
- Premium: **3 канала**, **40 playlist-видео/request**, без monthly playlist limit.
- Оба тарифа: uniqueness, watermark, autopost.
- Playlist video original limit: 80 MB.
- `db.add_channel()` проверяет premium напрямую в users table и запрещает Free >1 / Premium >3; повторное сохранение существующего канала разрешено.
- DB commit: `0fda8a1756d32abd7733d5b571e278f65ca6048e`.
- ⬜ Production проверить Free second channel reject и Premium third/fourth channel behavior.

## Важная история с handlers.py
- ❌ Неполная массовая замена `handlers.py` ранее вырезала функциональность и вызвала CI ошибки.
- ✅ Рабочий `handlers.py` восстановлен из точки `6842889`.
- Restore commit: `a559a8dc79447a0e65a04009226b9d0123b5bc78`.
- Не делать широких rewrite `handlers.py` без необходимости.

## Tests / CI
- `.github/workflows/tests.yml`: install dependencies → compile → `python -m unittest discover -s tests -v`.
- Последний подтверждённый green до exact-copy: run `33762724035` для `ae7e28244450f71793f0dc9b2158de33face08af`.
- Run `33764835219` на `8bd812c6ccb2559966b0481627a2d24ff2ff596d` — ❌ regression из-за старого ожидания разных outputs для разных watermark; compile и остальные тесты прошли.
- Run `33765082009` на `a90d72b3bc7a3a6474fe27d45cef165d130316e3` — ✅ green.
- Latest legacy-cleanup runs: `33775146383` — ✅; `33775162559` — compile и regression tests завершены успешно.
- ⬜ Новый CI для first-channel watermark: должен подтвердить `e1d50d50...` + `73375997...`.

## Handoff / текущий статус
1. Branch: `Media_hanter-v3-security`.
2. Latest code includes first-channel watermark exact-copy logic: `e1d50d50ce3d19bf5643df502053590564fd5185` + tests `733759976b88a34526acdaf4a21791f5a9965128`.
3. Production deploy is ⬜ until VPS is updated and smoke-tested.
4. After deploy, restart `media-hunter.service`.
5. First smoke: send a <=100 MB video with one enabled channel whose watermark is configured; verify bot result and channel copy show the same watermark.
6. Second smoke: verify an old `Мой канал` watermark is not applied.
7. Third smoke: verify 1-channel autopost uses exact same processed file / no second FFmpeg.
8. Multi-channel smoke: verify `UNIQUE_BASE_CREATE` once and channel variants without repeated uniqueness.
9. Playlist smoke remains ⬜.
10. Never record bot tokens or `.env` contents in this journal.
