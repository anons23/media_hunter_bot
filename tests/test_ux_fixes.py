import unittest

from media_hunter_bot import ux_fixes


class UxFixTests(unittest.TestCase):
    def test_expected_callback_actions_exist(self):
        source = ux_fixes._UxCallbackMiddleware.__call__.__code__.co_consts
        values = {x for x in source if isinstance(x, str)}
        for expected in ("wmtext", "wmtext_edit", "wmtext_delete", "wmlogo", "wmlogo_edit", "wmlogo_delete"):
            self.assertIn(expected, values)

    def test_router_patch_is_idempotent(self):
        from aiogram import Router

        router = Router()
        ux_fixes.patch_router(router)
        ux_fixes.patch_router(router)
        self.assertTrue(getattr(router, "_media_hunter_ux_patched", False))


if __name__ == "__main__":
    unittest.main()
