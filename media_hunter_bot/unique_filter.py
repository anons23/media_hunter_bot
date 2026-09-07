"""CPU-friendly safe video uniqueness filter expressions for FFmpeg."""

from __future__ import annotations

import random


# Keep the variation deliberately narrow: it changes the visual processing
# profile without introducing crop, timing changes, or per-frame noise.
_CONTRAST_RANGE = (0.99, 1.02)
_BRIGHTNESS_RANGE = (-0.005, 0.008)
_SATURATION_RANGE = (0.99, 1.03)


def unique_video_filters() -> str:
    """Apply subtle, quality-preserving visual variation.

    A new set of small visual parameters is selected for each unique-processing
    pass. The H.264-safe even-dimension scale remains deterministic, while
    contrast/brightness/saturation vary inside conservative bounds.
    """
    contrast = random.uniform(*_CONTRAST_RANGE)
    brightness = random.uniform(*_BRIGHTNESS_RANGE)
    saturation = random.uniform(*_SATURATION_RANGE)

    return (
        "scale=trunc(iw*0.998/2)*2:trunc(ih*0.998/2)*2,"
        f"eq=contrast={contrast:.4f}:"
        f"brightness={brightness:.4f}:"
        f"saturation={saturation:.4f}"
    )
