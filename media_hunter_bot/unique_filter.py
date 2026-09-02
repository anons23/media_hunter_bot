"""Safe video uniqueness filter expressions for FFmpeg."""


def unique_video_filters() -> str:
    """Apply a subtle fingerprint change while keeping H.264 dimensions even.

    FFmpeg's libx264 commonly targets yuv420p, which requires even frame
    dimensions. The old fractional scale expressions could round a 720x1280
    frame to 719x1279 and make the encoder fail. Explicit truncation to the
    nearest even dimension prevents that class of failure while preserving
    the existing two-stage scale bounce and visual fingerprint changes.
    """
    return (
        "scale=trunc(iw*0.998/2)*2:trunc(ih*0.998/2)*2,"
        "scale=trunc(iw*1.002004/2)*2:trunc(ih*1.002004/2)*2,"
        "eq=contrast=1.012:brightness=0.004:saturation=1.015,"
        "unsharp=3:3:0.4:3:3:0.0,"
        "noise=alls=1:allf=t"
    )
