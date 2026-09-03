import unittest

from aiogram import Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from media_hunter_bot.about import ABOUT_TEXT, register_about


class AboutScreenTests(unittest.TestCase):
    def test_about_button_is_appended(self):
        router = Router()

        def menu(_uid):
            return InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📥 Скачать", callback_data="download")]]
            )

        patched = register_about(router, menu)
        result = patched(123)

        self.assertEqual(result.inline_keyboard[-1][0].text, "ℹ️ Что я умею")
        self.assertEqual(result.inline_keyboard[-1][0].callback_data, "about")
        self.assertEqual(result.inline_keyboard[0][0].callback_data, "download")

    def test_about_text_describes_core_limits_and_features(self):
        for expected in (
            "YouTube-плейлисты",
            "20 видео",
            "3 playlist-запросов",
            "80 МБ",
            "10 ваших задач",
            "50 видео",
            "Premium",
            "Автопостинг",
            "уникализация",
        ):
            self.assertIn(expected, ABOUT_TEXT)


if __name__ == "__main__":
    unittest.main()
