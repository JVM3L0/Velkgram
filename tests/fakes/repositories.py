from dataclasses import replace

from velkgram.channels import Channel, ChannelStatus
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
