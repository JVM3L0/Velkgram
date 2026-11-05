from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime

from velkgram.alerting import Alert, AlertStatus, SuppressionRule
from velkgram.channels import Channel, ChannelStatus
from velkgram.ingestion import Heartbeat
from velkgram.offers.domain.models import Offer, OfferMatch, OfferText, RetroRun
from velkgram.shared.deals import WishView
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

    def purge_text_before(self, cutoff: datetime) -> int:
        n = 0
        for key, m in list(self._messages.items()):
            if m.date < cutoff and m.text != "":
                self._messages[key] = replace(m, text="")
                n += 1
        return n

    def write_heartbeat(self, h: Heartbeat) -> None:
        self._heartbeat = h

    def read_heartbeat(self) -> Heartbeat | None:
        return self._heartbeat


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self._alerts: dict[int, Alert] = {}
        self._next_id = 1
        self.suppressions: list[tuple[int, int, int, str, int, datetime]] = []

    def _where(self, predicate: Callable[[Alert], bool]) -> list[Alert]:
        found = [a for a in self._alerts.values() if predicate(a)]
        return sorted(found, key=lambda a: (a.created_at, a.id or 0))

    def add(self, a: Alert) -> Alert:
        stored = replace(a, id=self._next_id)
        self._alerts[self._next_id] = stored
        self._next_id += 1
        return stored

    def update(self, a: Alert) -> None:
        if a.id is not None and a.id in self._alerts:
            self._alerts[a.id] = a

    def add_suppression(
        self,
        channel_id: int,
        message_id: int,
        wish_id: int,
        rule: SuppressionRule,
        matched_alert_id: int,
        at: datetime,
    ) -> None:
        self.suppressions.append(
            (channel_id, message_id, wish_id, rule.value, matched_alert_id, at)
        )

    def list_since(self, since: datetime) -> list[Alert]:
        return self._where(lambda a: a.created_at >= since)

    def list_retryable(self, since: datetime, stuck_before: datetime) -> list[Alert]:
        return self._where(
            lambda a: (
                (a.status is AlertStatus.failed and a.created_at >= since)
                or (a.status is AlertStatus.pending and a.created_at < stuck_before)
            )
        )

    def list_failed_before(self, before: datetime) -> list[Alert]:
        return self._where(lambda a: a.status is AlertStatus.failed and a.created_at < before)

    def has_alert_for_message(self, channel_id: int, message_id: int) -> bool:
        return any(
            a.channel_id == channel_id and a.message_id == message_id for a in self._alerts.values()
        )


class InMemoryOfferRepository:
    def __init__(self) -> None:
        self._offers: dict[tuple[int, int], Offer] = {}
        self._matches: dict[tuple[int, int, int], OfferMatch] = {}
        self._runs: dict[int, RetroRun] = {}

    def upsert(self, o: Offer) -> None:
        self._offers[(o.channel_id, o.message_id)] = o

    def get(self, channel_id: int, message_id: int) -> Offer | None:
        return self._offers.get((channel_id, message_id))

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None:
        for mid in message_ids:
            o = self._offers.get((channel_id, mid))
            if o is not None:
                self._offers[(channel_id, mid)] = replace(o, deleted=True, updated_at=at)

    def add_match(self, m: OfferMatch) -> bool:
        key = (m.wish_id, m.channel_id, m.message_id)
        if key in self._matches:
            return False
        self._matches[key] = m
        return True

    def add_matches(self, ms: Sequence[OfferMatch]) -> int:
        return sum(1 for m in ms if self.add_match(m))

    def delete_matches(self, wish_id: int, since: datetime | None) -> int:
        doomed = [
            k
            for k, m in self._matches.items()
            if m.wish_id == wish_id and (since is None or m.posted_at >= since)
        ]
        for k in doomed:
            del self._matches[k]
        return len(doomed)

    def iter_offers_with_text(self, since: datetime, batch_size: int) -> Iterator[list[OfferText]]:
        rows = sorted(
            (
                OfferText(o.channel_id, o.message_id, o.posted_at, o.price_cents, o.norm_text)
                for o in self._offers.values()
                if o.norm_text is not None and not o.deleted and o.posted_at >= since
            ),
            key=lambda t: (t.posted_at, t.channel_id, t.message_id),
        )
        for i in range(0, len(rows), batch_size):
            yield rows[i : i + batch_size]

    def priced_points(self, wish_id: int) -> list[tuple[datetime, int | None]]:
        ms = sorted(
            (m for m in self._matches.values() if m.wish_id == wish_id),
            key=lambda m: (m.posted_at, m.channel_id, m.message_id),
        )
        return [(m.posted_at, m.price_cents) for m in ms]

    def purge_text_before(self, cutoff: datetime) -> int:
        n = 0
        for k, o in list(self._offers.items()):
            if o.posted_at < cutoff and o.text is not None:
                self._offers[k] = replace(o, text=None, norm_text=None)
                n += 1
        return n

    def get_retro_run(self, wish_id: int) -> RetroRun | None:
        return self._runs.get(wish_id)

    def save_retro_run(self, r: RetroRun) -> None:
        self._runs[r.wish_id] = r

    def list_retro_runs(self) -> list[RetroRun]:
        return [self._runs[k] for k in sorted(self._runs)]

    def delete_wish_data(self, wish_id: int) -> None:
        self.delete_matches(wish_id, None)
        self._runs.pop(wish_id, None)

    def delete_retro_run(self, wish_id: int) -> None:
        self._runs.pop(wish_id, None)


class FakeWishReader:
    def __init__(self) -> None:
        self.views: list[WishView] = []
        self.enabled_ids: set[int] = set()

    def enabled(self) -> list[WishView]:
        return [v for v in self.views if v.id in self.enabled_ids]

    def all(self) -> list[WishView]:
        return list(self.views)
