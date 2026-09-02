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

## Ранее выполнено

### Security
- ✅ SSRF защита `validate_source_url`: HTTP/HTTPS, запрет credentials/control chars, localhost/metadata/internal suffixes, non-global literal/resolved IP.
- ⚠️ Остаточный риск DNS rebinding/redirect-to-internal; mitigation — unprivileged user + egress isolation.
- ✅ Logo path confinement.
- ✅ Queue/restart race через `asyncio.Lock`.
- ✅ Queue accounting и `task_done()` при restart.
- ✅ Restart завершает subprocess и чистит uploads.
- ✅ Upload проверяет очередь до скачивания.
- ✅ Reboot VPS из бота удалён.
- ✅ Payment activation атомарна; `telegram_charge_id` unique.
- ✅ Referral assignment защищён `AND referred_by IS NULL`.
- ✅ OPP private invite fail-closed.
- ✅ User errors фильтруются через `user_errors.py`.

### Media
- ✅ `download()` использует `--write-info-json`.
- ✅ `safe_media_filename()` и сохранение исходного названия.
- ✅ Text watermark: цвет, шрифт, размер, позиция, прозрачность.
- ✅ Logo watermark: относительный размер, позиция, прозрачность.
- ✅ Source/upload limit 1024 MB.
- ✅ `yt-dlp --max-filesize` и post-download checks.
- ⚠️ FFmpeg ранее логировал только первые 2000 символов stderr; настоящий финальный error line при `code=187` ещё нужно сделать видимым.
- ⚠️ Уникализация — полноценный FFmpeg re-encode и тяжёлая фильтрация; проверить производительность на VPS.

### Dependencies
- ✅ `aiogram==3.31.0`
- ✅ `aiohttp==3.14.3`
- ✅ `python-dotenv==1.1.1`
- ✅ `yt-dlp==2026.8.19`
- ✅ `curl-cffi==0.15.0`
- ✅ TikTok impersonation issue исправлен.

### UI / watermark
- ✅ Русские подписи.
- ✅ «Моё видео» — собственная загрузка.
- ✅ Text watermark wizard: текст → цвет → шрифт → размер → позиция → прозрачность → сохранение.
- ✅ Logo wizard: PNG → размер → позиция → прозрачность → сохранение.
- ✅ Logo size presets: 10/20/30/40/50%.
- ✅ Logo масштабируется с учётом размеров кадра.
- ⚠️ В проекте есть старые/новые участки watermark flow; не плодить новые дубликаты.

## Серверный инцидент 2026-09-02
- ✅ `media-hunter.service` ранее терял `127.0.0.1:8081`.
- ✅ Причина: права `mediahunter` на `/var/lib/telegram-bot-api`.
- ✅ Исправлено владение каталогом и `temp` на `mediahunter:mediahunter`.
- ✅ Local Bot API стал `active/running`, слушает `127.0.0.1:8081`.
- ✅ Media Hunter вернулся в polling и обрабатывал updates.
- 🔐 Bot Token ранее был раскрыт в диагностическом выводе; перед production следует перевыпустить через BotFather. В журнал токен не писать.

## FFmpeg incident 2026-09-02
- FFmpeg 6.1.1 на VPS.
- Для некоторых входов виден `libdav1d 1.4.1`.
- Разные MP4 приводили к `ffmpeg failed (code=187)`.
- После ошибки приложение показывало общий `RuntimeError`.
- По имеющемуся журналу финальная строка FFmpeg не видна из-за обрезки stderr.
- `187` сам по себе не считается доказательством конкретной причины.

## Пользовательские требования 2026-09-02
1. Уникализировать все видео <100 MB; фактически безопаснее считать порог `<=100 MB`.
2. Убрать двойную уникализацию.
3. После перехода из «Каналы»/описаний в другой раздел старое информационное сообщение не должно оставаться отдельным сообщением снизу.

## Изменения текущего сеанса

### UI stale-description
- ✅ `wm_wizard.py` middleware изменён так, чтобы навигация оставалась в текущем сообщении через `edit_text`/`edit_reply_markup`, без отдельного `answer(info...)`.
- ✅ Добавлен regression test, проверяющий отсутствие stale-info отправки.
- ⚠️ Нужен runtime smoke test в Telegram.

### UI tests
- ✅ `tests/test_ui.py` приведён в соответствие с текущими русскими названиями кнопок.
- ✅ Тест stale-description теперь проверяет реальную реализацию middleware, а не удалённый `_MAIN_MENU_INFO`.

### Callback
- ✅ Канальный watermark callback в рабочем `handlers.py`: `cwmx:`.
- ⚠️ Проверять все остальные места на старый `cwm:` перед дальнейшими UI-правками.

### Важная ошибка предыдущей попытки
- ❌ Была сделана неполная массовая замена `handlers.py`, которая вырезала существующую функциональность и вызвала CI ошибки (`MAX_USER_QUEUE`, `metadata`, UI).
- ✅ Эта неполная версия отменена: полный `handlers.py` восстановлен из рабочей точки `6842889`.
- Commit восстановления: `a559a8dc79447a0e65a04009226b9d0123b5bc78`.
- Не считать неполную замену частью production-кода.

### Текущее состояние уникализации
- ✅ После восстановления полного `handlers.py` вернулась логика рабочей точки `6842889`.
- В этой логике для видео до 100 MB выполняется unique processing.
- При включённых каналах обработка строится от исходного файла для channel output, вместо обязательной предварительной обработки пользовательского результата с последующей повторной обработкой того же результата.
- Если разные каналы имеют разные watermark, отдельный FFmpeg output для каждого канала допустим и не считается двойной обработкой одного результата.
- ⬜ Добавить отдельный regression test, который явно фиксирует количество `process_media` вызовов для private-send/channel сценариев.

## CI

Workflow: `.github/workflows/tests.yml`.
- Trigger: push/PR в `Media_hanter-v3-security` + manual dispatch.
- Install dependencies → compile → `unittest discover`.

### CI run 33647655449 / commit 731956c
- ❌ Regression tests.
- Причины: неполная версия `handlers.py` после ошибочной массовой замены:
  - `MAX_USER_QUEUE` missing import.
  - `metadata` ошибочно await-ился.
  - oversized-source test не доходил до проверки send limit.
  - старые UI tests ожидали `_MAIN_MENU_INFO` и старые подписи.

### CI после восстановления
- Run `33648442338` на промежуточном commit журнала: проверки прошли после восстановления/уточнения тестов; не использовать этот run как финальный head.
- Run `33648480341` на commit `a559a8dc79447a0e65a04009226b9d0123b5bc78`: **✅ success**.
- Install dependencies: ✅
- Compile: ✅
- Regression tests: ✅
- Post cleanup: ✅

Финальный green CI подтверждён для полного восстановленного `handlers.py` + текущих UI tests.

## Что осталось сделать
- ⬜ Runtime Telegram smoke test UI: перейти `Каналы` → `Водяной знак` → другие разделы и убедиться, что старое описание не остаётся снизу.
- ⬜ Runtime smoke test логотипа.
- ⬜ Runtime smoke test видео <=100 MB с URL.
- ⬜ Regression test на отсутствие лишнего `process_media` pass.
- ⬜ Проверить все `cwm:`/`cwmx:` references.
- ⬜ Исправить FFmpeg stderr logging: начало + последние строки.
- ⬜ По свежему полному journal определить точную причину `code=187`.
- ⬜ После production deployment проверить systemd journal.

## Production deployment checklist

```bash
cd /opt/mediahunter/app
git remote -v
git branch --show-current
git status
git log -1 --oneline
sudo cp -a /opt/mediahunter/app /opt/mediahunter/app_backup_$(date +%Y%m%d_%H%M%S)
```

```bash
git fetch origin
git checkout Media_hanter-v3-security
git reset --hard origin/Media_hanter-v3-security
```

```bash
/opt/mediahunter/venv/bin/python -m py_compile media_hunter_bot/processor.py media_hunter_bot/handlers.py media_hunter_bot/db.py media_hunter_bot/config.py main.py
```

```bash
systemctl restart telegram-bot-api.service
systemctl status telegram-bot-api.service --no-pager -l
systemctl restart media-hunter.service
systemctl status media-hunter.service --no-pager -l
journalctl -u media-hunter.service -n 100 --no-pager -o cat
```

## Для следующего ИИ
Сначала прочитать этот журнал. Не предполагать, что предыдущий ассистент действительно применил правку: проверять commit/tree/diff и CI. После каждой правки обновлять этот журнал.
