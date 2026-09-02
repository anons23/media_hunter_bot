"""Interactive Russian watermark setup via inline buttons."""
from __future__ import annotations

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db
from .processor import _is_valid_color

# Internal codes stay English for FFmpeg/callbacks; UI is Russian.
COLORS = [
    ("white", "⬜ Белый"),
    ("black", "⬛ Чёрный"),
    ("red", "🔴 Красный"),
    ("yellow", "🟡 Жёлтый"),
    ("orange", "🟠 Оранжевый"),
    ("green", "🟢 Зелёный"),
    ("blue", "🔵 Синий"),
    ("cyan", "🩵 Голубой"),
    ("pink", "🩷 Розовый"),
    ("purple", "🟣 Фиолетовый"),
    ("gold", "🥇 Золотой"),
    ("silver", "⚪ Серебристый"),
]

SIZES = [
    (18, "Мелкий"),
    (28, "Обычный"),
    (40, "Крупный"),
    (56, "Очень крупный"),
    (72, "Огромный"),
]

POSITIONS = [
    ("tl", "↖ Верх слева"),
    ("tr", "↗ Верх справа"),
    ("c", "⏺ По центру"),
    ("bl", "↙ Низ слева"),
    ("br", "↘ Низ справа"),
]

OPACITIES = [
    (0.4, "Слабый (40%)"),
    (0.6, "Средний (60%)"),
    (0.8, "Заметный (80%)"),
    (1.0, "Яркий (100%)"),
]

# font style key -> label (processor maps key to file)
FONTS = [
    ("sans", "Обычный"),
    ("bold", "Жирный"),
    ("serif", "С засечками"),
    ("mono", "Моноширинный"),
]

POS_RU = dict(POSITIONS)
COLOR_RU = dict(COLORS)
FONT_RU = dict(FONTS)


_MAIN_MENU_TEXT = {
    "upload": "📤 Загрузить видео",
    "premium": "⭐ Премиум",
    "restart": "🔄 Отменить мои задачи",
    "admin": "👑 Админка",
}

_MAIN_MENU_INFO = {
    "download": "📥 <b>Скачать</b>\n\nПришлите ссылку на видео из YouTube, TikTok или Instagram. Бот скачает его, обработает и отправит вам готовый файл.",
    "upload": "📤 <b>Загрузить видео</b>\n\nЗдесь можно отправить боту уже имеющийся видеофайл. Он обработает его так же, как видео по ссылке.",
    "channels": "📺 <b>Каналы</b>\n\nПодключайте свои Telegram-каналы для автоматической публикации обработанных видео. Для каждого канала можно отдельно настроить автопост и водяной знак.",
    "wm": "💧 <b>Водяной знак</b>\n\nНастройте текстовую надпись или логотип: текст, цвет, шрифт, размер, положение и прозрачность. Настройка применяется к новым обработанным видео.",
    "settings": "⚙️ <b>Настройки</b>\n\nВыберите, что получать после обработки: обычное видео или только аудио в формате MP3.",
    "premium": "⭐ <b>Премиум</b>\n\nЗдесь можно купить Premium на выбранный срок. Премиум-задачи получают приоритет в очереди.",
    "restart": "🔄 <b>Отменить мои задачи</b>\n\nОтменяются только ваши текущие и ожидающие задачи. Задачи других пользователей не затрагиваются.",
    "admin": "👑 <b>Админка</b>\n\nРаздел управления ботом: ОПП, отчёты, реклама, Stars и служебные настройки.",
}


class _MainMenuInfoMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        info = _MAIN_MENU_INFO.get(event.data or "")
        if info and event.message:
            try:
                await event.message.answer(info, parse_mode="HTML")
            except Exception:
                pass
        result = await handler(event, data)
        if event.message and event.data == "wm":
            try:
                await event.message.edit_reply_markup(
                    reply_markup=_kb(
                        [
                            [_B("📝 Текст", "wmtext")],
                            [_B("🖼 Логотип", "wmlogo")],
                            [_B("◀️ Назад", "back")],
                        ]
                    )
                )
            except Exception:
                pass
        elif event.message and (event.data or "").startswith("cwm:"):
            try:
                cid = (event.data or "").split(":", 1)[1]
                await event.message.edit_reply_markup(
                    reply_markup=_kb(
                        [
                            [_B("🔄 Автопост", f"toggle:{cid}"), _B("💧 Водяной знак", f"cwm:{cid}")],
                            [_B("🗑 Удалить", f"del:{cid}")],
                            [_B("◀️ Назад", "channels")],
                        ]
                    )
                )
            except Exception:
                pass
        return result


class WmStates(StatesGroup):
    text = State()


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _B(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def _chunk(items: list, n: int) -> list[list]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def _friendly_menu(menu_fn, uid: int) -> InlineKeyboardMarkup:
    """Return the existing main menu with only visible English labels translated."""
    original = menu_fn(uid)
    rows: list[list[InlineKeyboardButton]] = []
    for row in original.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            label = _MAIN_MENU_TEXT.get(button.callback_data, button.text)
            new_row.append(InlineKeyboardButton(text=label, callback_data=button.callback_data, url=button.url))
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _summary(data: dict) -> str:
    text = data.get("wm_text") or "—"
    color = data.get("wm_color", "white")
    size = data.get("wm_size", 28)
    pos = data.get("wm_position", "br")
    opacity = data.get("wm_opacity", 0.8)
    font = data.get("wm_font", "sans")
    size_label = next((lab for s, lab in SIZES if s == size), str(size))
    return (
        "💧 <b>Ваш водяной знак</b>\n\n"
        f"📝 Текст: <code>{text}</code>\n"
        f"🎨 Цвет: {COLOR_RU.get(color, color)}\n"
        f"🔤 Шрифт: {FONT_RU.get(font, font)}\n"
        f"📏 Размер: {size_label} ({size})\n"
        f"📍 Позиция: {POS_RU.get(pos, pos)}\n"
        f"👁 Прозрачность: {int(float(opacity) * 100)}%\n\n"
        "Так надпись будет накладываться на видео."
    )


async def _save_watermark(uid: int, data: dict) -> None:
    w = {
        "type": "text",
        "text": str(data.get("wm_text", ""))[:200],
        "position": data.get("wm_position", "br"),
        "size": int(data.get("wm_size", 28)),
        "color": data.get("wm_color", "white"),
        "opacity": float(data.get("wm_opacity", 0.8)),
        "font": data.get("wm_font", "sans"),
    }
    if not _is_valid_color(w["color"]):
        w["color"] = "white"
    if w["position"] not in {"tl", "tr", "bl", "br", "c"}:
        w["position"] = "br"
    if not 10 <= w["size"] <= 200:
        w["size"] = 28
    if not 0.05 <= w["opacity"] <= 1.0:
        w["opacity"] = 0.8

    cid = data.get("channel")
    if cid:
        row = next((x for x in await db.alist_channels(uid) if x["channel_id"] == cid), None)
        if not row:
            raise ValueError("Канал больше не подключён.")
        await db.aset_channel_watermark(cid, uid, w)
    else:
        await db.aset_user_watermark(uid, w)


def register_wm_wizard(router: Router, menu_fn) -> None:
    """Register interactive watermark text wizard and friendly main-menu UI."""
    base_menu_fn = menu_fn
    router.callback_query.middleware(_MainMenuInfoMiddleware())

    def friendly_main_menu(uid: int) -> InlineKeyboardMarkup:
        return _friendly_menu(base_menu_fn, uid)

    # handlers.py calls its global menu() directly. Replace that function at
    # registration time so /start and all normal returns use the same labels.
    try:
        from . import handlers as handlers_module
        handlers_module.menu = friendly_main_menu
    except Exception:
        pass

    @router.callback_query(F.data.in_({"wmtext", "cwmtext"}))
    async def wm_start_text(c: CallbackQuery, state: FSMContext):
        cid = None if c.data == "wmtext" else (await state.get_data()).get("cid")
        if cid is not None:
            row = next(
                (x for x in await db.alist_channels(c.from_user.id) if x["channel_id"] == cid),
                None,
            )
            if not row:
                await c.answer("Канал не найден", show_alert=True)
                return
        await state.set_state(WmStates.text)
        await state.update_data(
            channel=cid,
            wm_text=None,
            wm_color="white",
            wm_size=28,
            wm_position="br",
            wm_opacity=0.8,
            wm_font="sans",
        )
        await c.answer()
        back = "wm" if cid is None else "channels"
        await c.message.edit_text(
            "📝 Введите текст водяного знака одним сообщением.\n"
            "Например: <code>Мой канал</code>",
            reply_markup=_kb([[_B("◀️ Назад", back)]]),
            parse_mode="HTML",
        )

    @router.message(WmStates.text)
    async def wm_got_text(m: Message, state: FSMContext):
        if not m.text or not m.text.strip():
            await m.answer("❌ Пришлите обычный текст (не файл).")
            return
        text = m.text.strip()[:200]
        await state.update_data(wm_text=text)
        await state.set_state(None)
        rows = [
            [_B(lab, f"wmcolor:{code}") for code, lab in pair]
            for pair in _chunk(COLORS, 2)
        ]
        rows.append([_B("❌ Отмена", "wm_cancel")])
        await m.answer(
            f"Текст: <b>{text}</b>\n\n🎨 Выберите цвет:",
            reply_markup=_kb(rows),
            parse_mode="HTML",
        )

    @router.callback_query(F.data.startswith("wmcolor:"))
    async def wm_color(c: CallbackQuery, state: FSMContext):
        color = c.data.split(":", 1)[1]
        if color not in COLOR_RU:
            await c.answer("Некорректный цвет", show_alert=True)
            return
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Сначала введите текст", show_alert=True)
            return
        await state.update_data(wm_color=color)
        rows = [[_B(lab, f"wmfont:{code}")] for code, lab in FONTS]
        rows.append([_B("❌ Отмена", "wm_cancel")])
        await c.answer()
        await c.message.edit_text(
            f"Цвет: {COLOR_RU[color]}\n\n🔤 Выберите стиль шрифта:",
            reply_markup=_kb(rows),
        )

    @router.callback_query(F.data.startswith("wmfont:"))
    async def wm_font(c: CallbackQuery, state: FSMContext):
        font = c.data.split(":", 1)[1]
        if font not in FONT_RU:
            await c.answer("Некорректный шрифт", show_alert=True)
            return
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Сначала введите текст", show_alert=True)
            return
        await state.update_data(wm_font=font)
        rows = [[_B(f"{lab} ({sz})", f"wmsize:{sz}")] for sz, lab in SIZES]
        rows.append([_B("❌ Отмена", "wm_cancel")])
        await c.answer()
        await c.message.edit_text(
            f"Шрифт: {FONT_RU[font]}\n\n📏 Выберите размер:",
            reply_markup=_kb(rows),
        )

    @router.callback_query(F.data.startswith("wmsize:"))
    async def wm_size(c: CallbackQuery, state: FSMContext):
        try:
            size = int(c.data.split(":", 1)[1])
        except ValueError:
            await c.answer("Некорректный размер", show_alert=True)
            return
        if size not in {s for s, _ in SIZES}:
            await c.answer("Некорректный размер", show_alert=True)
            return
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Сначала введите текст", show_alert=True)
            return
        await state.update_data(wm_size=size)
        rows = [[_B(lab, f"wmpos:{code}")] for code, lab in POSITIONS]
        rows.append([_B("❌ Отмена", "wm_cancel")])
        await c.answer()
        lab = next(l for s, l in SIZES if s == size)
        await c.message.edit_text(
            f"Размер: {lab}\n\n📍 Где показать надпись на видео?",
            reply_markup=_kb(rows),
        )

    @router.callback_query(F.data.startswith("wmpos:"))
    async def wm_pos(c: CallbackQuery, state: FSMContext):
        pos = c.data.split(":", 1)[1]
        if pos not in POS_RU:
            await c.answer("Некорректная позиция", show_alert=True)
            return
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Сначала введите текст", show_alert=True)
            return
        await state.update_data(wm_position=pos)
        rows = [[_B(lab, f"wmop:{op}")] for op, lab in OPACITIES]
        rows.append([_B("❌ Отмена", "wm_cancel")])
        await c.answer()
        await c.message.edit_text(
            f"Позиция: {POS_RU[pos]}\n\n👁 Насколько яркой сделать надпись?",
            reply_markup=_kb(rows),
        )

    @router.callback_query(F.data.startswith("wmop:"))
    async def wm_opacity(c: CallbackQuery, state: FSMContext):
        try:
            opacity = float(c.data.split(":", 1)[1])
        except ValueError:
            await c.answer("Некорректное значение", show_alert=True)
            return
        if opacity not in {o for o, _ in OPACITIES}:
            await c.answer("Некорректное значение", show_alert=True)
            return
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Сначала введите текст", show_alert=True)
            return
        await state.update_data(wm_opacity=opacity)
        data = await state.get_data()
        rows = [
            [_B("✅ Сохранить", "wm_save"), _B("❌ Отмена", "wm_cancel")],
        ]
        await c.answer()
        await c.message.edit_text(
            _summary(data),
            reply_markup=_kb(rows),
            parse_mode="HTML",
        )

    @router.callback_query(F.data == "wm_save")
    async def wm_save(c: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if not data.get("wm_text"):
            await c.answer("Нет текста для сохранения", show_alert=True)
            return
        try:
            await _save_watermark(c.from_user.id, data)
        except ValueError as e:
            await c.answer(str(e), show_alert=True)
            await state.clear()
            return
        await state.clear()
        await c.answer("Сохранено")
        await c.message.edit_text(
            "✅ Водяной знак сохранён.\nОн будет на новых обработанных видео.",
            reply_markup=menu_fn(c.from_user.id),
        )

    @router.callback_query(F.data == "wm_cancel")
    async def wm_cancel(c: CallbackQuery, state: FSMContext):
        await state.clear()
        await c.answer("Отменено")
        await c.message.edit_text(
            "Настройка водяного знака отменена.",
            reply_markup=menu_fn(c.from_user.id),
        )
