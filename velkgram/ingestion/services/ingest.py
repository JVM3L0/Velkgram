"""Ingest live messages: store the raw data, then publish events."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from velkgram.ingestion.domain.sold_out import detect_sold_out
from velkgram.ingestion.ports.repository import MessageRepository
from velkgram.shared.events import MessageData, MessageDeleted, MessageEdited, MessageReceived
from velkgram.shared.ports import Clock, EventBus

log = logging.getLogger(__name__)


class Ingestor:
    def __init__(
        self,
        repo: MessageRepository,
        bus: EventBus,
        clock: Clock,
        enabled_channels: Callable[[], frozenset[int]],
        on_message: Callable[[], None] = lambda: None,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._clock = clock
        self._enabled = enabled_channels
        self._on_message = on_message
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def _accepts(self, channel_id: int) -> bool:
        return not self._stopped and channel_id in self._enabled()

    async def on_new(self, m: MessageData) -> None:
        if not self._accepts(m.channel_id):
            return
        try:
            if not self._repo.add(m):
                return
            self._repo.set_cursor(m.channel_id, m.message_id)
        except Exception:
            log.exception(
                "raw_store_failed",
                extra={"channel_id": m.channel_id, "message_id": m.message_id},
            )
        self._on_message()
        await self._bus.publish(MessageReceived(m))

    async def on_edit(self, m: MessageData, edited_at: datetime) -> None:
        if not self._accepts(m.channel_id):
            return
        hint = detect_sold_out(m.text)
        version = self._repo.add_version(m, edited_at, hint)
        await self._bus.publish(MessageEdited(m, version, edited_at, hint))

    async def on_delete(self, channel_id: int, ids: Sequence[int]) -> None:
        if not self._accepts(channel_id):
            return
        now = self._clock.now()
        self._repo.mark_deleted(channel_id, ids, now)
        await self._bus.publish(MessageDeleted(channel_id, tuple(ids), now))
