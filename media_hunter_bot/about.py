"""Simple user-facing list of the bot's main features."""
from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .config import MAX_SOURCE_DOWNLOAD_MB, MAX_VIDEO_MINUTES


def _minutes(value: float) -> str:
    return f"{value:g} минут" if value > 0 else "любой длины"


ABOUT_TEXT = (
    "🤖 <b>Media Hunter — возможности</b>\n\n"
    "📥 <b>Скачать по ссылке</b>\n"
    "• YouTube и Shorts, TikTok, Instagram Reels\n"
    "• VK Видео и Клипы, Rutube, Дзен, Одноклассники\n"
    "• X (Twitter), Reddit, Pinterest, Likee, Twitch-клипы, Vimeo, SoundCloud\n"
    "• …и ещё сотни сайтов — просто пришлите ссылку\n"
    "• YouTube-плейлисты — по одному видео\n"
    f"• Видео до {_minutes(MAX_VIDEO_MINUTES)}; если файл больше {MAX_SOURCE_DOWNLOAD_MB} МБ — предложим качество пониже\n"
    "• Можно отправить своё видео\n"
    "🔓 Скачиваем только <b>общедоступные</b> видео. Закрытые профили, приватные "
    "видео и платный контент недоступны.\n\n"
    "💧 <b>Водяной знак</b>\n"
    "• Плашка: картинка или GIF — место, размер, прозрачность и время показа\n"
    "• Надпись: 15 шрифтов, любые цвета, тень, контур или подложка\n"
    "• Всё настраивается в удобном редакторе прямо в Telegram\n\n"
    "🔄 <b>Автопостинг</b>\n"
    "• Free — 1 канал\n"
    "• Premium — до 3 каналов\n"
    "• Для каждого канала можно настроить свой водяной знак\n\n"
    "🛡 <b>Уникализация</b>\n"
    "• Обычные видео до 100 МБ (более крупные отправляем без уникализации)\n"
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
