# Media Hunter — журнал разработки и передачи контекста

> **Назначение:** единая точка правды для продолжения разработки другим ИИ без повторного пересказа истории проекта.
> **Рабочая ветка:** `Media_hanter-v3-security`
> **Важно:** этот файл хранится только в GitHub и **не копируется на сервер**.

## 1. Правила работы

1. Работать в `Media_hanter-v3-security`.
2. Не создавать новую ветку без необходимости.
3. Перед исправлением проверять, не закрыта ли проблема текущим кодом.
4. Не менять архитектуру без необходимости.
5. Исправлять прежде всего реальные баги/риски перед запуском.
6. После изменения запускать тесты/CI; только после успешной проверки ставить `✅`.
7. Серверные действия фиксировать здесь: сначала `⬜` план, после фактической проверки `✅`.

## 2. Текущий проект

Telegram-бот Media Hunter: Python + aiogram 3.x + yt-dlp + ffmpeg + SQLite.
Основные функции: скачивание и обработка медиа, уникализация, watermark, загрузка пользовательского видео, автопостинг, Premium, ОПП и админка.

Ограничения production:
- VPS: небольшой диск (~9.8 GB).
- Лимит входного файла проекта: **1024 MB**.
- Telegram Bot API: ориентироваться примерно на максимум 2 GB.
- Не увеличивать лимиты только ради рекомендаций аудита.

## 3. Выполненные изменения

### Безопасность

- ✅ SSRF-защита `processor.validate_source_url`: только HTTP/HTTPS; запрещены credentials и control chars; блокируются localhost/metadata/internal suffixes; literal non-global IP запрещены; DNS resolution отклоняет любой non-global адрес.
- ✅ В коде/README явно указан остаточный риск DNS rebinding/redirect и необходимость production egress isolation.
- ✅ Logo path confinement: логотипы не могут выходить за `LOGO_DIR`.
- ✅ Исправлена гонка `Engine.add()` ↔ `restart()` через `asyncio.Lock`.
- ✅ Исправлен учёт очереди и `task_done()` при restart.
- ✅ Restart очищает queued jobs и завершает связанные subprocess.
- ✅ Upload проверяет возможность постановки задачи до скачивания Telegram-файла.
- ✅ Удалена опасная команда перезапуска VPS из бота.
- ✅ Payment activation атомарна, duplicate `charge_id` защищён unique index/проверками.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite работает fail-closed.
- ✅ Пользовательские ошибки фильтруются через `user_errors.py`.

### Медиа / лимиты

- ✅ `processor.download()` использует `--write-info-json` и возвращает `(file_path, title)`.
- ✅ Добавлен `safe_media_filename()` для безопасного имени результата.
- ✅ Результат использует безопасное название исходного видео вместо generic filename, где это возможно.
- ✅ Watermark поддерживает текст/логотип, цвет, шрифт, размер, позицию и прозрачность.
- ✅ Production source/upload limit: **1024 MB**.
- ✅ Лишний pre-download disk guard не возвращали: на реальном VPS он требовал бы слишком много свободного места. `--max-filesize` и post-download checks сохранены.

### TikTok / зависимости

- ✅ Исправлен TikTok impersonation issue.
- ✅ Зафиксированы зависимости:
  - `aiogram==3.31.0`
  - `aiohttp==3.14.3`
  - `python-dotenv==1.1.1`
  - `yt-dlp==2026.8.19`
  - `curl-cffi==0.15.0`
- ✅ Прямой TikTok test после установки этих зависимостей проходил.

### Интерфейс

- ✅ Видимые английские подписи основных кнопок переведены на русский.
- ✅ «Моё видео» переименовано/сделано понятнее как раздел загрузки собственного видео.
- ✅ Добавлены информационные объяснения после нажатия основных разделов.
- ✅ Watermark UI полностью переведён на русский.
- ✅ UI middleware `_friendly_menu()`/help-layer приводит пользовательские подписи к русскому виду.

### Админка / Premium

- ✅ «Админка» видна только `ADMIN_ID`.
- ✅ Админские callbacks отдельно проверяют `ADMIN_ID`.
- ✅ Добавлено ручное управление Premium.
- ✅ Создан `media_hunter_bot/admin_premium.py`.
- ✅ Ручные grants хранятся отдельно в `admin_premium_grants`.
- ✅ Можно выдать Premium на 1–3650 дней.
- ✅ Можно посмотреть активные ручные grants.
- ✅ Можно отозвать ручной grant.
- ✅ При отзыве оплаченный Premium должен сохраняться.
- ✅ Неизвестный пользователь не может получить grant.
- ✅ Добавлены `tests/test_admin_premium.py`.

### Журнал / ветки

- ✅ Создан `DEVELOPMENT_LOG.md`.
- ✅ Старые ветки удалены вручную: `Media_hanter-v3`, `feat/opp-stats-handlers`, `handlers-preproduction-fixes`, `media-hunter-v2`.
- ✅ В репозитории оставлены только `main` и `Media_hanter-v3-security`.

## 4. Исправления после финального аудита

- ✅ README исправлен: старые `1536 MB` заменены на актуальные **1024 MB**.
- ✅ CI workflow очищен от ссылки на удалённую ветку `Media_hanter-v3`.
- ✅ Admin Premium revoke переведён на одну SQLite-транзакцию с `BEGIN IMMEDIATE`, чтобы платёж не мог вклиниться между чтением платежей и восстановлением `premium_until`.
- ✅ Добавлен regression test для транзакционного revoke.

Важные commits этого этапа:
- `7613608d25b2ee3ee2968189fd606cb1e53b9ce4` — README limit fix.
- `0e5025fec7defd11a18aa50609326afef0a2631b2f0` — CI branch cleanup.
- `9fbddf1fced12939b57cf0b00c2f85f4328bb7b4` — transactional admin Premium revoke.
- `dbb6ecfbda90a0d1a18c04fd4b0c3319a9905813` — regression test for revoke transaction.

## 5. CI status

- ✅ CI run #120 для commit `2f570a6b54fdd2f405e3356635e0f4fcebd92c52` — success.
- ✅ CI run #121 для commit `6ec27f28be9acda10fb282045028928ec7e20ca0` — success.
- ⏳ После транзакционного fix запускались runs #124/#125; исторически run #125 ещё выполнял Regression tests на момент последней проверки.
- ⬜ Перед финальным deployment подтвердить, что самый свежий CI run завершён с `success`.

## 6. Что ещё проверить перед сервером

### Code / runtime

- ⬜ Подтвердить актуальный green CI.
- ⬜ Проверить фактический runtime main menu и порядок middleware/routers (`wm_wizard`, `opp_admin`, `admin_premium`).
- ⬜ Проверить admin Premium сценарии:
  - paid Premium → admin grant → revoke → paid access preserved;
  - grant expiry does not prolong Premium;
  - permanent Premium не ломается;
  - повторная выдача корректно продлевает grant;
  - обычный пользователь не получает admin callback access.

## 7. Сервер: точные пути, имена сервисов и устройство запуска

> **Критически важно для другого ИИ:** на VPS имя systemd-сервиса — `media-hunter.service` (с дефисом), а не `mediahunter.service`. Все команды ниже должны использовать именно `media-hunter`.

### 7.1 Основные пути VPS

- Корень приложения: `/opt/mediahunter/app`
- Главный запуск бота: `/opt/mediahunter/app/main.py`
- Виртуальное окружение Python: `/opt/mediahunter/venv`
- Python production: `/opt/mediahunter/venv/bin/python`
- yt-dlp находится в: `/opt/mediahunter/venv/bin/yt-dlp`
- Конфигурация окружения: `/opt/mediahunter/app/.env`
- Данные приложения: `/opt/mediahunter/app/data`
- Медиа приложения: `/opt/mediahunter/app/media`
- Дополнительные рабочие данные: `/opt/mediahunter/data`
- Дополнительный рабочий каталог: `/opt/mediahunter/work`
- Systemd unit-файл: `/etc/systemd/system/media-hunter.service`
- Локальный Telegram Bot API: `127.0.0.1:8081`
- Local Bot API systemd unit: `/etc/systemd/system/telegram-bot-api.service`
- Local Bot API data/work directory: `/var/lib/telegram-bot-api`
- Local Bot API temp directory: `/var/lib/telegram-bot-api/temp`
- Local Bot API binary: `/usr/local/bin/telegram-bot-api`
- Local Bot API environment file: `/root/telegram-bot-api.env`

### 7.2 Пользователь и systemd

Бот и Local Bot API запускаются от отдельного системного пользователя:
- `User=mediahunter`
- `Group=mediahunter`
- shell пользователя — `nologin`

### 7.3 Точные systemd units

#### Media Hunter

Unit: `/etc/systemd/system/media-hunter.service`

```ini
[Unit]
Description=Media Hunter Telegram Bot
After=network-online.target telegram-bot-api.service
Wants=network-online.target

[Service]
Type=simple

User=mediahunter
Group=mediahunter

WorkingDirectory=/opt/mediahunter/app
EnvironmentFile=/opt/mediahunter/app/.env
Environment="PATH=/opt/mediahunter/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/mediahunter/venv/bin/python /opt/mediahunter/app/main.py

Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictRealtime=true
MemoryDenyWriteExecute=true

CapabilityBoundingSet=
AmbientCapabilities=

ReadWritePaths=/opt/mediahunter/app/data
ReadWritePaths=/opt/mediahunter/app/media
ReadWritePaths=/opt/mediahunter/data
ReadWritePaths=/opt/mediahunter/work

[Install]
WantedBy=multi-user.target
```

#### Telegram Local Bot API

Unit: `/etc/systemd/system/telegram-bot-api.service`

```ini
[Unit]
Description=Telegram Local Bot API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mediahunter
Group=mediahunter
EnvironmentFile=/root/telegram-bot-api.env
ExecStart=/usr/local/bin/telegram-bot-api \
    --api-id=${TELEGRAM_API_ID} \
    --api-hash=${TELEGRAM_API_HASH} \
    --local \
    --http-port=8081 \
    --http-ip-address=127.0.0.1 \
    --dir=/var/lib/telegram-bot-api \
    --temp-dir=/var/lib/telegram-bot-api/temp \
    --log=/var/lib/telegram-bot-api/bot-api.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7.4 Как связаны сервисы

Порядок работы production:

`telegram-bot-api.service` → слушает `127.0.0.1:8081` → `media-hunter.service` использует этот Local Bot API для общения с Telegram.

`media-hunter.service` имеет `After=telegram-bot-api.service`, поэтому systemd знает порядок запуска, но сам `After=` не означает, что зависимый сервис гарантированно останется живым.

Media Hunter подключается к Local Bot API через aiogram. При недоступном порте `8081` вызов `bot.get_me()` завершается `TelegramNetworkError`, после чего процесс бота завершается. При `Restart=always` systemd запускает его снова.

### 7.5 Systemd hardening Media Hunter

Unit Media Hunter включает sandbox/hardening:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `ProtectKernelTunables=true`
- `ProtectKernelModules=true`
- `ProtectKernelLogs=true`
- `ProtectControlGroups=true`
- `RestrictSUIDSGID=true`
- `LockPersonality=true`
- `RestrictRealtime=true`
- `MemoryDenyWriteExecute=true`
- пустые `CapabilityBoundingSet=` и `AmbientCapabilities=`

Запись разрешена только в явно перечисленные директории через `ReadWritePaths`.

### 7.6 Правильные команды управления сервисами

Media Hunter:
```bash
systemctl status media-hunter --no-pager
systemctl restart media-hunter
systemctl stop media-hunter
systemctl start media-hunter
systemctl enable media-hunter
systemctl disable media-hunter
journalctl -u media-hunter -n 100 --no-pager
```

Local Bot API:
```bash
systemctl status telegram-bot-api --no-pager
systemctl restart telegram-bot-api
systemctl stop telegram-bot-api
systemctl start telegram-bot-api
systemctl enable telegram-bot-api
systemctl disable telegram-bot-api
journalctl -u telegram-bot-api -n 100 --no-pager
```

**Не использовать:** `systemctl status mediahunter` — такого unit нет. Правильное имя Media Hunter: `media-hunter`.

### 7.7 Firewall / сеть

Текущая модель firewall:
- UFW используется.
- Входящие соединения: default **deny**.
- SSH порт 22 разрешён.
- Исходящий трафик: **allow**.

Следствие: firewall защищает вход на VPS, но сейчас не является полноценной process-specific egress изоляцией для `mediahunter`. Это важно именно из-за остаточного SSRF-рискa: `yt-dlp` запускается отдельным subprocess и сам выполняет сетевые соединения.

### 7.8 Bot API

Локальный Telegram Bot API работает на:

```text
127.0.0.1:8081
```

Он не должен рассматриваться как публичный endpoint для интернета.

### 7.9 История серверного сбоя 2026-09-02

Сразу после обновления зависимостей Media Hunter не запускался из-за недоступного `127.0.0.1:8081`.

Диагностика показала первопричину в `telegram-bot-api.service`:

```text
Can't create files in the directory "/var/lib/telegram-bot-api/".
Use --dir option to specify a writable working directory
```

Причина: Local Bot API работал от `mediahunter:mediahunter`, но `/var/lib/telegram-bot-api` принадлежал `root:mediahunter` с правами `755`, поэтому пользователь `mediahunter` не мог создавать/изменять файлы.

Исправление:

```bash
chown -R mediahunter:mediahunter /var/lib/telegram-bot-api
```

После этого подтверждено:
- `/var/lib/telegram-bot-api` → `mediahunter:mediahunter`
- `/var/lib/telegram-bot-api/temp` → `mediahunter:mediahunter`
- `telegram-bot-api.service` → `active (running)`
- Local Bot API слушает `127.0.0.1:8081`
- `curl http://127.0.0.1:8081/` получает HTTP `404 Not Found`, что подтверждает, что порт доступен и HTTP-сервер отвечает.

### 7.10 Текущий фактический production status после исправления

На 2026-09-02 подтверждено:
- ✅ `telegram-bot-api.service` запущен.
- ✅ `127.0.0.1:8081` слушается Local Bot API.
- ✅ `media-hunter.service` запущен.
- ✅ Media Hunter перешёл в polling.
- ✅ В логах появился `Start polling`.
- ✅ Бот успешно определён как `@vidos_hunter_bot` и получил bot id `8633448892`.
- ✅ После запуска Media Hunter обработал Telegram updates с id `156522900`–`156522903`.
- ✅ Ошибка `Cannot connect to host 127.0.0.1:8081` после успешного запуска больше не является текущей ошибкой.

Предыдущий огромный `restart counter` относится к историческому периоду, когда Local Bot API был сломан из-за прав каталога. После исправления этот факт не считать текущим падением приложения.

Проверенный рабочий путь:

`systemd → telegram-bot-api.service → 127.0.0.1:8081 → media-hunter.service → aiogram polling → Telegram updates`

### 7.11 Важное замечание по секретам

В ходе диагностики в консольном выводе был показан bot token. Этот секрет больше не цитировать и не записывать в `DEVELOPMENT_LOG.md`.

Требование безопасности: перевыпустить bot token через BotFather и обновить production-конфигурацию, если токен действительно был раскрыт вне доверенной среды. Новый токен не записывать в журнал.

### 7.12 Рекомендуемый порядок обновления production

1. Проверить серверное состояние и git:
```bash
cd /opt/mediahunter/app
git remote -v
git branch --show-current
git status
git log -1 --oneline
```

2. Перед изменением сделать backup:
```bash
sudo cp -a /opt/mediahunter/app /opt/mediahunter/app_backup_$(date +%Y%m%d_%H%M%S)
```

3. Проверить SSH remote (предпочтительно):
```text
git@github.com:anons23/media_hunter_bot.git
```

4. Синхронизировать нужную ветку:
```bash
cd /opt/mediahunter/app
git fetch origin
git checkout Media_hanter-v3-security
git reset --hard origin/Media_hanter-v3-security
```

5. Установить production-зависимости:
```bash
/opt/mediahunter/venv/bin/python -m pip install -r media_hunter_bot/requirements.txt
```

6. Проверить компиляцию:
```bash
/opt/mediahunter/venv/bin/python -m py_compile media_hunter_bot/processor.py media_hunter_bot/handlers.py media_hunter_bot/db.py media_hunter_bot/config.py main.py
```

7. Перед запуском проверить Local Bot API:
```bash
systemctl status telegram-bot-api -l --no-pager
ss -lntp | grep ':8081'
```

8. Запустить/перезапустить Media Hunter:
```bash
systemctl restart media-hunter
systemctl status media-hunter -l --no-pager
```

9. Сразу смотреть логи:
```bash
journalctl -u media-hunter -n 200 --no-pager -o cat
```

10. Только после успешного старта делать runtime smoke tests.

### 7.13 Smoke tests после deployment

- ⬜ `/start` и главное меню.
- ⬜ Скачать видео по ссылке.
- ⬜ Загрузить собственное видео.
- ⬜ Watermark: текст и логотип.
- ⬜ Проверить название исходного видео в результате/описании.
- ⬜ Premium обычного пользователя.
- ⬜ Admin Premium: выдать → проверить → отозвать.
- ⬜ ОПП / приватная invite-ссылка.
- ⬜ Автопостинг в подключённый канал.

## 8. Остаточный security-риск

- ⬜ Рассмотреть process-specific egress filtering для `mediahunter`.

Приложение само блокирует известные private/loopback назначения, но DNS rebinding и redirect-to-internal остаются остаточным риском, поскольку конечное сетевое соединение выполняет `yt-dlp` в subprocess. Production security требует unprivileged user + сетевую изоляцию/egress rules.

UFW с разрешённым outgoing-трафиком этот риск полностью не устраняет: он контролирует firewall-правила VPS, но не ограничивает конкретно только процесс `mediahunter`.

## 9. Последняя точка продолжения для другого ИИ

**Рабочая ветка:** `Media_hanter-v3-security`.

**Главная задача сейчас:**
1. Проверить свежий green CI.
2. Считать цепочку `telegram-bot-api.service → 127.0.0.1:8081 → media-hunter.service` рабочей на основании успешного polling.
3. Выполнить реальные smoke tests бота.
4. Отдельно решить вопрос перевыпуска bot token из-за раскрытия секрета.
5. После smoke tests оценить финальную готовность к production.

`DEVELOPMENT_LOG.md` на сервер не копировать.

При каждом успешном важном изменении обновлять этот файл: кратко что сделано → commit → статус `✅`. Для планов использовать `⬜` до фактической проверки.
