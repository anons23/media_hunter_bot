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
- ✅ Text watermark: цвет, шрифт, размер, позиция, прозрачность.
- ✅ Source/upload limit 1024 MB.
- ✅ `yt-dlp --max-filesize` и post-download checks сохранены.
- ✅ Pre-download disk guard не возвращали из-за реального маленького диска VPS.

### TikTok / зависимости
- ✅ Исправлен TikTok impersonation issue.
- ✅ Зафиксированы: `aiogram==3.31.0`, `aiohttp==3.14.3`, `python-dotenv==1.1.1`, `yt-dlp==2026.8.19`, `curl-cffi==0.15.0`.
- ✅ TikTok test проходил после установки этих зависимостей.

### UI
- ✅ Основные видимые подписи переведены на русский.
- ✅ «Моё видео» приведено к более понятной загрузке собственного видео.
- ✅ Есть информационные подсказки для основных разделов.
- ✅ Text watermark wizard уже пошаговый: текст → цвет → шрифт → размер → позиция → прозрачность → сохранение.

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
- ✅ Последние известные commits: README `7613608...`, CI cleanup `0e5025...`, transactional revoke `9fbddf...`, regression test `dbb6ecf...`.

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

Правильные команды:
```bash
systemctl status media-hunter --no-pager
systemctl restart media-hunter
systemctl stop media-hunter
systemctl start media-hunter
systemctl enable media-hunter
journalctl -u media-hunter -n 100 --no-pager
```

### Telegram Local Bot API
- Unit: `/etc/systemd/system/telegram-bot-api.service`.
- Binary: `/usr/local/bin/telegram-bot-api`.
- EnvironmentFile: `/root/telegram-bot-api.env`.
- Working/data directory: `/var/lib/telegram-bot-api`.
- Temp directory: `/var/lib/telegram-bot-api/temp`.
- Listen: `127.0.0.1:8081`.
- Service User/Group: `mediahunter`.

Правильные команды:
```bash
systemctl status telegram-bot-api --no-pager
systemctl restart telegram-bot-api
systemctl stop telegram-bot-api
systemctl start telegram-bot-api
journalctl -u telegram-bot-api -n 100 --no-pager
```

### Firewall
- ✅ UFW используется.
- ✅ Incoming default deny.
- ✅ SSH 22 разрешён.
- ✅ Outgoing allow.
- ⚠️ Это не process-specific egress isolation. SSRF residual risk остаётся.

## 5. Фактический серверный инцидент 2026-09-02

- ✅ `media-hunter.service` изначально падал с `ConnectionRefusedError` к `127.0.0.1:8081`.
- ✅ Причина была найдена в `telegram-bot-api.service`: `mediahunter` не мог писать в `/var/lib/telegram-bot-api`.
- ✅ Исправлено: `chown -R mediahunter:mediahunter /var/lib/telegram-bot-api`.
- ✅ Каталог `temp` также принадлежит `mediahunter:mediahunter`.
- ✅ Local Bot API после исправления стал `active (running)` и слушает `127.0.0.1:8081`.
- ✅ `curl http://127.0.0.1:8081/` получает JSON `404 Not Found`, то есть HTTP-сервис отвечает.
- ✅ Media Hunter после запуска перешёл в polling: `Start polling` и `Run polling for bot @vidos_hunter_bot`.
- ✅ Бот обработал реальные Telegram updates.
- ℹ️ Исторические restart counters были большими (~9400 для Media Hunter и ~14500 для Local Bot API), но причина установлена и устранена.
- 🔐 Никогда не записывать секретный Bot Token в этот журнал.

## 6. Последняя проверенная рабочая точка сервера

На 2026-09-02 после исправления прав:
- `telegram-bot-api.service` — active/running.
- `127.0.0.1:8081` — LISTEN.
- `media-hunter.service` — active/running.
- Media Hunter успешно начал polling и обработал updates.

## 7. CI / deployment

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

- ⬜ `/start` и главное меню.
- ⬜ Скачать видео по ссылке.
- ⬜ Загрузить собственное видео.
- ⬜ Text watermark.
- ⬜ Logo watermark.
- ⬜ Premium.
- ⬜ Admin Premium grant/revoke.
- ⬜ ОПП/private invite.
- ⬜ Autoposting.

## 9. Остаточный security-риск

Приложение блокирует известные private/loopback destinations, но DNS rebinding и redirect-to-internal остаются остаточным риском, потому что сетевое соединение выполняет `yt-dlp` в subprocess. Production mitigation: unprivileged user + process/network egress isolation.

## 10. Новый UI/Watermark запрос от пользователя — 2026-09-02

### Этап A — текстовый watermark

- ✅ Текущий принцип уже соответствует требованию: пользователь вводит только текст, после чего бот по очереди показывает кнопки выбора.
- ⬜ Сделать текстовые настройки максимально понятными для пользователя и убрать любой старый формат вида `ТЕКСТ|ПОЗИЦИЯ|РАЗМЕР|ЦВЕТ|ПРОЗРАЧНОСТЬ` из пользовательского интерфейса.
- ⬜ Оставить пошаговый сценарий: `введите текст` → `выберите цвет` → `выберите шрифт/стиль` → `выберите размер` → `выберите расположение` → `выберите прозрачность` → `подтвердите`.
- ⬜ Все названия кнопок и подсказок — на русском.
- ⬜ Для цвета использовать удобный набор кнопок: белый, чёрный, красный, жёлтый, оранжевый, зелёный, синий, голубой, розовый, фиолетовый и другие безопасно поддерживаемые цвета.
- ⬜ Для шрифта использовать понятные варианты: обычный, жирный, засечками, моноширинный; при наличии безопасного системного шрифта можно добавить курсив.

### Этап B — logo watermark

Текущий баг: загруженный логотип накладывается в исходном размере и может занять почти весь кадр.

- ⬜ После загрузки логотипа не сохранять его сразу с фиксированным размером.
- ⬜ Сделать пошаговый мастер логотипа: `загрузите логотип` → `выберите размер` → `выберите расположение` → `выберите прозрачность` → `готово`.
- ⬜ Размер должен быть относительным к видео, чтобы логотип автоматически помещался в кадр. Использовать понятные пресеты в процентах ширины видео, а не пиксели исходной картинки.
- ⬜ Дать кнопки нескольких размеров, например `10%`, `20%`, `30%`, `40%`, `50%` ширины кадра.
- ⬜ Дать кнопки положения: верх слева, верх справа, центр, низ слева, низ справа.
- ⬜ Дать кнопки прозрачности: слабая/средняя/заметная/яркая.
- ⬜ Сохранить выбранные настройки в watermark JSON пользователя или канала без нарушения существующей схемы.
- ⬜ Не ломать существующее ограничение пути логотипа и очистку неиспользуемых логотипов.

### Этап C — главный watermark и watermark канала

- ✅ В коде уже существуют две независимые настройки: user watermark (`users.watermark`) и channel watermark (`channels.watermark`).
- ✅ Главная кнопка `💧 Водяной знак` настраивает user watermark для видео, отправляемого самому пользователю.
- ✅ В разделе `📺 Каналы` watermark канала настраивает отдельный watermark для автопубликации именно в выбранный канал.
- ⬜ Сделать это различие очевидным в текстах интерфейса, чтобы пользователь сразу понимал: главный watermark = мои получаемые видео; watermark канала = публикация в конкретный канал.
- ⬜ Убрать оставшиеся английские `Watermark` и заменить на `💧 Водяной знак`.
- ⬜ Убрать/перевести оставшийся `PNG` там, где пользователю понятнее написать `🖼 Логотип`.

### Этап D — «Моё видео»

- ⬜ Изменить описание раздела с `Отправьте видео до 1024 МБ.` на более понятное:
  `📤 Отправьте видео с вашего устройства.`
- ⬜ Проверить, что реальная загрузка видео с телефона/устройства продолжает работать.

### Этап E — регрессия и проверка

- ⬜ Добавить/обновить UI regression tests для русских подписей каналов, логотипа и «Моё видео».
- ⬜ Добавить regression tests для сохранения logo size/position/opacity.
- ⬜ Проверить, что текстовый watermark по-прежнему сохраняется с выбранными параметрами.
- ⬜ Запустить полный CI.
- ⬜ После CI обновить этот раздел зелёными `✅` по реально выполненным пунктам.
- ⬜ После деплоя повторно проверить на VPS: логотип на маленьком размере, позиция, прозрачность, текстовый мастер, загрузка видео с телефона.

## 11. Последняя точка продолжения для другого ИИ

Рабочая ветка: `Media_hanter-v3-security`.

Сервер сейчас рабочий после исправления прав Local Bot API.

Главная текущая задача: выполнить новый UI/watermark план из раздела 10 без изменения архитектуры. Текстовый мастер не переписывать без необходимости — он уже пошаговый. Основное новое исправление: сделать logo watermark относительного размера/позиции/прозрачности и понятный русский мастер.

После каждого реально завершённого пункта обновлять этот журнал и менять только подтверждённый `⬜` на `✅`.
