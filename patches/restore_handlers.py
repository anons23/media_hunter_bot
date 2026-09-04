#!/usr/bin/env python3
"""Restore handlers.py from base64 parts in this directory."""
import base64
from pathlib import Path
here = Path(__file__).resolve().parent
parts = sorted(here.glob("handlers_part_*.b64"), key=lambda p: int(p.stem.split("_")[-1]))
b64 = "".join(p.read_text() for p in parts)
data = base64.b64decode(b64)
target = here.parent / "media_hunter_bot" / "handlers.py"
if not target.parent.exists():
    target = Path("media_hunter_bot/handlers.py")
target.write_bytes(data)
print(f"Restored {target} ({len(data)} bytes)")
assert b"async def wmlogo" not in data
assert b"class Engine" in data
print("OK")
