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
- ✅ `media_hunter_bot/process_cache.py` теперь кэширует по `source + work + audio_only + compress`; watermark намеренно исключён из cache key.
- Поэтому первый `process_media()` создаёт финальный пользовательский файл, а следующий autopost `process_media()` с другим watermark возвращает тот же файл без FFmpeg.
- Compression `False` и `True` остаются разными cache entries: если канал реально требует compression retry, второй encode всё ещё допустим.
- Cache scoped по временному `work`, поэтому результат не может случайно переиспользоваться между разными jobs.
- Commit: `95ea3fcf8903ac29489a06816512b21b6d9e33fe`.
- Добавлен regression test на разные watermark при одинаковом source/work/options: ожидается один processor call.
- Test commit: `8bd812c6ccb2559966b0481627a2d24ff2ff596d`.
- Этот commit CI упал только потому, что старый regression test ожидал разные outputs для разных watermark. Это ожидание больше не соответствует новому exact-copy режиму.
- Тест обновлён: разные watermark при одинаковом non-compressed job должны возвращать один и тот же result.
- Test fix commit: `a90d72b3bc7a3a6474fe27d45cef165d130316e3`.
- CI run `33765082009` был запущен и на момент проверки находился `in_progress`; после завершения проверить итог перед production deploy.

## Autopost cache binding
- Важно: `handlers.py` импортирует `process_media` напрямую (`from .processor import process_media`), поэтому одного patch `processor.process_media` недостаточно.
- ✅ `main.py` после импорта handlers явно делает `_handlers.process_media = _cached_process_entry`.
- Commit: `fdc4df95a1df8a59339d7db9a726e07a01426179`.
- Ранее были production-only regressions в bootstrap wrapper (`TypeError` из-за positional args и `NameError` из-за удалённых globals); они исправлены и покрыты тестами.

## Production smoke test 2026-09-03
- До exact-copy режима: autopost уже работал.
- Последний фактический лог перед exact-copy изменением:
  - private `SEND_VIDEO_DONE` — успешно;
  - autopost `SEND_VIDEO_DONE` — успешно;
  - два `PROCESS_CACHE_MISS` на одном `work`, примерно 3.85s + 3.63s.
- Это подтвердило: автопост исправен, но выполняется лишний encode.
- ⬜ После deploy exact-copy версии ожидается:
  - один `PROCESS_CACHE_MISS`;
  - затем `PROCESS_CACHE_HIT` перед автопостом;
  - отсутствие второго `PROCESS_START`.

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

## Handoff / ближайшие действия
1. ⬜ Дождаться/проверить CI на `a90d72b3bc7a3a6474fe27d45cef165d130316e3`.
2. ⬜ После зелёного CI проверить, что branch head соответствует тестированному commit.
3. ⬜ Deploy branch head на VPS и restart `media-hunter.service`.
4. ⬜ Отправить тестовое видео при включённом autopost.
5. ⬜ Проверить journalctl: один `PROCESS_START`, `PROCESS_CACHE_MISS`, затем `PROCESS_CACHE_HIT`, затем private send и autopost send без второго FFmpeg.
6. ⬜ Проверить `Моё видео`, YouTube, PNG logo и video+logo.
7. ⬜ Проверить playlist и тарифные лимиты.
8. 🔐 Перевыпустить Bot Token через BotFather, если ещё не сделано.
