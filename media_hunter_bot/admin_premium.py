"""Admin-only management of manually granted Premium access."""
from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db
from .config import ADMIN_ID


class AdminPremiumStates(StatesGroup):
    user_id = State()
    days = State()


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _B(text: str, data: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ensure_table() -> None:
    with db._db() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_premium_grants(
                user_id INTEGER PRIMARY KEY,
                base_until TEXT,
                grant_until TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _grant_sync(user_id: int, days: int) -> str:
    _ensure_table()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    with db._db() as c:
        user = c.execute(
            "SELECT permanent_premium, premium_until FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not user:
            raise ValueError("Пользователь ещё ни разу не запускал бота.")
        if user["permanent_premium"]:
            raise ValueError("У пользователя уже постоянный Premium.")
        existing = c.execute(
            "SELECT base_until, grant_until, created_at FROM admin_premium_grants WHERE user_id=?",
            (user_id,),
        ).fetchone()
        current_until = _parse_dt(user["premium_until"])
        if existing:
            base_until = existing["base_until"]
            created_at = existing["created_at"]
            start = current_until if current_until and current_until > now else now
        else:
            base_until = user["premium_until"]
            created_at = now_iso
            start = current_until if current_until and current_until > now else now
        grant_until = (start + timedelta(days=days)).isoformat()
        c.execute(
            """
            INSERT INTO admin_premium_grants(user_id, base_until, grant_until, created_at, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                grant_until=excluded.grant_until,
                updated_at=excluded.updated_at
            """,
            (user_id, base_until, grant_until, created_at, now_iso),
        )
        c.execute(
            "UPDATE users SET premium_until=?, updated_at=? WHERE user_id=?",
            (grant_until, now_iso, user_id),
        )
        return grant_until


def _revoke_sync(user_id: int) -> bool:
    """Revoke a manual grant without losing payments made during the grant.

    BEGIN IMMEDIATE serializes this read/restore/delete sequence with other
    SQLite writers, so a payment cannot be committed between reading the
    payment history and restoring users.premium_until.
    """
    _ensure_table()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    with db._db() as c:
        c.execute("BEGIN IMMEDIATE")
        grant = c.execute(
            "SELECT base_until FROM admin_premium_grants WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not grant:
            return False

        base_until = _parse_dt(grant["base_until"])
        rows = c.execute(
            "SELECT created_at, days FROM payments WHERE user_id=? ORDER BY created_at, id",
            (user_id,),
        ).fetchall()
        paid_until: datetime | None = None
        for row in rows:
            created = _parse_dt(row["created_at"]) or now
            base = paid_until if paid_until and paid_until > created else created
            paid_until = base + timedelta(days=int(row["days"] or 0))

        restored = max(
            [dt for dt in (base_until, paid_until) if dt is not None],
            default=None,
        )
        restored_raw = restored.isoformat() if restored and restored > now else None
        c.execute(
            "UPDATE users SET premium_until=?, updated_at=? WHERE user_id=? AND permanent_premium=0",
            (restored_raw, now_iso, user_id),
        )
        c.execute("DELETE FROM admin_premium_grants WHERE user_id=?", (user_id,))
    return True


def _list_sync() -> list[dict]:
    _ensure_table()
    now = datetime.now(timezone.utc)
    result = []
    with db._db() as c:
        rows = c.execute(
            """
            SELECT g.user_id, g.grant_until, g.created_at,
                   u.username, u.first_name, u.premium_until
            FROM admin_premium_grants g
            LEFT JOIN users u ON u.user_id=g.user_id
            ORDER BY g.grant_until
            """
        ).fetchall()
        for row in rows:
            until = _parse_dt(row["grant_until"])
            if not until or until <= now:
                continue
            result.append(dict(row))
    return result


def register_admin_premium(router: Router) -> None:
    """Register admin-only manual Premium controls.

    The "🎁 Управление Premium" button lives in the admin menu in handlers.py.
    """
    if getattr(router, "_media_hunter_admin_premium", False):
        return
    router._media_hunter_admin_premium = True

    @router.callback_query(F.data == "admin_premium")
    async def admin_premium(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        await c.answer()
        await c.message.edit_text(
            "🎁 <b>Управление Premium</b>\n\n"
            "Здесь можно вручную выдать пользователю Premium на нужное количество дней или отозвать ранее выданный доступ.",
            reply_markup=_kb([
                [_B("➕ Выдать Premium", "admin_premium_grant")],
                [_B("📋 Выданный Premium", "admin_premium_list")],
                [_B("◀️ В админку", "admin")],
            ]),
            parse_mode="HTML",
        )

    @router.callback_query(F.data == "admin_premium_grant")
    async def admin_premium_grant(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.set_state(AdminPremiumStates.user_id)
        await c.answer()
        await c.message.edit_text(
            "Введите Telegram ID пользователя, которому выдать Premium.\n\n"
            "Пользователь должен уже хотя бы один раз запустить бота.",
            reply_markup=_kb([[_B("◀️ Назад", "admin_premium")]]),
        )

    @router.message(AdminPremiumStates.user_id)
    async def admin_premium_user(m: Message, state: FSMContext):
        if m.from_user.id != ADMIN_ID:
            await state.clear()
            return
        raw = (m.text or "").strip()
        if not raw.isdigit():
            await m.answer("Введите числовой Telegram ID пользователя.")
            return
        user_id = int(raw)
        if user_id == ADMIN_ID:
            await m.answer("У администратора Premium уже постоянный.")
            return
        user = await db.aget_user(user_id)
        if not user:
            await m.answer("Такого пользователя в базе пока нет. Сначала он должен запустить бота.")
            return
        if user["permanent_premium"]:
            await m.answer("У этого пользователя уже постоянный Premium.")
            return
        await state.update_data(target_user_id=user_id)
        await state.set_state(AdminPremiumStates.days)
        current = _parse_dt(user["premium_until"])
        current_text = current.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if current else "нет"
        await m.answer(
            f"Пользователь: {user_id}\n"
            f"Текущий Premium до: {current_text}\n\n"
            "Введите срок выдачи в днях (например, 30).",
            reply_markup=_kb([[_B("◀️ Назад", "admin_premium")]]),
        )

    @router.message(AdminPremiumStates.days)
    async def admin_premium_days(m: Message, state: FSMContext):
        if m.from_user.id != ADMIN_ID:
            await state.clear()
            return
        raw = (m.text or "").strip()
        if not raw.isdigit():
            await m.answer("Введите целое число дней.")
            return
        days = int(raw)
        if not 1 <= days <= 3650:
            await m.answer("Срок должен быть от 1 до 3650 дней.")
            return
        data = await state.get_data()
        user_id = int(data["target_user_id"])
        try:
            until_raw = await asyncio.to_thread(_grant_sync, user_id, days)
        except ValueError as e:
            await state.clear()
            await m.answer(f"❌ {e}", reply_markup=_kb([[_B("◀️ В управление Premium", "admin_premium")]]))
            return
        await state.clear()
        until = _parse_dt(until_raw)
        until_text = until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if until else until_raw
        await m.answer(
            f"✅ Premium выдан пользователю {user_id}.\n\nСрок действия до: {until_text}",
            reply_markup=_kb([[_B("◀️ В управление Premium", "admin_premium")]]),
        )

    @router.callback_query(F.data == "admin_premium_list")
    async def admin_premium_list(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        rows = []
        grants = await asyncio.to_thread(_list_sync)
        if not grants:
            text = "📋 Сейчас нет активных Premium, выданных администратором."
        else:
            lines = ["📋 <b>Premium, выданный администратором</b>", ""]
            for grant in grants[:30]:
                name = html.escape(str(grant.get("username") or grant.get("first_name") or "без имени"))
                until = _parse_dt(grant.get("grant_until"))
                until_text = until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if until else "—"
                lines.append(f"👤 {grant['user_id']} — {name}\n⏳ До: {until_text}")
                rows.append([_B(f"🗑 Отозвать {grant['user_id']}", f"admin_premium_revoke:{grant['user_id']}")])
            text = "\n".join(lines)
        rows.append([_B("◀️ Назад", "admin_premium")])
        await c.answer()
        await c.message.edit_text(text, reply_markup=_kb(rows), parse_mode="HTML")

    @router.callback_query(F.data.startswith("admin_premium_revoke:"))
    async def admin_premium_revoke(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        try:
            user_id = int(c.data.split(":", 1)[1])
        except (ValueError, AttributeError):
            await c.answer("Некорректный пользователь", show_alert=True)
            return
        revoked = await asyncio.to_thread(_revoke_sync, user_id)
        if not revoked:
            await c.answer("Выданный Premium не найден", show_alert=True)
            return
        await c.answer("Premium отозван")
        await admin_premium_list(c, state)
