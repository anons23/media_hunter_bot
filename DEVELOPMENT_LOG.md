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
- `0e5025fec7defd11aa50609326afef0a2631b2f0` — CI branch cleanup.
- `9fbddf1fced12939b57cf0b00c2f85f4328bb7b4` — transactional admin Premium revoke.
- `dbb6ecfbda90a0d1a18c04fd4b0c3319a9905813` — regression test for revoke transaction.

## 5. CI status

- ✅ CI run #120 для commit `2f570a6b54fdd2f405e3356635e0f4fcebd92c52` — success.
- ✅ CI run #121 для commit `6ec27f28be9acda10fb282045028928ec7e20ca0` — success.
- ⏳ После транзакционного fix запущены новые runs #124/#125; при последней проверке run #125 ещё выполнял Regression tests.
- ⬜ Перед deployment подтвердить, что самый свежий CI run завершён с `success`.

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

## 7. Серверный deployment plan

### Git / backup

- ⬜ Проверить `git remote -v` на сервере: желательно SSH remote `git@github.com:anons23/media_hunter_bot.git`.
- ⬜ Проверить `git branch --show-current`, `git status`, `git log -1 --oneline`.
- ⬜ Сделать backup текущего `/opt/mediahunter/app` перед обновлением.
- ⬜ Забрать `origin/Media_hanter-v3-security` и переключить сервер на этот commit.

### Environment / service

- ✅ Бот запускается отдельным пользователем `mediahunter` (`nologin`).
- ✅ Systemd sandbox: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, kernel/capability restrictions и writable paths.
- ✅ Local Bot API: `127.0.0.1:8081`.
- ✅ UFW: incoming default deny, SSH разрешён, outgoing allow.
- ✅ Ранее исправлен PATH сервиса для `/opt/mediahunter/venv/bin`, где находится `yt-dlp`.
- ⬜ После deployment проверить `systemctl status mediahunter`.
- ⬜ Проверить `journalctl -u mediahunter -n 100 --no-pager`.
- ⬜ Проверить, что сервис реально запускает актуальный commit и `yt-dlp` доступен.

### Runtime smoke tests после deployment

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

## 9. Последняя точка продолжения для другого ИИ

**Рабочая ветка:** `Media_hanter-v3-security`.

**Последний известный commit до обновления журнала:** `dbb6ecfbda90a0d1a18c04fd4b0c3319a9905813`.

**Главная задача сейчас:** подтвердить green CI после transactional Premium fix, затем синхронизировать этот commit на VPS и провести smoke-test. `DEVELOPMENT_LOG.md` на сервер не копировать.

При каждом успешном важном изменении обновлять этот файл: кратко что сделано → commit → статус `✅`. Для планов использовать `⬜` до фактической проверки.