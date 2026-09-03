"""Simple user-facing list of the bot's main features."""
from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup


ABOUT_TEXT = (
    "🤖 <b>Media Hunter — возможности</b>\n\n"
    "📥 <b>Скачать</b>\n"
    "• YouTube, TikTok и Instagram по ссылке\n"
    "• YouTube-плейлисты — по одному видео\n"
    "• Можно отправить своё видео\n\n"
    "💧 <b>Водяной знак</b>\n"
    "• Текст или PNG-логотип\n"
    "• Размер, позиция, цвет и прозрачность\n"
    "• Настройки можно изменить или удалить\n\n"
    "🔄 <b>Автопостинг</b>\n"
    "• Free — 1 канал\n"
    "• Premium — до 3 каналов\n"
    "• Для каждого канала можно настроить свой водяной знак\n\n"
    "🛡 <b>Уникализация</b>\n"
    "• Обычные видео до 100 МБ\n"
    "• Видео из плейлиста — до 80 МБ на видео\n\n"
    "🆓 <b>Free</b>\n"
    "• До 10 задач в очереди\n"
    "• До 20 видео из одного плейлиста\n"
    "• До 3 запросов плейлистов в календарный месяц\n\n"
    "⭐ <b>Premium</b>\n"
    "• Приоритет в очереди\n"
    "• До 40 видео из одного плейлиста\n"
    "• Без месячного лимита на плейлисты\n"
    "• Плейлист обрабатывается по одному видео, не блокируя очередь других пользователей\n\n"
    "🎬 <b>Формат</b> — видео или MP3\n\n"
    "💡 Нажмите «📥 Скачать» и отправьте ссылку.\n"
    "Для своего файла — «📤 Моё видео»."
)


def register_about(router, menu_fn):
    """Add the capabilities button to the end of the main menu."""
    original_menu = menu_fn

    def patched_menu(uid: int) -> InlineKeyboardMarkup:
        original = original_menu(uid)
        rows = [list(row) for row in original.inline_keyboard]
        rows.append([InlineKeyboardButton(text="🤖 Возможности", callback_data="about")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def about(c: CallbackQuery):
        await c.answer()
        await c.message.edit_text(
            ABOUT_TEXT,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]]
            ),
            parse_mode="HTML",
        )

    router.callback_query.register(about, F.data == "about")
    return patched_menu
