import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import ux_fixes
from media_hunter_bot.wm_wizard import LogoStates


def _callback(data: str):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )


class TestLogoEntryState(unittest.TestCase):
    def test_logo_button_without_saved_logo_waits_for_upload(self):
        async def run():
            state = AsyncMock()
            state.get_data.return_value = {}
            with patch.object(ux_fixes, "_get_watermark", new=AsyncMock(return_value={})):
                await ux_fixes._show_logo_config(_callback("wmlogo"), state)
            state.set_state.assert_awaited_with(LogoStates.upload)
            kwargs = state.update_data.await_args.kwargs
            self.assertIsNone(kwargs["channel"])
            self.assertIsNone(kwargs["logo_path"])

        asyncio.run(run())

    def test_channel_logo_button_uses_opened_channel(self):
        async def run():
            state = AsyncMock()
            state.get_data.return_value = {"cid": -100500, "channel": -100777}
            with patch.object(ux_fixes, "_get_watermark", new=AsyncMock(return_value={})) as get_wm:
                await ux_fixes._show_logo_config(_callback("cwmlogo"), state)
            get_wm.assert_awaited_with(123, -100500)
            state.set_state.assert_awaited_with(LogoStates.upload)
            self.assertEqual(state.update_data.await_args.kwargs["channel"], -100500)

        asyncio.run(run())

    def test_replace_logo_resets_previous_upload(self):
        async def run():
            state = AsyncMock()
            state.get_data.return_value = {"channel": None, "logo_path": "/old.png"}
            await ux_fixes._start_logo_edit(_callback("wmlogo_edit"), state)
            state.set_state.assert_awaited_with(LogoStates.upload)
            self.assertIsNone(state.update_data.await_args.kwargs["logo_path"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
