"""Catch up on messages missed while offline."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import replace
from datetime import timedelta

from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.ingestion.ports.telegram import TelegramDeferred, TelegramGateway
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

BACKFILL_LIMIT = 200
BACKFILL_WINDOW = timedelta(hours=6)


def snapshot_cursors(repo: MessageRepository, channel_ids: Sequence[int]) -> dict[int, int | None]:
    """Cursors as they are now. Live messages advance the cursor, so take this before they can."""
    return {c: repo.get_cursor(c) for c in channel_ids}


async def backfill_channel(
    gateway: TelegramGateway,
    ingestor: Ingestor,
    repo: MessageRepository,
    clock: Clock,
    channel_id: int,
    snapshot: MutableMapping[int, int | None] | None = None,
) -> int:
    """Backfill from the snapshotted cursor when there is one (consumed on success)."""
    min_id = (
        snapshot[channel_id] if snapshot and channel_id in snapshot else repo.get_cursor(channel_id)
    )
    not_before = clock.now() - BACKFILL_WINDOW
    count = 0
    async for m in gateway.iter_since(channel_id, min_id, BACKFILL_LIMIT, not_before):
        await ingestor.on_new(replace(m, source="backfill"))
        count += 1
    if snapshot is not None:
        snapshot.pop(channel_id, None)
    return count


async def backfill_all(
    gateway: TelegramGateway,
    ingestor: Ingestor,
    repo: MessageRepository,
    clock: Clock,
    channel_ids: Sequence[int],
    pause_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    snapshot: MutableMapping[int, int | None] | None = None,
) -> int:
    total = 0
    for i, channel_id in enumerate(channel_ids):
        if i > 0:
            await sleep(pause_s)
        try:
            total += await backfill_channel(gateway, ingestor, repo, clock, channel_id, snapshot)
        except TelegramDeferred as e:
            log.warning("telegram_deferred", extra={"channel_id": channel_id, "seconds": e.seconds})
    return total
