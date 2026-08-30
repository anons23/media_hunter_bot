"""OPP membership check, private-channel support, conversion logging."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import db

logger = logging.getLogger(__name__)


def B(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def _resolve_opp_target(url: str, chat_ref: str = "") -> str | int | None:
    """Resolve target for get_chat_member.

    Prefers explicit chat_ref (@username or numeric -100...).
    Falls back to parsing a public t.me/username URL.
    """
    from urllib.parse import urlparse

    ref = (chat_ref or "").strip()
    if ref:
        if ref.lstrip("-").isdigit():
            return int(ref)
        return ref if ref.startswith("@") else "@" + ref.lstrip("@")
    path = urlparse(url or "").path.strip("/")
    if not path or path.startswith("+") or path.startswith("joinchat/"):
        return None
    target = path.split("/")[0]
    if target.isdigit():
        return int(target)
    return target if target.startswith("@") else "@" + target


async def opp_check(
    bot: Bot,
    uid: int,
    username: str | None = None,
) -> tuple[bool, list[list[InlineKeyboardButton]]]:
    rows: list[list[InlineKeyboardButton]] = []
    missing = False
    for r in await db.aactive_opp():
        chat_ref = ""
        try:
            chat_ref = r["chat_ref"] or ""
        except (KeyError, IndexError):
            chat_ref = ""
        target = _resolve_opp_target(r["url"] or "", chat_ref)
        ok = False
        if target is not None:
            try:
                m = await bot.get_chat_member(target, uid)
                ok = m.status in ("member", "administrator", "creator") or (
                    m.status == "restricted" and getattr(m, "is_member", False)
                )
            except Exception:
                ok = False
        if target is None:
            logger.error(
                "OPP slot %s has no verifiable chat_ref; blocking until admin fixes it",
                r["slot"],
            )
            missing = True
            btn_url = r["url"] or None
            rows.append([B(f"⚠️ ОПП {r['slot']} требует настройки", url=btn_url)])
            continue
        if not ok:
            missing = True
            title = r["title"] or f'ОПП {r["slot"]}'
            btn_url = r["url"] or None
            rows.append([B(title, url=btn_url)])
        else:
            try:
                await db.arecord_opp_conversion(r["slot"], uid, username)
            except Exception:
                logger.exception(
                    "Failed to record OPP conversion slot=%s uid=%s", r["slot"], uid
                )
    if missing:
        rows.append([B("🔄 Проверить подписку", "check_opp")])
    return missing, rows
