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
- Первоначально было отмечено, что `apply_watermark()` для logo использовал direct overlay и не проходил старый `wm_wizard` render pipeline.
- ✅ В текущей версии это исправлено: размер/opacity logo учитываются непосредственно в FFmpeg filter graph.

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
- Actual code commit: `3d7df138a9603f68319fa4a68097f91ece401193`.
- Actual test commit: `1694e97ddd033e47c15cd85d78b2aeaf87e74753`.
- ⬜ CI для `1694e97...` ранее не был подтверждён через commit-scoped endpoint; перед production ориентируемся на текущий green workflow после последующих commits.

## YouTube playlists — 2026-09-03
- Плейлист — одна логическая задача; следующий элемент ставится только после завершения предыдущего.
- Каждый элемент: скачать → уникализировать → watermark → отправить/autopost → следующий элемент.
- Continuation priority = `2`; обычный Free = `1`; обычный Premium = `0`.
- Premium не прерывает уже выполняющийся FFmpeg/yt-dlp, но после освобождения worker идёт раньше Free и playlist continuation.
- Free: максимум 20 видео/request и 3 playlist requests в календарный месяц.
- Premium: максимум 40 видео/request, без monthly playlist-request limit.
- Playlist video source limit: 80 MB; при известном размере >80 MB загрузка не начинается; неизвестный размер проверяется после загрузки до FFmpeg.
- Обычные URL и `Моё видео` не получили новый 80 MB лимит.
- Continuation state в памяти; restart/cancel останавливает продолжение.
- ⬜ Production smoke: playlist 5–20 видео, fair interleaving, >80 MB guard, free monthly quota.

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
- Latest confirmed full green before explicit photo-handler rework: run `33781401170` на `a0f09948...` — ✅ compile + regression tests.
- CI workflow now also compiles `optimized_processor.py`, `process_cache.py`, `logo_upload_fix.py` and `legacy_watermark_guard.py`; this closes a previous CI coverage gap.

## Logo upload fix — 2026-09-03
### Причина
- Пользователь обнаружил, что при загрузке логотипа бот вообще ничего не отвечал и логотип не сохранялся.
- В `wm_wizard.py` исходный wizard имел обработчик только `LogoStates.upload, F.document`.
- Обычная фотография из галереи Telegram приходит как `Message.photo`, поэтому такой аплоад не попадал ни в один handler и выглядел как «тихое игнорирование» без ошибки.

### Первое исправление
- Добавлен `media_hunter_bot/logo_upload_fix.py` с обработкой `Message.photo` и конвертацией JPEG → PNG через FFmpeg.
- `main.py` регистрирует patch через `_logo_upload_fix.patch_router(_handlers.router)`.
- Исправлена асинхронная ошибка с `Path.mkdir()` через `asyncio.to_thread()`.
- Regression test использует `TemporaryDirectory()` и проверяет фактический PNG, переход FSM в `LogoStates.settings` и ответ пользователю.
- CI run `33780698086` на `8ccd1a08...` — ✅ success; Compile ✅, Regression tests ✅.

### Повторная диагностика после production smoke
- После деплоя предыдущей версии пользователь снова получил полное молчание при отправке обычного фото.
- `logo_upload_fix.py` получил явный router handler `LogoStates.upload + F.photo`.
- Production smoke всё ещё показал `Update ... is not handled`, поэтому одной регистрации через root `main.py` оказалось недостаточно.
- Причина усиления bootstrap: если service запускает `handlers.py` напрямую, root `main.py` patch не выполняется. Поэтому теперь `media_hunter_bot/__init__.py` оборачивает `register_wm_wizard()` и гарантирует регистрацию photo handler в любом поддержанном bootstrap пути.
- Новый commit: `146dc7ed2508d907b81d04100e605e432fb954c7`.

### Logo watermark rendering
- Выявлен отдельный production-риск: `process_cache.py` вызывает `optimized_processor.apply_watermark()` напрямую, поэтому старый `_install_logo_processing_wrapper()` из `wm_wizard.py` не гарантировал применение `logo_size`/`logo_opacity` в cached multi-channel path.
- `optimized_processor.py` теперь применяет `logo_size` и `logo_opacity` непосредственно в FFmpeg filter graph через `scale2ref` + `colorchannelmixer`, сохраняя frozen unique base без повторной уникализации.
- Commit: `4c51f6074dabe2f381698ffe419a9f00ba805b48`.
- Добавлен regression test `tests/test_optimized_logo.py`.
- Добавлен regression test `tests/test_logo_router_registration.py`.
- ⬜ Production smoke logo: обычное фото → экран настроек → сохранить → короткое видео → проверить размер/opacity/позицию.

### CI coverage
- `.github/workflows/tests.yml` расширен: compile теперь включает все runtime patch-модули, а не только основные файлы.
- Commit: `3fb66ea96979ad275aa8e7b84437d7a48c5eab1a`.
- ⬜ Новый CI для текущей головы после всех этих изменений.

## Bugfix audit — 2026-09-04
### Logo upload
- Production smoke повторно подтвердил проблему: после входа в `LogoStates.upload` обычные photo updates приходили как `Update ... is not handled`.
- Аудит ветки подтвердил, что legacy `wm_wizard.py` действительно регистрирует только `LogoStates.upload + F.document`; photo path был вынесен в `logo_upload_fix.py`.
- Предыдущая архитектура была хрупкой: photo handler подключался отдельным bootstrap patch, а ошибка импорта/регистрации в `media_hunter_bot/__init__.py` проглатывалась через `except Exception: pass`. Поэтому отсутствие handler могло выглядеть как полностью «тихая» проблема.
- Новый fix: `logo_upload_fix.py` регистрирует обработчик на **весь `LogoStates.upload` state**, а не только через `F.photo`. Если в состоянии пришло фото — оно проходит полный download → FFmpeg JPEG→PNG → validate → FSM settings → сохранение. Для неподдерживаемого сообщения бот теперь отвечает пользователю вместо молчания.
- Добавлена проверка фактической регистрации state-handler.
- ⬜ Production smoke: обычное фото из галереи → экран настроек → сохранить → проверить файл в `data/logos`.

### Videos >100 MB
- Production smoke подтвердил отдельную логическую ошибку: `handlers.Engine._run_job()` сначала продвигал progress на stage `process` («Уникализация»), а затем для `size > MAX_UNIQUE_SIZE_MB` выбирал `result = source`. После этого общий `send_limit = MAX_SEND_MB = 100 MB` всё равно отклонял исходный файл сообщением `Результат превышает лимит отправки 100 МБ`.
- То есть ветка «не уникализировать >100 MB» формально существовала, но была несовместима с обязательным Telegram send limit 100 MB: оригинал нельзя было отправить.
- Новый fix вводит `media_hunter_bot/oversize_processor.py`: для видео >100 MB используется **compression-only** pipeline. Уникальный фильтр не применяется. Битрейт рассчитывается от длительности с запасом, а при необходимости снижается итеративно; watermark сохраняется.
- В `handlers.py` теперь **непосредственно** вызывается `compress_for_send()` для ветки `>100 MB`; autopost этой же категории повторно не запускает uniqueness и использует уже подготовленный результат.
- `media_hunter_bot/__init__.py` также содержит защитный routing entrypoint для вызовов `process_media` вне `Engine`, но production Engine теперь исправлен в основном месте принятия решения.
- Видео <=100 MB остаются на прежнем обязательном uniqueness path без ослабления требования.
- Добавлен regression test `tests/test_oversize_routing.py`.
- CI compile coverage расширена на `oversize_processor.py`.
- CI run `33892994401` (`2d552044...`) — ❌ из-за несовместимости нового routing с legacy tests, где `source` передавался строкой.
- CI run `33893100311` (`3c575bdd...`) — ❌ та же причина в `__init__.py`: `_processor` был удалён после bootstrap, но runtime wrapper обращался к нему.
- Исправление: routing использует `pathlib.Path(source)` до проверки существования; legacy string-call tests снова поддерживаются.
- CI run `33893116282` (`036bcf3...`) — ✅ Compile + Regression tests.
- Финальная правка `handlers.py` commit: `1527d12053d9553ec474c104ed8e4762feaaf5cd`.
- Финальная правка `__init__.py` commit: `ac8250ed5e69a54a86d6ea9b83d6005d6d1ab1ef`.
- Финальная logo fix commit: `60eb109feeefc3e349aa9d97b1e69e8a30f2081b`; registration test `bdfd0e267a56cbb1501216dc868ad71116e48202`.
- ⬜ CI после финальной правки `handlers.py`/`__init__.py`.
- ⬜ VPS deployment and production smoke for both fixes.

## Handoff / текущий статус
1. Branch: `Media_hanter-v3-security`.
2. Latest code commits before this journal update: `1527d12053d9553ec474c104ed8e4762feaaf5cd` (`handlers.py`) and `ac8250ed5e69a54a86d6ea9b83d6005d6d1ab1ef` (`__init__.py`), with journal update after them.
3. Logo upload now has a state-wide handler rather than relying on `F.photo` alone.
4. Videos >100 MB now bypass uniqueness and use compression-only processing to fit the send ceiling.
5. Videos <=100 MB remain mandatory uniqueness processed.
6. CI `33893116282` for the pre-final code is green; final handler commit still needs CI confirmation.
7. ⬜ After final CI: update VPS, restart `media-hunter.service`, verify status.
8. ⬜ Smoke logo: normal gallery photo → settings → save → verify persisted logo.
9. ⬜ Smoke >100 MB video: must not report uniqueness failure; must compress/send successfully within the configured absolute source limit.
10. ⬜ Verify old `Мой канал` watermark is not applied.
11. ⬜ Verify 1-channel autopost uses exact same processed file / no second FFmpeg.
12. ⬜ Multi-channel: verify `UNIQUE_BASE_CREATE` once and channel variants without repeated uniqueness.
13. ⬜ Playlist smoke: 5–20 videos, fair interleaving, 80 MB guard, Free quota, Premium 40.
14. ⬜ Premium/free channel-limit smoke.
15. Never record bot tokens or `.env` contents in this journal.
