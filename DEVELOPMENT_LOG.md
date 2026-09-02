# Media Hunter — журнал разработки и передачи контекста

> Единая точка правды для продолжения проекта другим ИИ без повторного пересказа истории.
> Рабочая ветка: `Media_hanter-v3-security`.
> Журнал хранится в GitHub и не копируется на VPS.

## 1. Правила работы

1. Работать в `Media_hanter-v3-security`.
2. Перед исправлением проверять, не закрыта ли проблема текущим кодом.
3. Не менять архитектуру без необходимости.
4. После каждого изменения кода запускать CI/тесты.
5. В журнале фиксировать каждое изменение кода, результат CI и статус серверной проверки.
6. Серверные изменения сначала отмечать `⬜`, после фактической проверки — `✅`.
7. Никогда не записывать секреты, токены, пароли или содержимое `.env`.

## 2. Проект

Telegram-бот Media Hunter: Python + aiogram 3.x + yt-dlp + FFmpeg + SQLite.
Функции: скачивание видео, уникализация, watermark, загрузка собственного видео, автопостинг в Telegram-каналы, Premium, ОПП и админка.

Production:
- VPS с небольшим диском (~9.8 GB).
- Абсолютный входной лимит: 1024 MB.
- Уникализация обязательна для всех видео до 100 MB включительно.
- Local Bot API на VPS: `127.0.0.1:8081`.
- Media Hunter systemd unit: `media-hunter.service`.
- Production Python: `/opt/mediahunter/venv/bin/python`.
- Application root: `/opt/mediahunter/app`.

## 3. Зафиксированные ранее изменения

### Безопасность
- ✅ SSRF-защита `validate_source_url`: HTTP/HTTPS, credentials/control chars, localhost/metadata/internal suffixes, non-global literal/resolved IP.
- ⚠️ Остаточный риск DNS rebinding/redirect-to-internal; mitigation: unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Queue/restart race исправлена через `asyncio.Lock`.
- ✅ Queue accounting и `task_done()` при restart исправлены.
- ✅ Restart завершает связанные subprocess и чистит uploads.
- ✅ Upload проверяет очередь до скачивания файла.
- ✅ Опасная команда reboot VPS удалена.
- ✅ Payment activation атомарна; `telegram_charge_id` защищён unique index.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite работает fail-closed.
- ✅ Пользовательские ошибки фильтруются через `user_errors.py`.

### Медиа
- ✅ `download()` использует `--write-info-json` и сохраняет исходное название.
- ✅ `safe_media_filename()`.
- ✅ Text watermark: цвет, шрифт, размер, позиция, прозрачность.
- ✅ Logo watermark: относительный размер, позиция, прозрачность.
- ✅ Source/upload limit 1024 MB.
- ✅ `yt-dlp --max-filesize` и post-download checks сохранены.
- ⚠️ FFmpeg error logging ранее обрезал stderr до первых 2000 символов; фактическая причина `code=187` требует отдельной диагностики по полному stderr.
- ⚠️ Уникализация всегда выполняет re-encode; текущая цепочка тяжёлая и может быть проблемной на небольшом VPS.

### Зависимости
- ✅ `aiogram==3.31.0`
- ✅ `aiohttp==3.14.3`
- ✅ `python-dotenv==1.1.1`
- ✅ `yt-dlp==2026.8.19`
- ✅ `curl-cffi==0.15.0`
- ✅ TikTok impersonation issue исправлен.

### UI / watermark
- ✅ Основные подписи переведены на русский.
- ✅ «Моё видео» — загрузка собственного видео.
- ✅ Text watermark — пошаговый мастер.
- ✅ Logo watermark — пошаговый мастер: PNG → размер → позиция → прозрачность → сохранение.
- ✅ Размер логотипа: 10/20/30/40/50%.
- ✅ Логотип ограничивается размерами кадра.
- ✅ Канальный watermark отделён от личного watermark.
- ⚠️ В `handlers.py` и `wm_wizard.py` исторически существуют две реализации части watermark/logo flow; перед дальнейшим расширением это нужно держать под контролем.

## 4. Серверный инцидент 2026-09-02

- ✅ `media-hunter.service` ранее падал из-за `ConnectionRefusedError` к `127.0.0.1:8081`.
- ✅ Причина была в правах `mediahunter` на `/var/lib/telegram-bot-api`.
- ✅ Исправлено владение каталогом на `mediahunter:mediahunter`.
- ✅ Local Bot API после исправления стал `active (running)` и слушает `127.0.0.1:8081`.
- ✅ `curl http://127.0.0.1:8081/` возвращал HTTP JSON `404 Not Found`, что подтверждало работу HTTP-сервиса.
- ✅ Media Hunter перешёл в polling и обрабатывал Telegram updates.
- 🔐 Bot Token ранее попал в диагностический вывод; токен должен быть перевыпущен через BotFather. Сам токен в журнал не записывать.

## 5. Инцидент FFmpeg 2026-09-02

По production journal были повторяющиеся ошибки:
- FFmpeg 6.1.1.
- В stderr виден `libdav1d 1.4.1` для некоторых входных видео.
- Несколько разных MP4 приводили к `ffmpeg failed (code=187)`.
- После этого `_run_job` выдавал общий `RuntimeError: Не удалось обработать медиа. Файл повреждён или формат не поддерживается.`
- Логирование FFmpeg показывало только начало stderr, поэтому настоящий финальный error line не был виден.
- Повторяемость на разных MP4 указывает на общую проблему pipeline, но `187` сам по себе не доказывает конкретную причину.

## 6. Последний пользовательский запрос — 2026-09-02

Пользователь явно подтвердил два требования:

1. **Уникализировать все видео менее 100 MB.** Это обязательное бизнес-требование и его нельзя убирать ради оптимизации.
2. **Устранить двойную уникализацию.** Видео не должно сначала полностью обрабатываться для пользователя, а затем повторно обрабатываться с нуля для автопостинга в канал.
3. **Убрать зависшее описание меню.** Текст вида:
   `📺 Каналы\nПодключайте свои Telegram-каналы...`
   не должен оставаться отдельным сообщением снизу после перехода в другой раздел; навигация должна происходить в текущем сообщении.

Пользователь дал согласие на исправление этих багов.

## 7. Изменения, сделанные в текущем сеансе

### 2026-09-02 — попытка исправления двойной обработки
- ⬜ Требование: если есть включённые каналы, не выполнять сначала пользовательскую обработку, а затем повторную обработку исходника для канала.
- Текущая рабочая идея: при включённых каналах обрабатывать исходный файл непосредственно для каждого включённого канала; без каналов — один раз для пользователя.
- Важно: если один и тот же файл должен попасть в несколько каналов с разными watermark, отдельный FFmpeg pass на каждый различающийся результат является нормальным; это не «двойная обработка» одного результата, а независимые выходы из одного исходника.
- ⬜ Требуется отдельный regression test на количество вызовов `process_media`.

### 2026-09-02 — исправление UI stale-description
- ✅ В `wm_wizard.py` middleware больше не отправляет отдельные информационные сообщения при навигации.
- ✅ Навигация выполняется через редактирование текущего сообщения/клавиатуры.
- ✅ Убран источник старого поведения `answer(info...)` из middleware.
- ⚠️ Нужен runtime smoke test в Telegram.

### 2026-09-02 — callback канального watermark
- ✅ Канальный callback приведён к `cwmx:` в `handlers.py`.
- ⚠️ В старом коде `wm_wizard.py` ранее встречался `cwm:`; все оставшиеся callback references должны быть проверены на согласованность.

### 2026-09-02 — UI regression tests
- ✅ `tests/test_ui.py` обновлён под фактические русские подписи текущего меню.
- ✅ Regression test теперь проверяет, что middleware навигации не отправляет старые stale-info сообщения и работает через `edit_text`.
- Commit: `52ee5602b8e94e10c01751d4501313bd723817a3`
- Затем test был уточнён и зафиксирован commit: `f364f5209f9d5bc2aecfaa34b75a8f2681e79fee`.

## 8. CI — текущий результат и важные находки

Workflow: `.github/workflows/tests.yml`.
Он запускается на push/PR в `Media_hanter-v3-security`, устанавливает зависимости, делает `py_compile`, затем `unittest discover`. 

Последний run:
- Run: `33647655449`
- Commit: `731956c5983d1817ee4409649e99f814db729328`
- Status: ❌ failure
- Install dependencies: ✅
- Compile: ✅
- Regression tests: ❌

Причины, обнаруженные CI:

1. ❌ `MAX_USER_QUEUE` используется в `handlers.py`, но не импортирован из `config.py`.
   Ошибка: `NameError: name 'MAX_USER_QUEUE' is not defined`.

2. ❌ В текущей версии `handlers.py` вызов `metadata(source, media_title)` был сделан как awaitable в одной из промежуточных версий; CI выявил `TypeError: object dict can't be used in 'await' expression`. В текущем зафиксированном файле вызов должен быть синхронным: `caption = metadata(source, media_title)`.

3. ❌ Старые UI tests ожидали устаревшие подписи (`📤 Загрузить видео`, `_MAIN_MENU_INFO`). Они были заменены regression-проверкой реального текущего UX.

4. ❌ На oversized-source regression test текущий код до проверки send-limit доходил до ошибки metadata; после исправления metadata test должен снова проверять именно ограничение отправки.

CI не должен считаться зелёным до исправления всех перечисленных проблем.

## 9. Важное замечание по последней попытке правки

Предыдущая попытка массовой замены `handlers.py` через GitHub Contents API не была применена из-за SHA conflict (409). Поэтому текущий `handlers.py` в ветке остался прежним исходным blob, а исправления из той неудачной попытки не считать применёнными.

Не считать двойную уникализацию окончательно исправленной только по предыдущему сообщению ассистента. Нужна фактическая проверка diff/CI.

## 10. Следующая обязательная работа

Перед deployment:

1. Исправить `handlers.py` без потери существующей функциональности:
   - импортировать `BOT_TOKEN`, `LOGO_DIR`, `MAX_USER_QUEUE` и другие реально используемые config constants;
   - исправить `caption = metadata(source, media_title)` без `await`;
   - устранить повторную обработку одного и того же пользовательского результата;
   - сохранить обязательную уникализацию всех видео <=100 MB;
   - сохранить channel-specific watermark.
2. Добавить regression test, доказывающий отсутствие лишнего `process_media` pass.
3. Проверить callback namespace `cwm`/`cwmx` по всему watermark flow.
4. Проверить logo upload end-to-end и наличие `Photo`/`Document` edge cases.
5. Улучшить FFmpeg error logging: сохранять и начало, и последние строки stderr, чтобы следующий `code=187` был диагностируемым.
6. Запустить полный CI.
7. Только после green CI помечать изменения как `✅`.
8. Перед production deployment сделать backup VPS и синхронизировать ветку.

## 11. Production deployment checklist

```bash
cd /opt/mediahunter/app
git remote -v
git branch --show-current
git status
git log -1 --oneline
sudo cp -a /opt/mediahunter/app /opt/mediahunter/app_backup_$(date +%Y%m%d_%H%M%S)
```

Синхронизация:

```bash
git fetch origin
git checkout Media_hanter-v3-security
git reset --hard origin/Media_hanter-v3-security
```

Compile:

```bash
/opt/mediahunter/venv/bin/python -m py_compile media_hunter_bot/processor.py media_hunter_bot/handlers.py media_hunter_bot/db.py media_hunter_bot/config.py main.py
```

После deployment:

```bash
systemctl restart telegram-bot-api.service
systemctl status telegram-bot-api.service --no-pager -l
systemctl restart media-hunter.service
systemctl status media-hunter.service --no-pager -l
journalctl -u media-hunter.service -n 100 --no-pager -o cat
```

## 12. Правило для следующих ИИ

Всегда сначала читать этот журнал, затем изучать текущую ветку и только после этого менять код. После каждой правки обязательно дописывать сюда:
- дату;
- что именно изменено;
- почему;
- какие тесты/CI запущены;
- результат;
- что осталось `⬜`.

Никаких секретов в журнале.
