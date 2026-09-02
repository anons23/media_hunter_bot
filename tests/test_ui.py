import unittest

from media_hunter_bot import handlers
from media_hunter_bot import wm_wizard


class UiRegressionTests(unittest.TestCase):
    def test_main_menu_uses_russian_labels(self):
        labels = [
            button.text
            for row in handlers.menu(123).inline_keyboard
            for button in row
        ]
        self.assertIn("📤 Загрузить видео", labels)
        self.assertIn("⭐ Премиум", labels)
        self.assertIn("🔄 Отменить мои задачи", labels)
        self.assertNotIn("Premium", labels)
        self.assertNotIn("Admin", labels)

    def test_main_menu_help_covers_all_base_actions(self):
        expected = {
            "download",
            "upload",
            "channels",
            "wm",
            "settings",
            "premium",
            "restart",
            "admin",
        }
        self.assertTrue(expected.issubset(wm_wizard._MAIN_MENU_INFO))
        self.assertNotIn("Premium", wm_wizard._MAIN_MENU_INFO["premium"])

    def test_watermark_labels_are_russian(self):
        color_labels = [label for _, label in wm_wizard.COLORS]
        font_labels = [label for _, label in wm_wizard.FONTS]
        self.assertIn("⬜ Белый", color_labels)
        self.assertIn("Обычный", font_labels)
        self.assertNotIn("Watermark", color_labels + font_labels)


if __name__ == "__main__":
    unittest.main()
