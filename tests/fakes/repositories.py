from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from velkgram.channels import Channel, ChannelStatus
from velkgram.ingestion import Heartbeat
from velkgram.shared.events import MessageData
from velkgram.wishlist import Wish


class InMemoryWishRepository:
    def __init__(self) -> None:
        self.version = 0
        self._wishes: dict[int, Wish] = {}
        self._next_id = 1

    def add(self, w: Wish) -> Wish:
        stored = replace(w, id=self._next_id)
        self._wishes[self._next_id] = stored
        self._next_id += 1
        self.version += 1
        return stored

    def update(self, w: Wish) -> None:
        if w.id is not None and w.id in self._wishes:
            self._wishes[w.id] = w
        self.version += 1

    def delete(self, id: int) -> None:
        self._wishes.pop(id, None)
        self.version += 1

    def get(self, id: int) -> Wish | None:
        return self._wishes.get(id)

    def list_all(self) -> list[Wish]:
        return [self._wishes[k] for k in sorted(self._wishes)]

    def list_enabled(self) -> list[Wish]:
        return [w for w in self.list_all() if w.enabled]


class InMemoryChannelRepository:
    def __init__(self) -> None:
        self.version = 0
        self._channels: dict[int, Channel] = {}
        self._next_id = 1

    def add(self, c: Channel) -> Channel:
        stored = replace(c, id=self._next_id)
        self._channels[self._next_id] = stored
        self._next_id += 1
        self.version += 1
        return stored

    def update(self, c: Channel) -> None:
        if c.id is not None and c.id in self._channels:
            self._channels[c.id] = c
        self.version += 1

    def delete(self, id: int) -> None:
        self._channels.pop(id, None)
        self.version += 1

    def get(self, id: int) -> Channel | None:
        return self._channels.get(id)

    def get_by_ref(self, ref: str) -> Channel | None:
        return next((c for c in self._channels.values() if c.ref == ref), None)

    def list_all(self) -> list[Channel]:
        return [self._channels[k] for k in sorted(self._channels)]

    def list_enabled_active(self) -> list[Channel]:
        return [c for c in self.list_all() if c.enabled and c.status is ChannelStatus.ACTIVE]

    def list_pending(self) -> list[Channel]:
        return [c for c in self.list_all() if c.status is ChannelStatus.PENDING]


class InMemoryMessageRepository:
    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], MessageData] = {}
        self._versions: dict[tuple[int, int], int] = {}
        self._deleted: dict[tuple[int, int], datetime] = {}
        self._processed: dict[tuple[int, int], datetime] = {}
        self._cursors: dict[int, int] = {}
        self._heartbeat: Heartbeat | None = None

    def add(self, m: MessageData) -> bool:
        key = (m.channel_id, m.message_id)
        if key in self._messages:
            return False
        self._messages[key] = m
        return True

    def add_version(self, m: MessageData, edited_at: datetime, sold_out_hint: bool) -> int:
        key = (m.channel_id, m.message_id)
        self._versions[key] = self._versions.get(key, 0) + 1
        return self._versions[key]

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None:
        for message_id in message_ids:
            if (channel_id, message_id) in self._messages:
                self._deleted[(channel_id, message_id)] = at

    def mark_processed(self, channel_id: int, message_id: int, at: datetime) -> None:
        if (channel_id, message_id) in self._messages:
            self._processed[(channel_id, message_id)] = at

    def list_unprocessed_since(self, since: datetime) -> list[MessageData]:
        return sorted(
            (
                m
                for key, m in self._messages.items()
                if key not in self._processed
                and key not in self._deleted
                and m.received_at >= since
            ),
            key=lambda m: (m.received_at, m.channel_id, m.message_id),
        )

    def get(self, channel_id: int, message_id: int) -> MessageData | None:
        return self._messages.get((channel_id, message_id))

    def get_cursor(self, channel_id: int) -> int | None:
        return self._cursors.get(channel_id)

    def set_cursor(self, channel_id: int, last_message_id: int) -> None:
        self._cursors[channel_id] = max(last_message_id, self._cursors.get(channel_id, 0))

    def write_heartbeat(self, h: Heartbeat) -> None:
        self._heartbeat = h

    def read_heartbeat(self) -> Heartbeat | None:
        return self._heartbeat
