"""CPU-friendly safe video uniqueness filter expressions for FFmpeg."""


def unique_video_filters() -> str:
    """Apply a subtle fingerprint change while keeping H.264 dimensions even.

    The old filter used two scale passes plus unsharp and per-frame noise.
    Those filters were unnecessarily expensive on the VPS and inflated the
    encoded output. A single even-dimension scale plus a small color change
    still changes the visual fingerprint while being much cheaper to encode.
    """
    return (
        "scale=trunc(iw*0.998/2)*2:trunc(ih*0.998/2)*2,"
        "eq=contrast=1.012:brightness=0.004:saturation=1.015"
    )
