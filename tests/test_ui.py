import inspect
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
        self.assertIn("📥 Скачать", labels)
        self.assertIn("📤 Моё видео", labels)
        self.assertIn("📺 Каналы", labels)
        self.assertIn("⭐ Premium", labels)
        self.assertIn("🔄 Рестарт моих задач", labels)
        self.assertNotIn("💧 Водяной знак", labels)
        self.assertNotIn("⚙️ Настройки", labels)
        self.assertNotIn("Admin", labels)

    def test_main_menu_navigation_does_not_send_stale_info_messages(self):
        source = inspect.getsource(wm_wizard._MainMenuInfoMiddleware)
        self.assertNotIn("_MAIN_MENU_INFO", source)
        self.assertNotIn("answer(info", source)

    def test_channel_watermark_middleware_does_not_overwrite_screen(self):
        source = inspect.getsource(wm_wizard._MainMenuInfoMiddleware.__call__)
        self.assertNotIn('startswith("cwmx:")', source)
        self.assertNotIn('startswith("ch:")', source)

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
