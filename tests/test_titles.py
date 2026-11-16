import unittest
from pathlib import Path
from types import SimpleNamespace

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import handlers
from media_hunter_bot.about import ABOUT_TEXT
from media_hunter_bot.processor import clean_title, pick_title, safe_media_filename


class PickTitleTests(unittest.TestCase):
    def test_real_title_is_kept(self):
        self.assertEqual(pick_title({"id": "abc", "title": "Как приготовить борщ"}), "Как приготовить борщ")

    def test_instagram_placeholder_uses_caption(self):
        data = {"id": "C1x", "title": "Video by some.account", "uploader": "some.account",
                "description": "Закат на море 🌅 #travel #sea\nвторая строка https://t.me/x"}
        self.assertEqual(pick_title(data), "Закат на море 🌅")

    def test_tiktok_caption_title_loses_tags_and_links(self):
        data = {"id": "7300", "title": "Смешной кот #cat #fyp @user https://vm.tiktok.com/x"}
        self.assertEqual(pick_title(data), "Смешной кот")

    def test_hashtags_only_falls_back_to_author_and_id(self):
        data = {"id": "7300", "title": "#fyp #viral", "description": "#fyp", "uploader": "catlover"}
        self.assertEqual(pick_title(data), "catlover 7300")

    def test_generic_placeholders(self):
        for title in ("TikTok video #7300123", "Video", "Instagram post", "untitled", "7300123"):
            data = {"id": "7300123", "title": title, "extractor_key": "TikTok"}
            self.assertEqual(pick_title(data), "TikTok 7300123", title)

    def test_clean_title_skips_empty_lines(self):
        self.assertEqual(clean_title("#a #b\n\n  Настоящий текст  "), "Настоящий текст")


class FilenameTests(unittest.TestCase):
    def test_long_name_is_cut_at_word_boundary(self):
        name = safe_media_filename("слово " * 30, ".mp4")
        self.assertTrue(name.endswith("слово.mp4"))
        self.assertLessEqual(len(name), 84)

    def test_upload_keeps_original_name(self):
        self.assertEqual(handlers.upload_title(Path("/x/Мой ролик.mp4")), "Мой ролик")
        self.assertEqual(handlers.upload_title(Path("/x/upload.mp4")), "video")

    def test_upload_file_name_from_message(self):
        m = SimpleNamespace(video=SimpleNamespace(file_name="clip.MOV"), document=None)
        self.assertEqual(handlers._upload_file_name(m), "clip.MOV")
        m = SimpleNamespace(video=SimpleNamespace(file_name=None), document=None)
        self.assertEqual(handlers._upload_file_name(m), "")


class AboutSitesTests(unittest.TestCase):
    def test_lists_popular_sites_and_public_only(self):
        for expected in ("TikTok", "Instagram", "VK", "Rutube", "общедоступные", "Закрытые профили"):
            self.assertIn(expected, ABOUT_TEXT)


if __name__ == "__main__":
    unittest.main()
