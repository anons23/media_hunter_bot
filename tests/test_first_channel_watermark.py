import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import media_hunter_bot as package


class FirstChannelWatermarkTests(unittest.TestCase):
    def test_first_enabled_channel_watermark_is_used(self):
        async def run():
            channels = [
                {"channel_id": -1001, "enabled": 0},
                {"channel_id": -1002, "enabled": 1},
                {"channel_id": -1003, "enabled": 1},
            ]
            channel_wm = {"type": "text", "text": "Мой настоящий канал"}
            with patch.object(package._db, "alist_channels", new=AsyncMock(return_value=channels)), \
                 patch.object(package._db, "aget_channel_watermark", new=AsyncMock(return_value=channel_wm)), \
                 patch.object(package, "_original_get_user_watermark", new=AsyncMock(return_value={"type": "text", "text": "старый"})):
                result = await package._first_channel_watermark(123)
            self.assertEqual(result, channel_wm)

        asyncio.run(run())

    def test_no_enabled_channel_falls_back_to_user_watermark(self):
        async def run():
            user_wm = {"type": "text", "text": "пользовательский"}
            with patch.object(package._db, "alist_channels", new=AsyncMock(return_value=[])), \
                 patch.object(package, "_original_get_user_watermark", new=AsyncMock(return_value=user_wm)):
                result = await package._first_channel_watermark(123)
            self.assertEqual(result, user_wm)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
