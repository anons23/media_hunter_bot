""""What I can do" screen for new Media Hunter users."""
from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup


ABOUT_TEXT = (
    "🤖 <b>Media Hunter — что я умею</b>\n\n"
    "📥 <b>Скачивание</b>\n"
    "• YouTube, TikTok и Instagram по ссылке\n"
    "• YouTube-плейлисты — видео обрабатываются по одному\n"
    "• Можно отправить своё видео прямо в бота\n\n"
    "💧 <b>Обработка видео</b>\n"
    "• Уникализация видео\n"
    "• Текстовый водяной знак\n"
    "• Водяной знак-логотип (PNG)\n"
    "• Настройка размера, позиции и прозрачности водяного знака\n"
    "• Формат: видео или только MP3\n\n"
    "📺 <b>Автопостинг</b>\n"
    "• Подключение до 3 каналов\n"
    "• Можно настроить отдельный водяной знак для канала\n\n"
    "🆓 <b>Бесплатный тариф</b>\n"
    "• До 10 ваших задач в очереди\n"
    "• Плейлист: первые 20 видео за один запрос\n"
    "• Не более 3 playlist-запросов в календарный месяц\n"
    "• Для видео из плейлиста исходный размер — до 80 МБ на видео\n"
    "• Обычные видео до 100 МБ проходят уникализацию\n\n"
    "⭐ <b>Premium</b>\n"
    "• Более высокий приоритет в общей очереди\n"
    "• До 50 видео из одного YouTube-плейлиста\n"
    "• Плейлисты также обрабатываются по одному, чтобы не блокировать весь бот\n"
    "• Удобнее для регулярной и массовой загрузки\n\n"
    "💡 <b>Как начать?</b> Нажмите «📥 Скачать» и отправьте ссылку.\n"
    "Для своего файла используйте «📤 Моё видео»."
)


def register_about(router, menu_fn):
    """Add the about button to the end of the main menu and its screen."""
    original_menu = menu_fn

    def patched_menu(uid: int) -> InlineKeyboardMarkup:
        original = original_menu(uid)
        rows = [list(row) for row in original.inline_keyboard]
        rows.append([InlineKeyboardButton(text="ℹ️ Что я умею", callback_data="about")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def about(c: CallbackQuery):
        await c.answer()
        await c.message.edit_text(
            ABOUT_TEXT,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]]
            ),
        )

    router.callback_query.register(about, F.data == "about")
    return patched_menu
