"""Find channels whose latest Telegram message is ahead of our cursor."""

import logging
from collections.abc import Mapping, Sequence

from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.ingestion.ports.telegram import TelegramDeferred, TelegramGateway

log = logging.getLogger(__name__)


async def gap_check(
    gateway: TelegramGateway,
    repo: MessageRepository,
    channel_ids: Sequence[int],
    snapshot: Mapping[int, int | None] | None = None,
) -> list[int]:
    """Channels whose latest id is ahead of the snapshotted cursor (else the current one).

    The current cursor is advanced by live messages, so without a snapshot a live message can
    hide an offline gap; the snapshot is only kept until the channel was backfilled.
    """
    behind: list[int] = []
    for channel_id in channel_ids:
        try:
            latest = await gateway.latest_message_id(channel_id)
        except TelegramDeferred as e:
            log.warning("telegram_deferred", extra={"channel_id": channel_id, "seconds": e.seconds})
            continue
        cursor = snapshot[channel_id] if snapshot and channel_id in snapshot else None
        if cursor is None:
            cursor = repo.get_cursor(channel_id)
        if latest is not None and latest > (cursor or 0):
            behind.append(channel_id)
    return behind
