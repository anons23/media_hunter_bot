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

playlist_support.patch_engine(_handlers.Engine, _handlers)
_handlers.menu = _about.register_about(_handlers.router, _handlers.menu)


if __name__ == "__main__":
    ensure_directories()
    validate()
    asyncio.run(main())
