"""TeleAds ad network integration (https://teleads.pro).

Same protocol as the official ``TeleAds`` PyPI SDK (0.1.7), without the extra
dependency: every incoming Telegram update is reported to TeleAds as one JSON
UDP datagram (fire-and-forget, method "activity"). TeleAds decides when to
show an ad and sends it to the user itself through the bot token configured in
the TeleAds dashboard.

Ad buttons carry callback_data starting with "/__bap"; such updates belong to
TeleAds and must not reach the bot's own handlers.

A failure here never affects the bot: errors are logged (rate-limited) and the
update is processed as usual.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from datetime import date, datetime
from typing import Any

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)

BAP_HOST = "bap.teleads.pro"
BAP_PORT = 8080
API_VERSION = 3
BAP_PREFIX = "/__bap"
_RESOLVE_EVERY_S = 600
_MAX_DATAGRAM = 65000


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        # Telegram's own JSON uses unix timestamps, so does the official SDK.
        if isinstance(obj, datetime):
            return int(round(obj.timestamp()))
        return int(datetime(obj.year, obj.month, obj.day).timestamp())
    raise TypeError(f"Type {type(obj)} not serializable")


def is_bap_update(update: dict) -> bool:
    cq = update.get("callback_query")
    data = cq.get("data") if isinstance(cq, dict) else None
    return isinstance(data, str) and data.startswith(BAP_PREFIX)


def build_packet(api_key: str, update: dict, method: str = "activity") -> bytes:
    payload = {"api_key": api_key, "version": API_VERSION, "update": update, "method": method}
    return json.dumps(payload, default=_json_default, ensure_ascii=False).encode("utf-8")


class TeleAds:
    def __init__(self, api_key: str, host: str = BAP_HOST, port: int = BAP_PORT) -> None:
        self.api_key = api_key
        self.host, self.port = host, port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._addr: tuple[str, int] | None = None
        self._resolved_at = 0.0
        self._last_error_log = 0.0
        self.sent = 0

    def _resolve(self) -> tuple[str, int]:
        info = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_DGRAM)
        return info[0][4][0], self.port

    async def _target(self) -> tuple[str, int]:
        now = time.monotonic()
        if self._addr is None or now - self._resolved_at > _RESOLVE_EVERY_S:
            try:
                # DNS lookup is blocking: keep it off the event loop.
                self._addr = await asyncio.to_thread(self._resolve)
                self._resolved_at = now
            except OSError:
                if self._addr is None:
                    raise
        return self._addr

    def _log_error(self, msg: str, *args) -> None:
        now = time.monotonic()
        if now - self._last_error_log > 300:
            self._last_error_log = now
            logger.warning(msg, *args)

    async def send(self, update: dict, method: str = "activity") -> bool:
        if not update or update.get("update_id") is None:
            return False
        try:
            packet = build_packet(self.api_key, update, method)
            if len(packet) > _MAX_DATAGRAM:
                self._log_error("TELEADS_SKIP oversize update %s bytes", len(packet))
                return False
            self._sock.sendto(packet, await self._target())
            self.sent += 1
            return True
        except Exception as e:  # never break the bot because of ads
            self._log_error("TELEADS_SEND_FAILED %s: %s", type(e).__name__, e)
            return False


class TeleAdsMiddleware(BaseMiddleware):
    """Outer update middleware: report every update, hide TeleAds' own ones."""

    def __init__(self, ads: TeleAds) -> None:
        self.ads = ads

    async def __call__(self, handler, event, data: dict[str, Any]):
        try:
            update = event.model_dump(by_alias=True, exclude_none=True)
        except Exception:
            return await handler(event, data)
        await self.ads.send(update, "activity")
        if is_bap_update(update):
            return None
        return await handler(event, data)


def install(dp, api_key: str) -> TeleAds | None:
    if not api_key:
        logger.info("TELEADS disabled (no TELEADS_SDK_KEY)")
        return None
    ads = TeleAds(api_key)
    dp.update.outer_middleware(TeleAdsMiddleware(ads))
    logger.info("TELEADS enabled")
    return ads
