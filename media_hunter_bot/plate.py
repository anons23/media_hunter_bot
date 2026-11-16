"""Image/GIF plate (logo) overlay: placement, size, opacity and timing.

A plate is stored in the existing image watermark dict::

    {"type": "image", "logo": "<path>", "x": 0.5, "y": 0.9, "w": 0.6,
     "logo_opacity": 0.9, "timing": {"mode": "start", "start": 1, "duration": 5},
     "fade": true}

* ``x``/``y`` are fractions of the *free space* (frame size minus plate size):
  0 = left/top edge, 1 = right/bottom edge. The plate therefore always stays
  inside the frame on any aspect ratio.
* ``w`` is the plate width as a fraction of the video width; height follows
  the image aspect ratio.
* Legacy logos (``position`` + ``logo_size``) are converted on the fly.

Sizes are computed in Python from the probed frame size, not with scale2ref,
whose variable semantics differ between FFmpeg versions (on 6.x ``main_w``
is the logo itself, which made old logos tiny).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TIMING_MODES = ("all", "start", "end", "custom")
START_PRESET = (1.0, 5.0)  # appear at 1 s, visible 5 s
END_PRESET = 5.0  # last 5 s
FADE_MAX = 0.5
MIN_W, MAX_W = 0.05, 1.0
MIN_OPACITY = 0.1
_LEGACY_POS = {"tl": (0.0, 0.0), "tr": (1.0, 0.0), "bl": (0.0, 1.0), "br": (1.0, 1.0), "c": (0.5, 0.5)}


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def normalize(wm: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete, clamped plate config (works for legacy logos)."""
    wm = wm or {}
    if "x" in wm and "y" in wm and "w" in wm:
        x = _num(wm.get("x"), 1.0, 0.0, 1.0)
        y = _num(wm.get("y"), 1.0, 0.0, 1.0)
        w = _num(wm.get("w"), 0.3, MIN_W, MAX_W)
    else:
        x, y = _LEGACY_POS.get(str(wm.get("position", "br")), (1.0, 1.0))
        w = _num(wm.get("logo_size", 20), 20, 5, 80) / 100.0
    timing = wm.get("timing") if isinstance(wm.get("timing"), dict) else {}
    mode = timing.get("mode") if timing.get("mode") in TIMING_MODES else "all"
    start = _num(timing.get("start"), 0.0, 0.0, 3600.0)
    duration = timing.get("duration")
    duration = None if duration in (None, "", 0) else _num(duration, 5.0, 0.5, 3600.0)
    return {
        "logo": str(wm.get("logo") or ""),
        "x": round(x, 4),
        "y": round(y, 4),
        "w": round(w, 4),
        "opacity": round(_num(wm.get("logo_opacity", 0.9), 0.9, MIN_OPACITY, 1.0), 3),
        "timing": {"mode": mode, "start": round(start, 2), "duration": duration},
        "fade": bool(wm.get("fade", mode != "all")),
    }


def window(plate: dict[str, Any], duration: float | None) -> tuple[float, float | None, str | None]:
    """Visible window (start, end or None = until the end) and a user note.

    The note is set when the requested time did not fit into the video and
    the window was moved so the plate is still shown.
    """
    t = plate["timing"]
    mode = t["mode"]
    if mode == "all":
        return 0.0, None, None
    if mode == "start":
        start, length = START_PRESET
    elif mode == "end":
        if not duration:
            return 0.0, None, None
        length = min(END_PRESET, duration)
        return max(0.0, duration - length), None, None
    else:
        start = float(t["start"])
        length = t["duration"]
    if not duration:
        return start, (start + length) if length else None, None
    if start >= duration - 0.3:
        # Requested start is past the end: show the plate at the end instead.
        length = min(length or END_PRESET, duration)
        new_start = max(0.0, duration - length)
        note = (
            f"Видео {duration:.0f} с — плашку показали с {new_start:.0f}-й по "
            f"{duration:.0f}-ю секунду (заданное время не поместилось)."
        )
        return new_start, None, note
    end = start + length if length else None
    if end is not None and end >= duration:
        end = None
    return start, end, None


def describe(plate: dict[str, Any]) -> str:
    """Short human summary for confirmations."""
    t = plate["timing"]
    if t["mode"] == "all":
        when = "всё видео"
    elif t["mode"] == "start":
        when = f"в начале ({START_PRESET[0]:.0f}–{sum(START_PRESET):.0f} с)"
    elif t["mode"] == "end":
        when = f"последние {END_PRESET:.0f} с"
    else:
        dur = f"{t['duration']:g} с" if t["duration"] else "до конца"
        when = f"с {t['start']:g} с, показывать {dur}"
    fade = ", с затуханием" if plate["fade"] and t["mode"] != "all" else ""
    return f"ширина {plate['w'] * 100:.0f}%, прозрачность {plate['opacity'] * 100:.0f}%, время: {when}{fade}"


def input_args(logo: Path) -> list[str]:
    """Endless plate stream: GIFs loop, still images repeat at 30 fps."""
    if logo.suffix.lower() == ".gif":
        return ["-ignore_loop", "0", "-i", str(logo)]
    return ["-loop", "1", "-framerate", "30", "-i", str(logo)]


def overlay_graph(
    base_chain: str,
    plate: dict[str, Any],
    frame_w: int,
    duration: float | None,
) -> str:
    """filter_complex producing [v] from input 0 (video) and input 1 (plate)."""
    plate_w = max(2, int(frame_w * plate["w"]) // 2 * 2)
    start, end, _ = window(plate, duration)
    logo_chain = [f"format=rgba,scale={plate_w}:-2", f"colorchannelmixer=aa={plate['opacity']:.3f}"]
    timed = plate["timing"]["mode"] != "all"
    if timed and plate["fade"]:
        span = (end if end is not None else (duration or start + 10)) - start
        fade = max(0.1, min(FADE_MAX, span / 3))
        logo_chain.append(f"fade=t=in:st={start:.3f}:d={fade:.3f}:alpha=1")
        if end is not None:
            logo_chain.append(f"fade=t=out:st={max(start, end - fade):.3f}:d={fade:.3f}:alpha=1")
    overlay = (
        f"overlay=x='(W-w)*{plate['x']:.4f}':y='(H-h)*{plate['y']:.4f}'"
        ":shortest=1:eof_action=pass"
    )
    if timed:
        stop = f"{end:.3f}" if end is not None else "1e9"
        overlay += f":enable='between(t,{start:.3f},{stop})'"
    base = f"[0:v]{base_chain}[base];" if base_chain else "[0:v]null[base];"
    return f"{base}[1:v]{','.join(logo_chain)}[logo];[base][logo]{overlay}[v]"
