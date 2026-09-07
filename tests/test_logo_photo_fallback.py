import unittest

from aiogram import Router

from media_hunter_bot import logo_photo_fallback


class TestLogoPhotoFallback(unittest.TestCase):
    def test_registers_gallery_photo_fallback(self):
        router = Router()
        logo_photo_fallback.patch_router(router)
        handlers = getattr(router.message, "handlers", [])
        names = {getattr(h.callback, "__name__", "") for h in handlers}
        self.assertIn("_logo_photo_fallback", names)

    def test_patch_is_idempotent(self):
        router = Router()
        logo_photo_fallback.patch_router(router)
        first = len(getattr(router.message, "handlers", []))
        logo_photo_fallback.patch_router(router)
        second = len(getattr(router.message, "handlers", []))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
