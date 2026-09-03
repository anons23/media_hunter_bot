import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from media_hunter_bot import logo_upload_fix


class TestLogoUploadFix(unittest.IsolatedAsyncioTestCase):
    async def test_photo_upload_saves_png_and_enters_settings(self):
        message = MagicMock()
        message.photo = [MagicMock(file_id="photo-file", file_size=1000)]
        message.from_user.id = 123
        message.answer = AsyncMock()

        bot = MagicMock()
        bot.get_file = AsyncMock(return_value=MagicMock(file_path="photos/123.jpg"))

        state = MagicMock()
        state.get_data = AsyncMock(return_value={"logo_size": 20, "logo_position": "br", "logo_opacity": 0.8})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        with tempfile.TemporaryDirectory() as tmp:
            logo_dir = Path(tmp)

            async def fake_download(file_path, destination):
                Path(destination).write_bytes(b"jpeg")

            bot.download_file = AsyncMock(side_effect=fake_download)

            with patch.object(logo_upload_fix, "LOGO_DIR", logo_dir), \
                 patch.object(logo_upload_fix.subprocess, "run") as run, \
                 patch.object(logo_upload_fix, "validate_logo", return_value=(True, "")):
                def fake_run(*args, **kwargs):
                    output = Path(args[0][-1])
                    output.write_bytes(b"png")
                    result = MagicMock()
                    result.returncode = 0
                    return result
                run.side_effect = fake_run

                handled = await logo_upload_fix._handle_photo(message, bot, state)

            self.assertTrue(handled)
            saved = list(logo_dir.glob("*.png"))
            self.assertEqual(len(saved), 1)
            state.set_state.assert_awaited_once_with(logo_upload_fix.LogoStates.settings)
            self.assertTrue(state.update_data.await_count >= 1)
            message.answer.assert_awaited_once()

    async def test_non_photo_is_not_handled(self):
        message = MagicMock()
        message.photo = []
        self.assertFalse(await logo_upload_fix._handle_photo(message, MagicMock(), MagicMock()))


if __name__ == "__main__":
    unittest.main()
