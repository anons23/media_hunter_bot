"""Editable text progress table for Media Hunter jobs."""
from __future__ import annotations

from aiogram import Bot


class ProgressTracker:
    """Editable text progress table for a single job."""

    STAGES_URL = ("download", "analyze", "process", "send")
    STAGES_UPLOAD = ("analyze", "process", "send")
    LABELS = {
        "download": "Скачивание",
        "analyze": "Анализ файла",
        # Covers uniqueness (<=100 MB) and compression-only (>100 MB).
        "process": "Обработка",
        "send": "Отправка",
    }

    def __init__(self, bot: Bot, uid: int, has_url: bool):
        self.bot = bot
        self.uid = uid
        self.stages = list(self.STAGES_URL if has_url else self.STAGES_UPLOAD)
        self.current = -1
        self.message_id: int | None = None

    def _render(self, failed: bool = False, cancelled: bool = False) -> str:
        lines = ["⏳ <b>Обработка видео</b>", ""]
        for i, key in enumerate(self.stages):
            label = self.LABELS[key]
            if failed and i == self.current:
                icon = "❌"
            elif cancelled and i == self.current:
                icon = "⏹"
            elif i < self.current:
                icon = "✅"
            elif i == self.current:
                icon = "🔄"
            else:
                icon = "⬜"
            lines.append(f"{icon} {label}")
        if failed:
            lines.extend(["", "Обработка прервана."])
        elif cancelled:
            lines.extend(["", "Задача отменена."])
        elif self.current >= len(self.stages):
            lines[0] = "✅ <b>Готово</b>"
        return "\n".join(lines)

    async def start(self) -> None:
        self.current = 0
        try:
            msg = await self.bot.send_message(self.uid, self._render(), parse_mode="HTML")
            self.message_id = msg.message_id
        except Exception:
            self.message_id = None

    async def advance(self, stage: str) -> None:
        if stage not in self.stages:
            return
        idx = self.stages.index(stage)
        if idx < self.current:
            return
        self.current = idx
        await self._edit()

    async def complete(self) -> None:
        self.current = len(self.stages)
        await self._edit()

    async def fail(self) -> None:
        await self._edit(failed=True)

    async def cancel(self) -> None:
        await self._edit(cancelled=True)

    async def _edit(self, failed: bool = False, cancelled: bool = False) -> None:
        if self.message_id is None:
            return
        try:
            await self.bot.edit_message_text(
                self._render(failed=failed, cancelled=cancelled),
                chat_id=self.uid,
                message_id=self.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
