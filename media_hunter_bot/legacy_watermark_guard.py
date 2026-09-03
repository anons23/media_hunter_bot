"""One-time cleanup for the legacy watermark template."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_MARKER = "legacy_watermark_cleanup_v1"
_PLACEHOLDER = "Мой канал"


def cleanup_legacy_watermark(db_path: Path) -> int:
    """Remove the old example watermark once, without touching real settings.

    The cleanup is deliberately one-shot. A user may legitimately configure
    the text "Мой канал" later; this migration must not keep deleting it on
    every restart.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return 0

    changed = 0
    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        row = con.execute(
            "SELECT value FROM settings WHERE key=?", (_MARKER,)
        ).fetchone()
        if row and str(row[0]) == "done":
            return 0

        for table in ("users", "channels"):
            rows = con.execute(
                f'SELECT rowid, watermark FROM "{table}"'
            ).fetchall()
            for rowid, raw in rows:
                try:
                    value = json.loads(raw or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                if value.get("type") != "text":
                    continue
                if str(value.get("text") or "").strip() != _PLACEHOLDER:
                    continue
                con.execute(
                    f'UPDATE "{table}" SET watermark=? WHERE rowid=?',
                    ("{}", rowid),
                )
                changed += 1

        con.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_MARKER, "done"),
        )
        con.commit()
    finally:
        con.close()

    if changed:
        logger.warning(
            "LEGACY_WATERMARK_CLEANUP removed=%s placeholder=%r",
            changed,
            _PLACEHOLDER,
        )
    return changed
