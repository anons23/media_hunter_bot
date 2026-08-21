import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PATH если запускаете не как пакет
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from media_hunter_bot.handlers import main

if __name__ == "__main__":
    asyncio.run(main())
