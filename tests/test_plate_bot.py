import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import db, handlers, webapp, wm_wizard


class PlateBotTests(unittest.TestCase):
    def test_editor_button_when_webapp_configured(self):
        with patch.object(wm_wizard, "WEBAPP_URL", "https://app.example.com"), \
             patch.object(webapp, "WEBAPP_URL", "https://app.example.com"):
            kb = wm_wizard.plate_editor_keyboard(-100123, "channels")
        btn = kb.inline_keyboard[0][0]
        self.assertEqual(btn.web_app.url, "https://app.example.com/?scope=c-100123")

    def test_no_editor_button_without_webapp(self):
        with patch.object(wm_wizard, "WEBAPP_URL", ""):
            kb = wm_wizard.plate_editor_keyboard(None, "wm")
        self.assertEqual(len(kb.inline_keyboard), 1)

    def test_new_upload_replaces_logo_and_keeps_placement(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(db, "DB_PATH", Path(td) / "t.db"), patch.object(db, "ensure_directories", lambda: None):
                db.init_db()
                db.ensure_user(7)
                db.set_user_watermark(7, {"type": "image", "logo": "/old.png", "x": 0.1, "y": 0.2, "w": 0.7,
                                          "logo_opacity": 0.5, "timing": {"mode": "end"}, "fade": False})
                asyncio.run(wm_wizard._store_plate(7, None, Path("/new.gif")))
                saved = db.get_user_watermark(7)
        self.assertEqual(saved["logo"], "/new.gif")
        self.assertEqual((saved["x"], saved["y"], saved["w"]), (0.1, 0.2, 0.7))
        self.assertEqual(saved["timing"]["mode"], "end")

    def test_user_notes(self):
        big = handlers.MAX_UNIQUE_SIZE_MB * 1024 * 1024 + 1
        wm = {"type": "image", "logo": "/x.png", "x": 0, "y": 0, "w": 0.3,
              "timing": {"mode": "custom", "start": 10, "duration": 3}}
        self.assertIn("без плашки", handlers.plate_user_note(wm, {}, big, False))
        self.assertIsNone(handlers.plate_user_note({}, {}, big, False))
        self.assertIn("Видео 6 с", handlers.plate_user_note(wm, {"format": {"duration": "6"}}, 1000, False))
        self.assertIsNone(handlers.plate_user_note(wm, {"format": {"duration": "60"}}, 1000, False))
        self.assertIsNone(handlers.plate_user_note(wm, {}, 1000, True))


if __name__ == "__main__":
    unittest.main()
