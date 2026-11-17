import asyncio
import json
import socket
import unittest
from datetime import datetime, timezone

from aiogram import Dispatcher
from aiogram.types import Update

import media_hunter_bot  # noqa: F401  (package bootstrap)
from media_hunter_bot import teleads


def _update(data="menu"):
    return Update.model_validate({
        "update_id": 7,
        "callback_query": {
            "id": "1", "chat_instance": "c", "data": data,
            "from": {"id": 42, "is_bot": False, "first_name": "A"},
        },
    })


def _message_update():
    return Update.model_validate({
        "update_id": 8,
        "message": {"message_id": 1, "date": 1763300000, "text": "hi",
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42, "is_bot": False, "first_name": "A"}},
    })


class PacketTests(unittest.TestCase):
    def test_packet_matches_official_sdk_shape(self):
        when = datetime(2026, 11, 17, tzinfo=timezone.utc)
        pkt = json.loads(teleads.build_packet("KEY", {"update_id": 1, "message": {"date": when}}))
        self.assertEqual(pkt["api_key"], "KEY")
        self.assertEqual(pkt["version"], 3)
        self.assertEqual(pkt["method"], "activity")
        self.assertEqual(pkt["update"]["message"]["date"], int(when.timestamp()))

    def test_bap_detection(self):
        self.assertTrue(teleads.is_bap_update({"callback_query": {"data": "/__bap:click"}}))
        self.assertFalse(teleads.is_bap_update({"callback_query": {"data": "menu"}}))
        self.assertFalse(teleads.is_bap_update({"message": {"text": "/__bap"}}))


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))
        self.rx.settimeout(2)
        self.addCleanup(self.rx.close)
        self.ads = teleads.TeleAds("KEY", host="127.0.0.1", port=self.rx.getsockname()[1])
        self.mw = teleads.TeleAdsMiddleware(self.ads)

    def _run(self, update):
        calls = []

        async def handler(event, data):
            calls.append(event)
            return "handled"

        result = asyncio.run(self.mw(handler, update, {}))
        return result, calls

    def test_reports_update_and_passes_it_on(self):
        result, calls = self._run(_message_update())
        self.assertEqual(result, "handled")
        self.assertEqual(len(calls), 1)
        pkt = json.loads(self.rx.recv(65535))
        self.assertEqual(pkt["update"]["update_id"], 8)
        self.assertEqual(pkt["update"]["message"]["date"], 1763300000)
        self.assertEqual(pkt["update"]["message"]["from"]["id"], 42)  # alias, not from_user

    def test_teleads_button_is_not_handled_by_bot(self):
        result, calls = self._run(_update("/__bap:abc"))
        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(self.rx.recv(65535))["update"]["callback_query"]["data"], "/__bap:abc")

    def test_network_failure_never_blocks_bot(self):
        self.ads.host = "does-not-exist.invalid"
        result, calls = self._run(_update())
        self.assertEqual(result, "handled")


class InstallTests(unittest.TestCase):
    def test_disabled_without_key(self):
        self.assertIsNone(teleads.install(Dispatcher(), ""))

    def test_enabled_with_key(self):
        dp = Dispatcher()
        self.assertIsInstance(teleads.install(dp, "KEY"), teleads.TeleAds)


if __name__ == "__main__":
    unittest.main()
