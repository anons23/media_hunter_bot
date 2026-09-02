# Media Hunter — журнал разработки и передачи контекста

> Единая точка правды для продолжения проекта другим ИИ без повторного пересказа истории.
> Рабочая ветка: `Media_hanter-v3-security`.
> Этот файл хранится только в GitHub и не копируется на VPS.

## 1. Правила работы

1. Работать в `Media_hanter-v3-security`.
2. Не создавать новую ветку без необходимости.
3. Перед исправлением проверять, не закрыта ли проблема текущим кодом.
4. Не менять архитектуру без необходимости.
5. Исправлять реальные баги/UX-проблемы перед запуском.
6. После изменения запускать тесты/CI; только после успешной проверки ставить `✅`.
7. Серверные изменения сначала записывать как `⬜`, после фактической проверки переводить в `✅`.
8. Не записывать в журнал секреты, токены, пароли или содержимое `.env`.

## 2. Проект и production-ограничения

Telegram-бот Media Hunter: Python + aiogram 3.x + yt-dlp + ffmpeg + SQLite.
Функции: скачивание и обработка медиа, уникализация, watermark, загрузка пользовательского видео, автопостинг, Premium, ОПП и админка.

Production:
- VPS с небольшим диском (~9.8 GB).
- Максимальный входной файл проекта: 1024 MB.
- Telegram Bot API: ориентир около 2 GB.
- Лимиты не увеличивать только ради рекомендаций аудита.
- Local Bot API используется локально на VPS через `127.0.0.1:8081`.

## 3. Уже выполнено

### Безопасность
- ✅ SSRF-защита `processor.validate_source_url`: HTTP/HTTPS, запрет credentials/control chars, localhost/metadata/internal suffixes, non-global literal/resolved IP.
- ✅ В README и коде зафиксирован остаточный риск DNS rebinding/redirect-to-internal; нужен unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Исправлена гонка `Engine.add()`/`restart()` через `asyncio.Lock`.
- ✅ Исправлены queue accounting и `task_done()` при restart.
- ✅ Restart завершает связанные subprocess и чистит uploads.
- ✅ Upload сначала проверяет очередь, затем скачивает файл.
- ✅ Удалена опасная команда reboot VPS из бота.
- ✅ Payment activation атомарна, `telegram_charge_id` защищён unique index.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite fail-closed.
- ✅ Пользовательские ошибки фильтруются через `user_errors.py`.

### Медиа / лимиты
- ✅ `download()` использует `--write-info-json` и возвращает `(file_path, title)`.
- ✅ `safe_media_filename()`.
- ✅ Сохранение исходного названия видео.
- ✅ Text watermark поддерживает цвет, шрифт, размер, позицию и прозрачность.
- ✅ Logo watermark теперь поддерживает относительный размер к кадру, позицию и прозрачность.
- ✅ Source/upload limit 1024 MB.
- ✅ `yt-dlp --max-filesize` и post-download checks сохранены.
- ✅ Pre-download disk guard не возвращали из-за реального маленького диска VPS.

### TikTok / зависимости
- ✅ Исправлен TikTok impersonation issue.
- ✅ Зафиксированы: `aiogram==3.31.0`, `aiohttp==3.14.3`, `python-dotenv==1.1.1`, `yt-dlp==2026.8.19`, `curl-cffi==0.15.0`.
- ✅ TikTok test проходил после установки этих зависимостей.

### UI
- ✅ Основные видимые подписи переведены на русский.
- ✅ «Моё видео» ориентировано на загрузку собственного видео.
- ✅ Есть информационные подсказки для основных разделов.
- ✅ Text watermark wizard уже пошаговый: текст → цвет → шрифт → размер → позиция → прозрачность → сохранение.
- ✅ Пользовательский текстовый интерфейс больше не требует ручного ввода строки `ТЕКСТ|ПОЗИЦИЯ|РАЗМЕР|ЦВЕТ|ПРОЗРАЧНОСТЬ`.
- ✅ Logo watermark переведён на пошаговый мастер: загрузка PNG → размер → позиция → прозрачность → сохранение.
- ✅ Размер логотипа задаётся относительными пресетами 10/20/30/40/50% и автоматически масштабируется под размеры видео с ограничением по ширине и высоте кадра.
- ✅ Логотип получает выбранную прозрачность при подготовке к наложению.
- ✅ Канальный интерфейс использует `💧 Водяной знак`, а не `Watermark`, и `🖼 Логотип`, а не техническое `PNG`.
- ✅ Пользовательское описание загрузки изменено на `📤 Отправьте видео с вашего устройства.`.
- ✅ Главный watermark явно описан как личный watermark для видео, которое получает пользователь.
- ✅ Канальный watermark явно описан как отдельная настройка для автопубликации в выбранный канал.

### Admin Premium
- ✅ Админка только для `ADMIN_ID`.
- ✅ Ручные Premium grants в `admin_premium.py`.
- ✅ Выдача на 1–3650 дней, список и отзыв.
- ✅ Paid Premium сохраняется при отзыве ручного grant.
- ✅ Неизвестному пользователю grant не выдаётся.
- ✅ Regression tests добавлены.
- ✅ Revoke переведён на одну SQLite `BEGIN IMMEDIATE` транзакцию.

### Ветки / CI
- ✅ Старые ветки удалены; оставлены `main` и `Media_hanter-v3-security`.
- ✅ README исправлен с 1536 MB на 1024 MB.
- ✅ CI очищен от ссылки на удалённую `Media_hanter-v3`.
- ⬜ После последних UI-изменений подтвердить новый green CI.

## 4. Сервер — точная карта VPS

### Приложение
- `/opt/mediahunter/app` — корень приложения.
- `/opt/mediahunter/app/main.py` — запуск.
- `/opt/mediahunter/venv` — production venv.
- `/opt/mediahunter/venv/bin/python` — production Python.
- `/opt/mediahunter/venv/bin/yt-dlp` — yt-dlp.
- `/opt/mediahunter/app/.env` — конфигурация бота.
- `/opt/mediahunter/app/data` — данные приложения.
- `/opt/mediahunter/app/media` — media/work data приложения.
- `/opt/mediahunter/data` — дополнительные данные.
- `/opt/mediahunter/work` — дополнительный work directory.

### Media Hunter systemd
- Unit: `/etc/systemd/system/media-hunter.service`.
- Точное имя: **`media-hunter.service`**. Не использовать `mediahunter.service`.
- User/Group: `mediahunter`.
- User shell: `nologin`.
- WorkingDirectory: `/opt/mediahunter/app`.
- ExecStart: `/opt/mediahunter/venv/bin/python /opt/mediahunter/app/main.py`.
- EnvironmentFile: `/opt/mediahunter/app/.env`.
- PATH содержит `/opt/mediahunter/venv/bin`.
- `Restart=always`, `RestartSec=5`.
- Включены `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, kernel hardening, пустые capabilities и `ReadWritePaths` только для нужных каталогов.

### Telegram Local Bot API
- Unit: `/etc/systemd/system/telegram-bot-api.service`.
- Binary: `/usr/local/bin/telegram-bot-api`.
- EnvironmentFile: `/root/telegram-bot-api.env`.
- Working/data directory: `/var/lib/telegram-bot-api`.
- Temp directory: `/var/lib/telegram-bot-api/temp`.
- Listen: `127.0.0.1:8081`.
- Service User/Group: `mediahunter`.

### Firewall
- ✅ UFW используется.
- ✅ Incoming default deny.
- ✅ SSH 22 разрешён.
- ✅ Outgoing allow.
- ⚠️ Это не process-specific egress isolation. SSRF residual risk остаётся.

## 5. Фактический серверный инцидент 2026-09-02

- ✅ `media-hunter.service` падал с `ConnectionRefusedError` к `127.0.0.1:8081`.
- ✅ Причина была найдена в `telegram-bot-api.service`: `mediahunter` не мог писать в `/var/lib/telegram-bot-api`.
- ✅ Исправлено: `chown -R mediahunter:mediahunter /var/lib/telegram-bot-api`.
- ✅ Каталог `temp` также принадлежит `mediahunter:mediahunter`.
- ✅ Local Bot API после исправления стал `active (running)` и слушает `127.0.0.1:8081`.
- ✅ `curl http://127.0.0.1:8081/` получает JSON `404 Not Found`, то есть HTTP-сервис отвечает.
- ✅ Media Hunter после запуска перешёл в polling: `Start polling` и `Run polling for bot @vidos_hunter_bot`.
- ✅ Бот обработал реальные Telegram updates.
- ℹ️ Исторические restart counters были большими (~9400 для Media Hunter и ~14500 для Local Bot API), но причина установлена и устранена.
- 🔐 Секретный Bot Token в журнал не записывать. Так как токен был раскрыт в диагностическом выводе, его следует перевыпустить через BotFather перед финальным production deployment.

## 6. Последняя проверенная рабочая точка сервера

На 2026-09-02 после исправления прав:
- `telegram-bot-api.service` — active/running.
- `127.0.0.1:8081` — LISTEN.
- `media-hunter.service` — active/running.
- Media Hunter успешно начал polling и обработал updates.
- ✅ Пользователь подтвердил, что бот работает.
- ✅ Пользователь подтвердил загрузку логотипа и собственного видео с телефона.

## 7. Deployment / CI

Перед изменением production:
```bash
cd /opt/mediahunter/app
git remote -v
git branch --show-current
git status
git log -1 --oneline
sudo cp -a /opt/mediahunter/app /opt/mediahunter/app_backup_$(date +%Y%m%d_%H%M%S)
```

Предпочтительный Git remote:
`git@github.com:anons23/media_hunter_bot.git`

Синхронизация:
```bash
git fetch origin
git checkout Media_hanter-v3-security
git reset --hard origin/Media_hanter-v3-security
```

Зависимости:
```bash
/opt/mediahunter/venv/bin/python -m pip install -r media_hunter_bot/requirements.txt
```

Compile:
```bash
/opt/mediahunter/venv/bin/python -m py_compile media_hunter_bot/processor.py media_hunter_bot/handlers.py media_hunter_bot/db.py media_hunter_bot/config.py main.py
```

После deployment сначала запускать `telegram-bot-api`, проверять `8081`, затем `media-hunter`, затем смотреть journal и только после этого делать smoke tests.

## 8. Runtime smoke tests

- ✅ Bot starts and polls Telegram.
- ✅ Uploading own video from phone works (user confirmed).
- ✅ Logo upload works (user confirmed).
- ⬜ Verify small/medium/large logo presets on real videos.
- ⬜ Verify logo position and transparency on real videos.
- ⬜ Verify text watermark wizard end-to-end.
- ⬜ Premium.
- ⬜ Admin Premium grant/revoke.
- ⬜ ОПП/private invite.
- ⬜ Autoposting.

## 9. Остаточный security-риск

Приложение блокирует известные private/loopback destinations, но DNS rebinding и redirect-to-internal остаются остаточным риском, потому что сетевое соединение выполняет `yt-dlp` в subprocess. Production mitigation: unprivileged user + process/network egress isolation.

## 10. Новый UI/Watermark запрос от пользователя — 2026-09-02

### Этап A — текстовый watermark

- ✅ Оставлен пошаговый UX без ручной строки с разделителями.
- ✅ Сценарий: `введите текст` → `выберите цвет` → `выберите шрифт/стиль` → `выберите размер` → `выберите расположение` → `выберите прозрачность` → `сохраните`.
- ✅ Цвета представлены русскими кнопками.
- ✅ Шрифт представлен русскими кнопками; реализованы обычный, жирный, с засечками и моноширинный.
- ⬜ При необходимости позже добавить отдельный курсивный системный шрифт, не меняя текущую архитектуру.

### Этап B — logo watermark

- ✅ Убран старый принцип мгновенного сохранения логотипа в исходном размере.
- ✅ Сделан пошаговый мастер: `загрузите PNG` → `размер` → `положение` → `прозрачность` → `сохранить`.
- ✅ Размер логотипа относительный к видео: 10%, 20%, 30%, 40%, 50%.
- ✅ Масштабирование учитывает одновременно ширину и высоту кадра, чтобы логотип не выходил за разумные границы.
- ✅ Положение: верх слева, верх справа, центр, низ слева, низ справа.
- ✅ Прозрачность: 40%, 60%, 80%, 100%.
- ✅ Настройки сохраняются в существующем watermark JSON пользователя или канала.
- ✅ Старое ограничение пути логотипа не отменено; перед обработкой путь снова проверяется внутри `LOGO_DIR`.
- ⬜ Проверить все пресеты на реальном видео после deployment.

### Этап C — главный watermark и watermark канала

- ✅ `users.watermark` и `channels.watermark` остаются независимыми настройками.
- ✅ Главная кнопка `💧 Водяной знак` настраивает watermark для видео, которое пользователь получает лично.
- ✅ `📺 Каналы` → выбранный канал → `💧 Водяной знак` настраивает watermark для автопубликации именно в этот канал.
- ✅ Русская формулировка теперь объясняет это различие.
- ✅ Убрано техническое слово `Watermark` из пользовательского интерфейса.
- ✅ `PNG` в пользовательском меню заменён на понятное `Логотип`.

### Этап D — «Моё видео»

- ✅ Описание изменено на `📤 Отправьте видео с вашего устройства.`.
- ✅ Реальная загрузка видео с телефона уже подтверждена пользователем.

### Этап E — регрессия и проверка

- ✅ Добавлены/обновлены UI regression tests для русских подписей watermark и загрузки видео.
- ✅ Добавлены тесты наличия logo-size пресетов и русских канал/водяной знак подсказок.
- ⬜ Подтвердить, что свежий CI завершился `success` после последних изменений.
- ⬜ После CI и deployment проверить логотип на 10/20/30/40/50%, позиции и прозрачность.
- ⬜ После CI и deployment проверить text watermark end-to-end.

## 11. Последняя точка продолжения для другого ИИ

Рабочая ветка: `Media_hanter-v3-security`.

Сервер сейчас рабочий после исправления прав Local Bot API.

Последние UI commits:
- `918d2e69af260825ec457461d25ddcee27c5099d` — logo size/position/opacity wizard and watermark UI improvements.
- `97bdb489f6bfdaefd28d5128c59b230738385f7d` — UI regression tests.

Главная текущая задача: подтвердить green CI и затем провести реальные smoke-тесты нового logo/text watermark. Не менять архитектуру без необходимости.

После каждого реально завершённого пункта обновлять этот журнал и менять только подтверждённый `⬜` на `✅`.
