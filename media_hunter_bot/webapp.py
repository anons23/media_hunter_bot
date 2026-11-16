"""Telegram Mini App: visual editor for the image/GIF plate (logo).

Served by the bot process itself (aiohttp) on WEBAPP_HOST:WEBAPP_PORT and
exposed through an HTTPS reverse proxy at WEBAPP_URL. Every API call is
authenticated with Telegram WebApp ``initData`` (HMAC with the bot token),
so a user can only read and change their own plates.

Scopes: ``u`` = the user's own plate, ``c<channel_id>`` = a channel plate of
a channel that belongs to the user.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

from . import db
from . import plate as plate_mod
from .config import BOT_TOKEN, WEBAPP_HOST, WEBAPP_PORT, WEBAPP_URL
from .processor import _logo_path

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "webapp_static"
INIT_DATA_MAX_AGE = 24 * 3600


def verify_init_data(init_data: str, bot_token: str, max_age: int = INIT_DATA_MAX_AGE) -> dict[str, Any] | None:
    """Validate Telegram WebApp initData and return the user dict.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = pairs.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age and time.time() - auth_date > max_age:
        return None
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return user


def editor_url(channel_id: int | None = None) -> str:
    scope = "u" if channel_id is None else f"c{int(channel_id)}"
    return f"{WEBAPP_URL}/?scope={scope}"


def _parse_scope(raw: str | None) -> int | None:
    raw = (raw or "u").strip()
    if raw == "u":
        return None
    if raw.startswith("c"):
        try:
            return int(raw[1:])
        except ValueError:
            pass
    raise web.HTTPBadRequest(text="bad scope")


async def _auth(request: web.Request) -> tuple[int, int | None]:
    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""), BOT_TOKEN)
    if user is None:
        raise web.HTTPUnauthorized(text="Откройте редактор из бота заново.")
    uid = int(user["id"])
    channel_id = _parse_scope(request.query.get("scope"))
    if channel_id is not None:
        channels = await db.alist_channels(uid)
        if not any(int(ch["channel_id"]) == channel_id for ch in channels):
            raise web.HTTPForbidden(text="Канал не найден.")
    return uid, channel_id


async def _load(uid: int, channel_id: int | None) -> dict[str, Any]:
    if channel_id is None:
        # The unpatched sync getter: the async one is overridden in
        # __init__ to return the first channel's watermark.
        return await asyncio.to_thread(db.get_user_watermark, uid)
    return await asyncio.to_thread(db.get_channel_watermark, channel_id, uid)


async def _store(uid: int, channel_id: int | None, value: dict[str, Any]) -> None:
    if channel_id is None:
        await asyncio.to_thread(db.set_user_watermark, uid, value)
    else:
        await asyncio.to_thread(db.set_channel_watermark, channel_id, uid, value)


def _current_logo(wm: dict[str, Any]) -> Path | None:
    if wm.get("type") != "image":
        return None
    return _logo_path(wm)


async def get_plate(request: web.Request) -> web.Response:
    uid, channel_id = await _auth(request)
    wm = await _load(uid, channel_id)
    logo = _current_logo(wm)
    if logo is None:
        return web.json_response({"has_logo": False})
    data = plate_mod.normalize(wm)
    data.pop("logo", None)
    return web.json_response({
        "has_logo": True,
        "kind": "gif" if logo.suffix.lower() == ".gif" else "image",
        "plate": data,
        "presets": {"start": list(plate_mod.START_PRESET), "end": plate_mod.END_PRESET, "fade": plate_mod.FADE_MAX},
    })


async def get_image(request: web.Request) -> web.StreamResponse:
    uid, channel_id = await _auth(request)
    logo = _current_logo(await _load(uid, channel_id))
    if logo is None:
        raise web.HTTPNotFound(text="Плашка не загружена.")
    resp = web.FileResponse(logo)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def save_plate(request: web.Request) -> web.Response:
    uid, channel_id = await _auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="bad json")
    incoming = body.get("plate") if isinstance(body, dict) else None
    if not isinstance(incoming, dict):
        raise web.HTTPBadRequest(text="bad plate")
    wm = await _load(uid, channel_id)
    logo = _current_logo(wm)
    if logo is None:
        raise web.HTTPNotFound(text="Сначала загрузите плашку в боте.")
    clean = plate_mod.normalize({
        "logo": str(logo),
        "x": incoming.get("x"),
        "y": incoming.get("y"),
        "w": incoming.get("w"),
        "logo_opacity": incoming.get("opacity"),
        "timing": incoming.get("timing"),
        "fade": incoming.get("fade"),
    })
    value = {
        "type": "image",
        "logo": str(logo),
        "x": clean["x"],
        "y": clean["y"],
        "w": clean["w"],
        "logo_opacity": clean["opacity"],
        "timing": clean["timing"],
        "fade": clean["fade"],
    }
    await _store(uid, channel_id, value)
    logger.info("PLATE_SAVED uid=%s channel=%s plate=%s", uid, channel_id, value)
    bot = request.app["bot"]
    scope = "для канала" if channel_id is not None else "для ваших видео"
    try:
        await bot.send_message(uid, f"✅ Плашка сохранена {scope}: {plate_mod.describe(clean)}.")
    except Exception:
        logger.warning("PLATE_SAVED notify failed uid=%s", uid)
    out = dict(clean)
    out.pop("logo", None)
    return web.json_response({"ok": True, "plate": out})


async def delete_plate(request: web.Request) -> web.Response:
    uid, channel_id = await _auth(request)
    wm = await _load(uid, channel_id)
    if wm.get("type") == "image":
        await _store(uid, channel_id, {})
        try:
            await request.app["bot"].send_message(uid, "🗑 Плашка удалена. Видео будут без неё.")
        except Exception:
            pass
    return web.json_response({"ok": True})


async def index(request: web.Request) -> web.FileResponse:
    resp = web.FileResponse(STATIC_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@web.middleware
async def _security_headers(request: web.Request, handler):
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


def build_app(bot) -> web.Application:
    app = web.Application(middlewares=[_security_headers], client_max_size=64 * 1024)
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/api/plate", get_plate)
    app.router.add_get("/api/plate/image", get_image)
    app.router.add_post("/api/plate", save_plate)
    app.router.add_post("/api/plate/delete", delete_plate)
    return app


async def start(bot) -> web.AppRunner | None:
    """Start the Mini App server if WEBAPP_URL is configured."""
    if not WEBAPP_URL:
        return None
    runner = web.AppRunner(build_app(bot), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT).start()
    except OSError:
        # The bot must keep working even if the editor port is busy.
        logger.exception("WEBAPP_START_FAILED %s:%s", WEBAPP_HOST, WEBAPP_PORT)
        await runner.cleanup()
        return None
    logger.info("WEBAPP_STARTED %s:%s public=%s", WEBAPP_HOST, WEBAPP_PORT, WEBAPP_URL)
    return runner
