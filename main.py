import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from media_hunter_bot.config import ensure_directories, validate
from media_hunter_bot.handlers import main
from media_hunter_bot import playlist_support
from media_hunter_bot import handlers as _handlers
from media_hunter_bot import about as _about
from media_hunter_bot import ux_fixes as _ux_fixes
from media_hunter_bot import runtime_diagnostics as _runtime_diagnostics
from media_hunter_bot import pipeline_diagnostics as _pipeline_diagnostics
from aiogram import Bot as _Bot

playlist_support.patch_engine(_handlers.Engine, _handlers)
_runtime_diagnostics.patch_engine(_handlers.Engine)
_runtime_diagnostics.patch_bot_downloads(_Bot)
_pipeline_diagnostics.patch_handlers(_handlers)
_pipeline_diagnostics.patch_bot_sends(_Bot)
_handlers.menu = _about.register_about(_handlers.router, _handlers.menu)
_ux_fixes.patch_router(_handlers.router)


if __name__ == "__main__":
    ensure_directories()
    validate()
    asyncio.run(main())
