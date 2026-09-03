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

## Telegram mobile command menu — 2026-09-02
- Пользователь обнаружил отдельное меню Telegram в строке ввода рядом со скрепкой, где оставались старые команды предыдущей версии: `Плюсы Hunter метода`, `Автопостинг`, `Купить премиум`.
- Это не inline-клавиатура `menu()` бота, а список команд Telegram Bot API.
- ✅ В `media_hunter_bot/__init__.py` добавлена очистка default command scope через `bot.delete_my_commands()` после успешного `get_me()` и до polling.
- Очистка выполняется автоматически при каждом старте, поэтому старые команды не должны возвращаться после перезапуска.
- Изменение не затрагивает inline-кнопки, уникализацию, watermark, загрузку видео или автопостинг.
- Commit: `59c20fb4ae8183e210c5521c1172640d5f1300a5`.
- ⬜ После deploy проверить мобильное меню Telegram; если старые пункты останутся, проверить наличие отдельно заданных command scopes/languages в BotFather/API.

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
  `NameError: name '_cached_process_media' is not defined. Did you mean '_cached_process_entry'?`
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

## YouTube playlists — 2026-09-03
- В исходной реализации playlist URL сначала разворачивался в список ссылок через `playlist_items()`, затем все элементы пытались сразу положить в общую очередь. Из-за `MAX_USER_QUEUE=10` плейлист фактически упирался в лимит пользователя и мог быть отклонён целиком.
- ❌ Не нужно просто снимать `MAX_USER_QUEUE` и складывать 20–50 отдельных задач: при `MAX_CONCURRENT=1` это могло надолго занять единственный worker и заморозить обычные задачи.
- ✅ Добавлен `media_hunter_bot/playlist_support.py`, подключаемый после импорта `handlers.py` из root `main.py`, без массовой переделки `handlers.py`.
- ✅ Плейлист теперь считается **одной логической задачей пользователя** и не расходует лимит `MAX_USER_QUEUE` на каждый элемент. Продолжение добавляется в очередь только после завершения предыдущего видео.
- ✅ После каждого элемента полностью выполняется обычный `_run_job()`: скачивание → уникализация → watermark → все enabled autopost-каналы → отправка. Только после завершения этого видео ставится следующий элемент плейлиста. Поэтому 40 видео с тремя разными channel watermark не держат все версии одновременно и дают общей очереди шанс работать между элементами.
- ✅ Playlist continuation получает низший приоритет `2`, поэтому обычные бесплатные/премиум задачи могут проходить между видео плейлиста. Это снижает риск блокировки общей очереди при `MAX_CONCURRENT=1`.
- ✅ Обычная Premium-задача имеет приоритет `0`, Free — `1`. Premium **не прерывает уже выполняющийся FFmpeg/yt-dlp job**, но после освобождения worker обычная Premium-задача выбирается раньше обычной Free-задачи и playlist continuation.
- ✅ Бесплатный тариф: максимум **20 первых видео за один плейлист** и максимум **3 playlist-запроса в календарный месяц**. Лимит хранится в SQLite (`playlist_usage`), поэтому restart не сбрасывает месячный счётчик.
- ✅ Premium: максимум **40 первых видео за один плейлист**, **без месячного лимита** на количество playlist-запросов.
- ✅ Перед постановкой playlist-запроса бот получает общее количество элементов через `playlist_count`, а пользователю отправляется сообщение с фактическим количеством и применённым лимитом.
- ✅ Для playlist-видео введён отдельный исходный лимит **80 MB**. Если yt-dlp заранее сообщает известный `filesize/filesize_approx` выше 80 MB, загрузка такого видео не начинается. Если размер заранее неизвестен, после загрузки размер проверяется и файл не передаётся в обычную обработку/FFmpeg.
- ⚠️ Для HLS/DASH и других форматов yt-dlp может не знать точный размер до загрузки; поэтому пост-проверка после скачивания остаётся обязательной.
- ✅ Обычные одиночные URL и `Моё видео` не получили новый 80 MB playlist-лимит.
- Commits: `43e29244...`, `4e45567f...`, `2a61db18...`, `01846cdf...`, `2863e662...`.
- CI workflow `33743644530` на commit `f8a15408...` — ✅ success (compile + regression tests).
- ⬜ Production smoke test: playlist 5–20 видео.
- ⬜ Production проверить Premium playlist 40 видео.
- ⬜ Production проверить, что обычная задача пользователя/другого пользователя проходит между playlist-видео.
- ⬜ Production проверить отказ/пропуск playlist-видео >80 MB без FFmpeg.
- ⬜ Production проверить месячный лимит 3 playlist-запроса free-пользователя.

## Тарифы / каналы — 2026-09-03
- Зафиксирована окончательная продуктовая матрица:
  - 🆓 Free: **1 канал**, **20 видео из плейлиста за запрос**, **3 playlist-запроса в календарный месяц**.
  - ⭐ Premium: **3 канала**, **40 видео из плейлиста за запрос**, **без месячного лимита плейлистов**.
  - Оба тарифа: уникализация, watermark и автопостинг.
  - Для playlist-видео обоих тарифов действует исходный лимит 80 MB на видео.
- ✅ `media_hunter_bot/db.py` теперь реально ограничивает добавление каналов: Free — 1, Premium — 3. Повторное сохранение уже подключённого канала не блокируется лимитом.
- ✅ `MAX_PLAYLIST_ITEMS` по умолчанию снижен с 50 до 40; Premium policy дополнительно ограничена `PREMIUM_PLAYLIST_MAX_VIDEOS=40`, Free — `FREE_PLAYLIST_MAX_VIDEOS=20`.
- ⬜ CI после изменений тарифной матрицы.
- ⬜ Production проверить Free: второй канал отклоняется.
- ⬜ Production проверить Premium: третий канал добавляется, четвёртый отклоняется.

## Что я умею — 2026-09-03
- Пользователь предложил добавить в конец главного меню кнопку `ℹ️ Что я умею`, чтобы новый пользователь сразу видел возможности бота и различия Free/Premium.
- ✅ Добавлен отдельный `media_hunter_bot/about.py` с единым информационным экраном.
- ✅ Кнопка добавляется последней строкой главного меню и открывает экран с описанием скачивания, плейлистов, уникализации, text/logo watermark, своего видео, автопостинга, форматов, Free-лимитов и Premium.
- ✅ Экран теперь отражает финальную матрицу: Free 1 канал / 20 видео / 3 playlist-запроса в месяц; Premium 3 канала / 40 видео / без месячного лимита; обработка плейлиста по одному видео; уникализация, watermark и автопостинг для обоих тарифов.
- Commits: `b1efa423...`, `2e1295a4...`, `99bfdce8...`, `32dd48ce...`, `0ce1f520...`.
- ⬜ CI для текущего head.
- ⬜ Production проверить отображение кнопки и возврат назад.

## Tests / CI
- `.github/workflows/tests.yml`: install dependencies → compile → `unittest discover`.
- Run `33743644530` на `f8a15408...` — ✅ success.
- Run `33744043051` на промежуточном commit `32dd48ce...` — ❌ regression tests failed; compile step passed.
- ⬜ CI для текущего head после финальной тарифной матрицы.

## Последние commits
- `4720d54d132aa43f58f424c2012c60c3d855623b` — Test final Free and Premium capabilities.
- `0ce1f5205e00b06da99079c4fb7cefb989a3e334` — Document final Free and Premium capabilities.
- `88148677f9b95235e3d1e298061d2d42a05b8162` — Restore DB API and enforce Free 1 Premium 3 channels.
- `b6972f4813664453ccde9727d78b566bda27e765` — Apply fair playlist processing and Premium 40-video policy.
- `86d9bb44ad3a141f0f157515a0392c739e3d938a` — Set final subscription and playlist limits.
- `dfe05abffdbd4542e40db43fc72918f26bb42a3b` — Document capabilities screen.
- `32dd48ce6f6c4b425700a09370317b532456d705` — Add regression tests for capabilities screen.
- `99bfdce872beebd2cd16896a72aa29ec4a89ec0e` — Register bot capabilities screen.
- `59c20fb4ae8183e210c5521c1172640d5f1300a5` — Clear legacy Telegram command menu.

## Handoff
1. ⬜ CI для текущего head после финальной тарифной матрицы.
2. ⬜ Deploy branch head to VPS и restart `media-hunter.service`.
3. ⬜ Проверить мобильное меню Telegram — старые команды должны исчезнуть.
4. ⬜ Проверить `Моё видео`.
5. ⬜ Проверить YouTube.
6. ⬜ Проверить PNG logo и video+logo.
7. ⬜ Проверить enabled autopost.
8. ⬜ Проверить, что одинаковый watermark не запускает второй FFmpeg.
9. ⬜ Проверить playlist 5–20 видео и fair interleaving с обычными задачами.
10. ⬜ Проверить Premium playlist до 40 видео и отсутствие месячного лимита.
11. ⬜ Проверить playlist >80 MB guard.
12. ⬜ Проверить free playlist quota: 3 запроса/месяц, 20 видео/запрос.
13. ⬜ Проверить Free 1 / Premium 3 channel limit.
14. ⬜ Проверить `ℹ️ Что я умею` и возврат в главное меню.
15. ⬜ Улучшить stderr logging FFmpeg.
16. 🔐 Перевыпустить Bot Token через BotFather из-за раскрытия в логах.
