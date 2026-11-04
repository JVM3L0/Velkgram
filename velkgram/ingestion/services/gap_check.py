"""Find channels whose latest Telegram message is ahead of our cursor."""

import logging
from collections.abc import Sequence

from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.ingestion.ports.telegram import TelegramDeferred, TelegramGateway

log = logging.getLogger(__name__)


async def gap_check(
    gateway: TelegramGateway, repo: MessageRepository, channel_ids: Sequence[int]
) -> list[int]:
    behind: list[int] = []
    for channel_id in channel_ids:
        try:
            latest = await gateway.latest_message_id(channel_id)
        except TelegramDeferred as e:
            log.warning("telegram_deferred", extra={"channel_id": channel_id, "seconds": e.seconds})
            continue
        if latest is not None and latest > (repo.get_cursor(channel_id) or 0):
            behind.append(channel_id)
    return behind
