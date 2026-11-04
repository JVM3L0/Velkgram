"""Catch up on messages missed while offline."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import timedelta

from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.ingestion.ports.telegram import TelegramDeferred, TelegramGateway
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

BACKFILL_LIMIT = 200
BACKFILL_WINDOW = timedelta(hours=6)


async def backfill_channel(
    gateway: TelegramGateway,
    ingestor: Ingestor,
    repo: MessageRepository,
    clock: Clock,
    channel_id: int,
) -> int:
    min_id = repo.get_cursor(channel_id)
    not_before = clock.now() - BACKFILL_WINDOW
    count = 0
    async for m in gateway.iter_since(channel_id, min_id, BACKFILL_LIMIT, not_before):
        await ingestor.on_new(replace(m, source="backfill"))
        count += 1
    return count


async def backfill_all(
    gateway: TelegramGateway,
    ingestor: Ingestor,
    repo: MessageRepository,
    clock: Clock,
    channel_ids: Sequence[int],
    pause_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    total = 0
    for i, channel_id in enumerate(channel_ids):
        if i > 0:
            await sleep(pause_s)
        try:
            total += await backfill_channel(gateway, ingestor, repo, clock, channel_id)
        except TelegramDeferred as e:
            log.warning("telegram_deferred", extra={"channel_id": channel_id, "seconds": e.seconds})
    return total
