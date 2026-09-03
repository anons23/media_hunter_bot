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
- Logo upload использует ту же исправленную цепочку.
- 🔐 Bot Token ранее попал в диагностический вывод. Не записывать его в журнал; перед production требуется перевыпуск через BotFather.

## UI / watermark
- ✅ Русские подписи.
- ✅ `Моё видео`.
- ✅ Text watermark wizard и logo wizard, размеры logo 10/20/30/40/50%.
- ✅ Главные кнопки `💧 Водяной знак` и `⚙️ Настройки` скрыты; формат доступен через `📥 Скачать`.
- ✅ Channel watermark callback использует `cwmx:`.
- ✅ Убран middleware, который после `cwmx:*` перезаписывал экран.
- ⚠️ В `handlers.py` существуют старые/новые участки watermark flow; не плодить дубликаты.
- ✅ `ℹ️ Что я умею` добавлена с простой формулировкой и иконками; HTML `<b>` в обычном тексте больше не должен отображаться как сырой тег.
- ✅ При открытии text/logo watermark пользователь видит уже настроенное значение и может его изменить или удалить.
- ✅ Autopost toggle использует async DB API `aset_channel_enabled()`.

## Telegram command menu
- В `media_hunter_bot/__init__.py` после успешного `Bot.get_me()` вызывается `delete_my_commands()` для очистки старого default command menu.
- Commit: `59c20fb4ae8183e210c5521c1172640d5f1300a5`.
- ⬜ Если старые команды Telegram всё ещё видны, проверить scoped commands/languages через BotFather/API.

## Autopost: exact-copy режим — 2026-09-03
### Что было
- `_run_job()` сначала создавал `result` для private send, затем для каждого enabled channel снова вызывал `process_media(source, ..., channel_wm)`.
- Production smoke test показывал два последовательных `PROCESS_START` примерно по 3–4 секунды каждый. Ошибок уже не было, но видео кодировалось повторно.
- Предыдущий cache был привязан к source + work + watermark + audio_only + compress. Поэтому разные watermark профили давали `MISS` и второй FFmpeg.

### Новое требование пользователя
- После того как бот отправил готовое видео пользователю, **не переделывать его для автопоста**.
- В канал должен уходить **тот же самый готовый результат**.
- Это сохраняет одну уникализацию/обработку на job и устраняет второй encode.
- Следствие: отдельный channel watermark больше не применяется к автопост-копии. Если пользователю нужен другой watermark именно в канале, это уже отдельный режим и потребует дополнительной обработки.

### Реализация
- `media_hunter_bot/process_cache.py` кэшировал по `source + work + audio_only + compress`; watermark был исключён из cache key.
- Это давало exact-copy для одного канала, но при нескольких каналах не позволяло каждому каналу иметь собственный watermark.
- Exact-copy code commit: `95ea3fcf8903ac29489a06816512b21b6d9e33fe`.
- Test fix commit: `a90d72b3bc7a3a6474fe27d45cef165d130316e3`.

## Autopost: frozen unique base + channel variants — 2026-09-03
### Новая схема
- Пользователь предложил разделить обработку на два этапа: один раз сделать уникализацию и сохранить её результат, а затем накладывать разные watermark для нескольких каналов.
- Реализована схема:
  - **0/1 enabled autopost channel:** сохраняется быстрый exact-copy режим — один готовый результат используется повторно.
  - **2–3 enabled autopost channels:** сначала один раз создаётся `unique_base.mp4` **без watermark**; этот файл считается зафиксированной уникализированной базой текущего job.
  - Пользовательский результат и каждый channel result создаются из `unique_base.mp4` через watermark-only стадию.
  - Повторная уникализация для второго/третьего канала не выполняется.
- `unique_base.mp4` хранится в том же временном `work` каталоге до завершения job; существующий cleanup удаляет каталог после отправок. Это и есть контролируемая временная фиксация результата вместо искусственной `sleep()` паузы.
- Варианты watermark получают отдельные файлы `watermark_<profile>.mp4`, поэтому разные настройки каналов не конфликтуют.
- Если watermark отсутствует, возвращается сам `unique_base.mp4` без лишнего FFmpeg.

### Изменения кода
- `media_hunter_bot/optimized_processor.py`: вынесен общий FFmpeg runner и добавлен `apply_watermark()`, который накладывает только watermark на уже уникализированное видео; uniqueness filter в этой стадии не используется.
- `media_hunter_bot/process_cache.py`: количество enabled каналов определяется по пользователю из имени job work directory; для нескольких каналов создаётся и сохраняется `unique_base.mp4`, затем используются watermark-only variants.
- `tests/test_process_cache.py`: добавлены проверки одного канала, frozen base для трёх каналов, возврата base без watermark и независимого compression cache entry.
- Commits:
  - `6004e6e3f62754ab2f3098128941934e1d5b0e11` — add frozen unique base and watermark-only processing stage.
  - `64e220e667f5d83202cbe5081c39f74ccfb0c6bb` — freeze unique base for multi-channel watermark variants.
- CI после этих двух code commits автоматически запущен:
  - run `33766411230` для `64e220e667f5d83202cbe5081c39f74ccfb0c6bb` — `in_progress` на момент записи;
  - run `33766434785` для `aa248aa50e0ee61d69c129ded0a8cc08d658c9f7` (test commit) — `queued` на момент записи.
- ⬜ Перед production deploy обязательно подтвердить green итог обоих/последнего актуального run.

### Ожидаемое поведение в production
Для 1 канала:
`unique/process → private send → exact same file to channel`.

Для 2–3 каналов:
`source → UNIQUE_BASE_CREATE → unique_base.mp4 → user/channel watermark variants → sends`.

Ожидаемые диагностические строки для multi-channel job:
- `UNIQUE_BASE_CREATE`
- `UNIQUE_BASE_READY`
- один уникализирующий `PROCESS_*`
- `WATERMARK_VARIANT_CREATE` для каждого отличающегося watermark
- при повторном использовании того же профиля `WATERMARK_VARIANT_HIT`
- отсутствие повторного uniqueness pass для channel #2/#3.

## YouTube playlists — 2026-09-03
- Плейлист не должен занимать worker всеми видео сразу.
- `media_hunter_bot/playlist_support.py` подключается после импорта handlers из root `main.py`.
- Плейлист — одна логическая задача; следующий элемент ставится после завершения предыдущего.
- Каждый элемент: скачать → уникализировать → watermark → отправить/autopost → следующий элемент.
- Continuation priority = `2`; обычный Free = `1`; обычный Premium = `0`.
- Premium не прерывает уже выполняющийся FFmpeg/yt-dlp, но после освобождения worker идёт раньше Free и playlist continuation.
- Free: максимум 20 видео за playlist request и 3 playlist requests в календарный месяц.
- Premium: максимум 40 видео за playlist request, без месячного лимита playlist requests.
- Playlist video source limit: 80 MB; если размер известен заранее и >80 MB, загрузка не начинается; если неизвестен, проверяется после загрузки до FFmpeg.
- Обычные URL и `Моё видео` не получили новый 80 MB лимит.
- Состояние continuation в памяти; restart/cancel останавливает продолжение.
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
- ✅ Полный рабочий `handlers.py` восстановлен из точки `6842889`.
- Restore commit: `a559a8dc79447a0e65a04009226b9d0123b5bc78`.
- Не делать широких rewrite `handlers.py` без необходимости.

## Tests / CI
- `.github/workflows/tests.yml`: install dependencies → compile → `python -m unittest discover -s tests -v`.
- Последний подтверждённый зелёный CI до exact-copy тестового изменения: run `33762724035` для journal/hardening commit `ae7e28244450f71793f0dc9b2158de33face08af`.
- Run `33764835219` на `8bd812c6ccb2559966b0481627a2d24ff2ff596d` — ❌ regression test, потому что старый тест ожидал разные outputs для разных watermark; compile и остальные 46 тестов прошли.
- Run `33765082009` на `a90d72b3bc7a3a6474fe27d45cef165d130316e3` — ⏳ проверялся; итог должен быть подтверждён после завершения.
- Exact-copy code commit: `95ea3fcf8903ac29489a06816512b21b6d9e33fe`.
- Multi-channel frozen-base code/test commits: `6004e6e3f62754ab2f3098128941934e1d5b0e11`, `64e220e667f5d83202cbe5081c39f74ccfb0c6bb`, `aa248aa50e0ee61d69c129ded0a8cc08d658c9f7`.

## Handoff / ближайшие действия
1. ⬜ Дождаться/проверить CI на `64e220e667f5d83202cbe5081c39f74ccfb0c6bb` и `aa248aa50e0ee61d69c129ded0a8cc08d658c9f7`.
2. ⬜ После зелёного CI проверить branch head.
3. ⬜ Deploy branch head на VPS и restart `media-hunter.service`.
4. ⬜ Тест с 1 enabled channel: пользователь и канал должны получить один и тот же готовый файл без второго processing.
5. ⬜ Тест с 2 channels и разными watermark: одна `UNIQUE_BASE_CREATE`, затем отдельные variants без повторной uniqueness.
6. ⬜ Проверить случай 3 channels.
7. ⬜ Проверить `Моё видео`, YouTube, PNG logo и video+logo.
8. ⬜ Проверить playlist и тарифные лимиты.
9. 🔐 Перевыпустить Bot Token через BotFather, если ещё не сделано.
