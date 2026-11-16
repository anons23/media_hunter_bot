import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from aiohttp.test_utils import AioHTTPTestCase

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import db, processor, webapp

TOKEN = "123456:TEST-TOKEN"


def make_init_data(user_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    pairs = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAE",
        "user": json.dumps({"id": user_id, "first_name": "U"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


class InitDataTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(webapp.verify_init_data(make_init_data(7), TOKEN)["id"], 7)

    def test_wrong_token_or_tampered(self):
        self.assertIsNone(webapp.verify_init_data(make_init_data(7), "other:token"))
        self.assertIsNone(webapp.verify_init_data(make_init_data(7).replace("U", "X"), TOKEN))
        self.assertIsNone(webapp.verify_init_data("", TOKEN))

    def test_expired(self):
        old = make_init_data(7, auth_date=int(time.time()) - 3 * 24 * 3600)
        self.assertIsNone(webapp.verify_init_data(old, TOKEN))


class WebAppApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.logo_dir = root / "logos"
        self.logo_dir.mkdir()
        self.logo = self.logo_dir / "logo_7.png"
        self.logo.write_bytes(b"\x89PNG fake")
        self.patches = [
            patch.object(db, "DB_PATH", root / "t.db"),
            patch.object(db, "ensure_directories", lambda: None),
            patch.object(processor, "LOGO_DIR", self.logo_dir),
            patch.object(webapp, "BOT_TOKEN", TOKEN),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        db.ensure_user(7)
        db.ensure_user(8)
        db.set_user_watermark(7, {"type": "image", "logo": str(self.logo), "position": "br", "logo_size": 20})
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        return webapp.build_app(self.bot)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def h(self, uid):
        return {"X-Telegram-Init-Data": make_init_data(uid)}

    async def test_requires_telegram_auth(self):
        resp = await self.client.get("/api/plate?scope=u")
        self.assertEqual(resp.status, 401)

    async def test_get_and_save_plate(self):
        resp = await self.client.get("/api/plate?scope=u", headers=self.h(7))
        data = await resp.json()
        self.assertTrue(data["has_logo"])
        self.assertEqual((data["plate"]["x"], data["plate"]["y"]), (1.0, 1.0))
        self.assertNotIn("logo", data["plate"])

        body = {"plate": {"x": 0.5, "y": 2, "w": 0.6, "opacity": 0.8,
                          "timing": {"mode": "custom", "start": 3, "duration": 4}, "fade": True,
                          "logo": "/etc/passwd"}}
        resp = await self.client.post("/api/plate?scope=u", headers=self.h(7), json=body)
        self.assertEqual(resp.status, 200)
        saved = db.get_user_watermark(7)
        self.assertEqual(saved["logo"], str(self.logo))  # path can't be changed from the app
        self.assertEqual(saved["y"], 1.0)  # clamped
        self.assertEqual(saved["timing"], {"mode": "custom", "start": 3.0, "duration": 4.0})
        self.bot.send_message.assert_awaited()

    async def test_image_is_served_only_to_owner(self):
        ok = await self.client.get("/api/plate/image?scope=u", headers=self.h(7))
        self.assertEqual(ok.status, 200)
        other = await self.client.get("/api/plate/image?scope=u", headers=self.h(8))
        self.assertEqual(other.status, 404)

    async def test_foreign_channel_scope_is_forbidden(self):
        resp = await self.client.get("/api/plate?scope=c-100500", headers=self.h(7))
        self.assertEqual(resp.status, 403)

    async def test_delete(self):
        resp = await self.client.post("/api/plate/delete?scope=u", headers=self.h(7), json={})
        self.assertEqual(resp.status, 200)
        self.assertEqual(db.get_user_watermark(7), {})

    async def test_index_served(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("telegram-web-app.js", await resp.text())


if __name__ == "__main__":
    unittest.main()
