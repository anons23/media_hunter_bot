"""Styled text watermark: fonts, colors, effects and free placement.

New-format text watermark (set by the Mini App or the bot)::

    {"type": "text", "text": "Мой канал", "font": "montserrat",
     "color": "#FFFFFF", "opacity": 0.9, "x": 0.5, "y": 0.9, "size": 0.05,
     "style": "outline", "accent": "#000000", "box_opacity": 0.55}

* ``x``/``y``: fractions of the free space (0 = left/top, 1 = right/bottom),
  like the plate, so the text always stays inside the frame.
* ``size``: font size as a fraction of the video height, so the text looks
  the same on 720p and 4K.
* ``style``: plain | shadow | outline | box (``accent`` is the effect colour).

Old watermarks (``position`` + pixel ``size``, no ``x``) keep the legacy
renderer in processor._build_text_filter.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# id -> label shown in the editor; files live in FONT_DIR/<id>.ttf
FONTS: dict[str, str] = {
    "montserrat": "Montserrat",
    "manrope": "Manrope",
    "rubik": "Rubik",
    "unbounded": "Unbounded",
    "oswald": "Oswald",
    "russo": "Russo One",
    "ptsans": "PT Sans",
    "ptsans_bold": "PT Sans Bold",
    "ptserif": "PT Serif",
    "playfair": "Playfair",
    "comfortaa": "Comfortaa",
    "caveat": "Caveat",
    "lobster": "Lobster",
    "marck": "Marck Script",
    "pixel": "Pixel",
}
LEGACY_FONTS = {"sans": "ptsans", "bold": "ptsans_bold", "serif": "ptserif", "mono": "pixel"}
DEFAULT_FONT = "montserrat"

PALETTE = [
    "#FFFFFF", "#000000", "#FFD60A", "#F5C542", "#FF8A00", "#FF3B30",
    "#FF2D95", "#D400FF", "#8E5CFF", "#2F80FF", "#00E5FF", "#2EE6A6",
    "#34C759", "#B6FF3B", "#F5E6C8", "#9AA0A6", "#0B1F4D", "#8B5A2B",
]
STYLES = ("plain", "shadow", "outline", "box")
_NAMED = {
    "white": "#FFFFFF", "black": "#000000", "red": "#FF3B30", "yellow": "#FFD60A", "orange": "#FF8A00",
    "green": "#34C759", "blue": "#2F80FF", "cyan": "#00E5FF", "pink": "#FF2D95", "purple": "#8E5CFF",
    "gold": "#F5C542", "silver": "#C0C0C0", "gray": "#9AA0A6", "grey": "#9AA0A6",
}
_LEGACY_POS = {"tl": (0.0, 0.0), "tr": (1.0, 0.0), "bl": (0.0, 1.0), "br": (1.0, 1.0), "c": (0.5, 0.5)}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_TEXT = 200
MAX_LINES = 3
MIN_SIZE, MAX_SIZE = 0.015, 0.25


def is_new_format(wm: dict[str, Any] | None) -> bool:
    return bool(wm) and wm.get("type") == "text" and "x" in wm and "y" in wm


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:
        return default
    return max(lo, min(hi, v))


def color(value: Any, default: str = "#FFFFFF") -> str:
    raw = str(value or "").strip()
    if raw.lower() in _NAMED:
        return _NAMED[raw.lower()]
    if len(raw) == 4 and raw.startswith("#"):
        raw = "#" + "".join(ch * 2 for ch in raw[1:])
    return raw.upper() if _HEX.match(raw) else default


# Characters the bundled fonts contain (Latin, Cyrillic, punctuation, ₽ № ™).
# Anything else (emoji, CJK, …) would render as empty boxes in FFmpeg.
_ALLOWED = re.compile(r"[^\n\u0020-\u007E\u00A0-\u00FF\u0400-\u045F\u0490\u0491\u2010-\u2027\u2030-\u203A\u20AC\u20BD\u2116\u2122]")


def clean_text(value: Any) -> str:
    text = _ALLOWED.sub("", str(value or "").replace("\r", ""))
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln][:MAX_LINES]
    return "\n".join(lines)[:MAX_TEXT]


def normalize(wm: dict[str, Any] | None) -> dict[str, Any]:
    """Complete, clamped text config (legacy watermarks are converted)."""
    wm = wm or {}
    if is_new_format(wm):
        x = _num(wm.get("x"), 0.5, 0.0, 1.0)
        y = _num(wm.get("y"), 0.9, 0.0, 1.0)
        size = _num(wm.get("size"), 0.05, MIN_SIZE, MAX_SIZE)
        font = wm.get("font") if wm.get("font") in FONTS else DEFAULT_FONT
        style = wm.get("style") if wm.get("style") in STYLES else "shadow"
    else:
        x, y = _LEGACY_POS.get(str(wm.get("position", "br")), (1.0, 1.0))
        # Legacy pixel size, mostly seen on 1080p sources.
        size = _num(_num(wm.get("size"), 28, 1, 200) / 1080, 0.03, MIN_SIZE, MAX_SIZE)
        font = LEGACY_FONTS.get(str(wm.get("font", "sans")), wm.get("font") if wm.get("font") in FONTS else "ptsans")
        style = "plain"
    return {
        "text": clean_text(wm.get("text")),
        "font": font,
        "color": color(wm.get("color"), "#FFFFFF"),
        "opacity": round(_num(wm.get("opacity", 0.9), 0.9, 0.1, 1.0), 3),
        "x": round(x, 4),
        "y": round(y, 4),
        "size": round(size, 4),
        "style": style,
        "accent": color(wm.get("accent"), "#000000"),
        "box_opacity": round(_num(wm.get("box_opacity", 0.55), 0.55, 0.1, 1.0), 3),
    }


def to_watermark(cfg: dict[str, Any]) -> dict[str, Any]:
    c = normalize({**cfg, "type": "text", "x": cfg.get("x", 0.5), "y": cfg.get("y", 0.9)})
    return {"type": "text", **c}


def font_path(font_id: str) -> Path:
    p = FONT_DIR / f"{font_id}.ttf"
    return p if p.exists() else FONT_DIR / f"{DEFAULT_FONT}.ttf"


def effect_px(cfg: dict[str, Any], fontsize: int) -> tuple[int, int]:
    """(outline/box padding, shadow offset) in pixels for a font size."""
    style = cfg["style"]
    if style == "outline":
        return max(1, round(fontsize * 0.08)), 0
    if style == "box":
        return max(2, round(fontsize * 0.35)), 0
    if style == "shadow":
        return 0, max(1, round(fontsize * 0.06))
    return 0, 0


def drawtext_filter(cfg: dict[str, Any], frame_h: int, work_dir: Path) -> str | None:
    """FFmpeg drawtext for a normalized config, or None when there is no text."""
    if not cfg["text"]:
        return None
    textfile = work_dir / "wm_text.txt"
    textfile.write_text(cfg["text"], encoding="utf-8")
    fontsize = max(8, round(cfg["size"] * frame_h))
    pad, shadow = effect_px(cfg, fontsize)
    op = cfg["opacity"]
    parts = [
        f"drawtext=textfile='{textfile}'",
        f"fontfile='{font_path(cfg['font'])}'",
        "expansion=none",
        f"fontsize={fontsize}",
        f"fontcolor={cfg['color']}@{op:.2f}",
        f"line_spacing={max(0, round(fontsize * 0.15))}",
        f"x='{pad}+(w-text_w-{2 * pad})*{cfg['x']:.4f}'",
        f"y='{pad}+(h-text_h-{2 * pad})*{cfg['y']:.4f}'",
    ]
    if cfg["style"] == "outline":
        parts += [f"borderw={pad}", f"bordercolor={cfg['accent']}@{op:.2f}"]
    elif cfg["style"] == "shadow":
        parts += [f"shadowx={shadow}", f"shadowy={shadow}", f"shadowcolor={cfg['accent']}@{min(1.0, op * 0.7):.2f}"]
    elif cfg["style"] == "box":
        parts += ["box=1", f"boxborderw={pad}", f"boxcolor={cfg['accent']}@{cfg['box_opacity'] * op:.2f}"]
    return ":".join(parts)


def describe(cfg: dict[str, Any]) -> str:
    style = {"plain": "без эффекта", "shadow": "с тенью", "outline": "с контуром", "box": "на подложке"}[cfg["style"]]
    return f"шрифт {FONTS.get(cfg['font'], cfg['font'])}, цвет {cfg['color']}, {style}, размер {cfg['size'] * 100:.1f}% высоты"
