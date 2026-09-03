import unittest

from aiogram import Router

from media_hunter_bot import logo_upload_fix


class TestLogoRouterRegistration(unittest.TestCase):
    def test_photo_handler_is_registered_on_router(self):
        router = Router()
        logo_upload_fix.patch_router(router)
        handlers = getattr(router.message, "handlers", [])
        self.assertTrue(any("_logo_photo_message" in getattr(h.callback, "__name__", "") for h in handlers))


if __name__ == "__main__":
    unittest.main()
