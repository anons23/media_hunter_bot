"""Admin handlers for OPP reports, export and retention settings."""
from __future__ import annotations

import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import db
from .config import ADMIN_ID, MEDIA_DIR

logger = logging.getLogger(__name__)


class OppAdminStates(StatesGroup):
    retain = State()


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _B(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def register_opp_admin(router: Router, menu_fn) -> None:
    """Attach OPP report/export/retain handlers to the main router."""

    @router.callback_query(F.data == "aopp_reports")
    async def aopp_reports(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        camps = await db.alist_opp_campaigns()
        rows = []
        if not camps:
            rows.append([_B("◀️ Назад", "admin")])
            await c.answer()
            await c.message.edit_text("Пока нет кампаний ОПП.", reply_markup=_kb(rows))
            return
        for camp in camps[:30]:
            status = "🟢" if not camp["ended_at"] else "⚪"
            title = (camp["title"] or f"Слот {camp['slot']}")[:28]
            rows.append([_B(f"{status} #{camp['id']} s{camp['slot']} {title}", f"aopp_rep:{camp['id']}")])
        rows.append([_B("◀️ Назад", "admin")])
        await c.answer()
        await c.message.edit_text("📊 Кампании ОПП (выберите отчёт):", reply_markup=_kb(rows))

    @router.callback_query(F.data.startswith("aopp_rep:"))
    async def aopp_rep(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        try:
            cid = int(c.data.split(":", 1)[1])
        except (ValueError, AttributeError):
            await c.answer("Некорректная кампания", show_alert=True)
            return
        stats = await db.aopp_campaign_stats(cid)
        if not stats:
            await c.answer("Кампания не найдена", show_alert=True)
            return
        camp = stats["campaign"]
        lines = [
            f"📊 ОПП слот {camp['slot']} — {camp['title'] or 'без названия'}",
            f"ID кампании: {camp['id']}",
            f"Старт: {str(camp['started_at'])[:19]}",
            f"Конец: {str(camp['ended_at'] or 'активна')[:19]}",
            f"Хранение после закрытия: {camp['retain_days']} дн.",
            f"Уникальных: {stats['total']}",
            "",
            "По дням:",
        ]
        for d in stats["by_day"]:
            lines.append(f"  {d['day']}: {d['n']}")
        if not stats["by_day"]:
            lines.append("  (пока пусто)")
        text = "\n".join(lines)
        if len(text) > 3500:
            text = text[:3500] + "\n…"
        await c.answer()
        await c.message.edit_text(
            text,
            reply_markup=_kb([
                [_B("📄 Выгрузить user_id", f"aopp_export:{cid}")],
                [_B("◀️ К списку", "aopp_reports")],
                [_B("◀️ Админка", "admin")],
            ]),
        )

    @router.callback_query(F.data.startswith("aopp_export:"))
    async def aopp_export(c: CallbackQuery, bot: Bot, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        await state.clear()
        try:
            cid = int(c.data.split(":", 1)[1])
        except (ValueError, AttributeError):
            await c.answer("Некорректная кампания", show_alert=True)
            return
        stats = await db.aopp_campaign_stats(cid)
        if not stats:
            await c.answer("Кампания не найдена", show_alert=True)
            return
        camp = stats["campaign"]
        lines = [
            f"OPP slot {camp['slot']} | {camp['title']}",
            f"campaign_id={camp['id']}",
            f"started={camp['started_at']}",
            f"ended={camp['ended_at'] or 'active'}",
            f"total_unique={stats['total']}",
            "",
            "day,count",
        ]
        for d in stats["by_day"]:
            lines.append(f"{d['day']},{d['n']}")
        lines.append("")
        lines.append("user_id,username,first_seen_at")
        for u in stats["users"]:
            un = (u.get("username") or "").replace(",", " ")
            lines.append(f"{u['user_id']},{un},{u['first_seen_at']}")
        report = "\n".join(lines)
        path = MEDIA_DIR / f"opp_report_{cid}_{uuid.uuid4().hex[:8]}.csv"
        try:
            path.write_text(report, encoding="utf-8")
            await c.answer()
            await bot.send_document(
                c.from_user.id,
                FSInputFile(path),
                caption=f"Отчёт ОПП #{cid}: {stats['total']} уникальных",
            )
        except Exception:
            logger.exception("OPP export failed campaign=%s", cid)
            await c.answer("Не удалось сформировать файл", show_alert=True)
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    @router.callback_query(F.data == "aopp_retain")
    async def aopp_retain(c: CallbackQuery, state: FSMContext):
        if c.from_user.id != ADMIN_ID:
            await c.answer("Нет доступа", show_alert=True)
            return
        days = await db.aget_opp_retain_days()
        await state.set_state(OppAdminStates.retain)
        await c.answer()
        await c.message.edit_text(
            f"⏱ Срок хранения данных закрытых кампаний ОПП сейчас: {days} дн.\n"
            "Отправьте число от 1 до 365.",
            reply_markup=_kb([[_B("◀️ Назад", "admin")]]),
        )

    @router.message(OppAdminStates.retain)
    async def aopp_retain_value(m: Message, state: FSMContext):
        if m.from_user.id != ADMIN_ID:
            await state.clear()
            return
        raw = (m.text or "").strip()
        if not raw.isdigit():
            await m.answer("Введите целое число от 1 до 365.")
            return
        days = int(raw)
        if not 1 <= days <= 365:
            await m.answer("Диапазон: 1–365 дней.")
            return
        await db.aset_opp_retain_days(days)
        await state.clear()
        await m.answer(
            f"✅ Срок хранения ОПП: {days} дн. (для новых кампаний и при закрытии слота).",
            reply_markup=menu_fn(m.from_user.id),
        )
