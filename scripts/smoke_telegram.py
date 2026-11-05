"""Manual smoke test (not run in CI): print the last 3 messages of a channel.

Usage: uv run python scripts/smoke_telegram.py @username
"""

import asyncio
import os
import sys

from velkgram.ingestion.adapters.telethon.client import build_client
from velkgram.shared.config import load_settings


async def main(ref: str) -> None:
    client = build_client(load_settings(os.environ))
    await client.connect()
    try:
        async for msg in client.iter_messages(ref, limit=3):
            print(msg.id, msg.date, (msg.message or "")[:80])
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
