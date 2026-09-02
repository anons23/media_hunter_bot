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
        self.assertIn("📤 Моё видео", labels)
        self.assertIn("⭐ Premium", labels)
        self.assertIn("🔄 Рестарт моих задач", labels)
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
        position_labels = [label for _, label in wm_wizard.POSITIONS]
        logo_size_labels = [label for _, label in wm_wizard.LOGO_SIZES]
        self.assertIn("⬜ Белый", color_labels)
        self.assertIn("Обычный", font_labels)
        self.assertIn("↘ Низ справа", position_labels)
        self.assertIn("Маленький — 20%", logo_size_labels)
        self.assertNotIn("Watermark", color_labels + font_labels + position_labels)

    def test_watermark_help_explains_global_scope(self):
        self.assertIn("личный водяной знак", wm_wizard._MAIN_MENU_INFO["wm"])
        self.assertIn("отдельно", wm_wizard._MAIN_MENU_INFO["wm"])
        self.assertIn("водяной знак", wm_wizard._MAIN_MENU_INFO["channels"])

    def test_upload_help_is_device_video(self):
        self.assertIn("с телефона или компьютера", wm_wizard._MAIN_MENU_INFO["upload"])


if __name__ == "__main__":
    unittest.main()
