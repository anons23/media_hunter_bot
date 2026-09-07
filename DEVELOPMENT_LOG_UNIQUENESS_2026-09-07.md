# Media Hunter — uniqueness improvement addendum — 2026-09-07

Рабочая ветка: `Media_hanter-v3-security`.

## Основание
Применён план `Plan_Unic`, но адаптирован к текущей рабочей архитектуре. Старый fractional-scale/unsharp/noise профиль не возвращён.

## Изменения
- `media_hunter_bot/unique_filter.py`: добавлена контролируемая случайная вариативность `contrast`, `brightness`, `saturation` в узких пределах.
- Сохранён текущий H.264-safe even-dimension scale: `trunc(iw*0.998/2)*2`.
- Постоянные `noise` и `unsharp`, обязательный crop, `setpts` и `atempo` не добавлялись.
- `media_hunter_bot/optimized_processor.py`: боевой unique path использует новый вариативный фильтр.
- Добавлена дополнительная post-FFmpeg проверка через `ffprobe`: наличие ожидаемого stream, duration > 0 и чётные положительные video dimensions.
- Watermark остаётся отдельным этапом; frozen unique base/multi-channel cache не изменён.
- Лимиты, очередь, SSRF/path/security и правило обязательной uniqueness для видео <=100 MB не изменены.
- Добавлены regression tests на диапазоны вариативности, отсутствие noise/unsharp и ffprobe validation.

## CI
- Первые два промежуточных CI запуска выявили только несовместимость тестового mock и сравнение двух независимых random-вызовов.
- Исправлено без изменения production-логики.
- Финальный CI run `34142810399` — `success`.
- Compile — `success`.
- Regression tests — `success`.

## Production
- ⬜ VPS deploy.
- ⬜ Smoke test обычного видео <=100 MB: uniqueness + качество + watermark.
- ⬜ Smoke test multi-channel: uniqueness выполняется один раз, watermark variants строятся от frozen base.
