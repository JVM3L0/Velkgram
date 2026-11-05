from collections.abc import AsyncIterator
from datetime import datetime

from velkgram.ingestion.ports.telegram import ChannelResolutionError, ResolvedChannel
from velkgram.shared.events import MessageData


class FakeTelegramGateway:
    def __init__(
        self,
        messages: dict[int, list[MessageData]],
        resolutions: dict[str, ResolvedChannel | str],
        connected: bool = True,
    ) -> None:
        self.messages = messages
        self.resolutions = resolutions
        self.connected = connected
        self.deferred: dict[int, Exception] = {}
        self.iter_calls: list[tuple[int, int | None, int, datetime]] = []

    async def iter_since(
        self, channel_id: int, min_id: int | None, limit: int, not_before: datetime
    ) -> AsyncIterator[MessageData]:
        self.iter_calls.append((channel_id, min_id, limit, not_before))
        if channel_id in self.deferred:
            raise self.deferred[channel_id]
        eligible = [
            m
            for m in sorted(self.messages.get(channel_id, []), key=lambda m: m.message_id)
            if (min_id is None or m.message_id > min_id) and m.date >= not_before
        ]
        # Like Telethon with reverse=True and a limit: the oldest `limit` messages after min_id.
        for m in eligible[:limit]:
            yield m

    async def latest_message_id(self, channel_id: int) -> int | None:
        if channel_id in self.deferred:
            raise self.deferred[channel_id]
        ids = [m.message_id for m in self.messages.get(channel_id, [])]
        return max(ids) if ids else None

    async def resolve_and_join(self, ref: str) -> ResolvedChannel:
        result = self.resolutions.get(ref, f"Canal não encontrado: {ref}")
        if isinstance(result, str):
            raise ChannelResolutionError(result)
        return result

    def is_connected(self) -> bool:
        return self.connected
