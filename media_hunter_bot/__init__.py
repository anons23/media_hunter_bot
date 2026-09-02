"""Media Hunter Bot — Telegram bot for downloading and processing media."""

__version__ = "3.0.0"

# Install the safe uniqueness filter before any consumer can call
# processor.process_media(). process_media resolves _unique_video_filters
# at runtime, so this keeps the existing processor implementation intact
# while replacing the unsafe fractional scale expressions centrally.
from . import processor as _processor
from .unique_filter import unique_video_filters as _safe_unique_video_filters

_processor._unique_video_filters = _safe_unique_video_filters

del _processor
 del _safe_unique_video_filters
