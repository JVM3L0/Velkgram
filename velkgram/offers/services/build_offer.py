"""Build offers and wish matches from ingestion events (own queue and worker)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from velkgram.offers.domain.build import offer_from_message
from velkgram.offers.domain.coupon_targets import coupon_targets
from velkgram.offers.domain.models import MatchSource, Offer, OfferKind, OfferMatch
from velkgram.offers.ports.messages import SourceMessage
from velkgram.offers.ports.repository import OfferRepository
from velkgram.offers.ports.wishes import WishReader
from velkgram.shared.deals import WishView, matches
from velkgram.shared.events import (
    CouponMatchedWish,
    Event,
    MessageData,
    MessageDeleted,
    MessageEdited,
    MessageReceived,
)
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

type _Event = MessageReceived | MessageEdited | MessageDeleted

_LIVE_AGE_LIMIT = timedelta(minutes=30)
_COUPON_LOOKBACK = timedelta(days=3)


class OfferBuilder:
    def __init__(
        self,
        repo: OfferRepository,
        wishes: WishReader,
        clock: Clock,
        publish: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        self._repo = repo
        self._publish = publish
        self._outbox: list[CouponMatchedWish] = []
        self._wishes = wishes
        self._clock = clock
        self._queue: asyncio.Queue[_Event] = asyncio.Queue()

    async def on_received(self, e: MessageReceived) -> None:
        self._queue.put_nowait(e)

    async def on_edited(self, e: MessageEdited) -> None:
        self._queue.put_nowait(e)

    async def on_deleted(self, e: MessageDeleted) -> None:
        self._queue.put_nowait(e)

    async def run(self) -> None:
        while True:
            e = await self._queue.get()
            self._handle(e)
            await self._flush()
            await asyncio.sleep(0)

    async def drain(self) -> None:
        while not self._queue.empty():
            self._handle(self._queue.get_nowait())
            await self._flush()

    async def _flush(self) -> None:
        """Publish the coupon events the last `_handle` queued; a failure never stops the worker."""
        events, self._outbox = self._outbox, []
        for event in events:
            try:
                assert self._publish is not None
                await self._publish(event)
            except Exception:
                log.exception(
                    "coupon_event_publish_failed",
                    extra={
                        "channel_id": event.coupon_channel_id,
                        "message_id": event.coupon_message_id,
                    },
                )

    def _handle(self, e: _Event) -> None:
        try:
            match e:
                case MessageReceived():
                    self.ingest(e.message)
                case MessageEdited():
                    previous = self._repo.get(e.message.channel_id, e.message.message_id)
                    self.ingest(
                        e.message,
                        sold_out=e.sold_out_hint or (previous.sold_out if previous else False),
                        deleted=previous.deleted if previous else False,
                    )
                case MessageDeleted():
                    self._repo.mark_deleted(e.channel_id, e.message_ids, e.deleted_at)
        except Exception:
            self._outbox.clear()
            ids = _ids(e)
            log.exception("offer_build_failed", extra=ids)

    def ingest(
        self,
        m: MessageData,
        *,
        sold_out: bool = False,
        deleted: bool = False,
        source: MatchSource = MatchSource.live,
    ) -> bool:
        now = self._clock.now()
        offer, matchable = self._store(m, sold_out=sold_out, deleted=deleted, now=now)
        if offer is None:
            return False
        if not matchable:
            return True
        found = self._matches_for(offer, self._wishes.all, source, now)
        if found:
            self._repo.add_matches(found)
        if self._publish is not None and source == MatchSource.live and m.source == "live":
            self._queue_coupon_event(m, offer, now)
        return True

    def _queue_coupon_event(self, m: MessageData, offer: Offer, now: datetime) -> None:
        """Queue a `CouponMatchedWish` for a fresh live coupon. Never raises: the offer and the
        v1 matches are already stored, so a failure here only costs the coupon alert."""
        if offer.kind != OfferKind.coupon or now - m.date > _LIVE_AGE_LIMIT:
            return
        try:
            if offer.store is None:
                return
            recent = self._repo.recent_store_offers(offer.store, offer.posted_at - _COUPON_LOOKBACK)
            targets = coupon_targets(offer, self._wishes.enabled(), recent, now)
            if not targets:
                return
            forwarded = offer.origin_channel_id is not None and offer.origin_message_id is not None
            self._outbox.append(
                CouponMatchedWish(
                    coupon_channel_id=offer.channel_id,
                    coupon_message_id=offer.message_id,
                    coupon_origin_channel_id=offer.origin_channel_id if forwarded else None,
                    coupon_origin_message_id=offer.origin_message_id if forwarded else None,
                    coupon_posted_at=offer.posted_at,
                    coupon_received_at=m.received_at,
                    store=offer.store,
                    scope=offer.coupon_scope,
                    link=offer.redeem_link or offer.main_link,
                    targets=targets,
                )
            )
        except Exception:
            log.exception(
                "coupon_targets_failed",
                extra={"channel_id": offer.channel_id, "message_id": offer.message_id},
            )

    def ingest_many(self, items: Sequence[SourceMessage], *, source: MatchSource) -> int:
        """Ingest a batch with `ingest`'s rules: one wish read and one `add_matches` call."""
        if not items:
            return 0
        now = self._clock.now()
        wishes = self._wishes.all()
        built = 0
        found: list[OfferMatch] = []
        for item in items:
            offer, matchable = self._store(
                item.message, sold_out=item.sold_out, deleted=item.deleted, now=now
            )
            if offer is None:
                continue
            built += 1
            if not matchable:
                continue
            found.extend(self._matches_for(offer, lambda: wishes, source, now))
        if found:
            self._repo.add_matches(found)
        return built

    def _store(
        self, m: MessageData, *, sold_out: bool, deleted: bool, now: datetime
    ) -> tuple[Offer | None, bool]:
        """Upsert the offer for `m`; return it (None when `m` yields no offer) and whether it
        may be matched. A blank redelivery of an existing offer only updates flags (ruling 11).
        """
        if not m.text.strip():
            existing = self._repo.get(m.channel_id, m.message_id)
            if existing is not None:
                flags_only = replace(
                    existing,
                    sold_out=existing.sold_out or sold_out,
                    deleted=existing.deleted or deleted,
                    updated_at=now,
                )
                self._repo.upsert(flags_only)
                return flags_only, False
        offer = offer_from_message(m, sold_out=sold_out, deleted=deleted, now=now)
        if offer is not None:
            self._repo.upsert(offer)
        return offer, True

    @staticmethod
    def _matches_for(
        offer: Offer,
        wishes: Callable[[], list[WishView]],
        source: MatchSource,
        now: datetime,
    ) -> list[OfferMatch]:
        if offer.deleted or offer.norm_text is None:
            return []
        return [
            OfferMatch(
                wish_id=w.id,
                channel_id=offer.channel_id,
                message_id=offer.message_id,
                price_cents=offer.price_cents,
                posted_at=offer.posted_at,
                source=source,
                matched_at=now,
            )
            for w in wishes()
            if matches(w, offer.norm_text, offer.price_cents)
        ]


def _ids(e: _Event) -> dict[str, object]:
    if isinstance(e, MessageDeleted):
        return {"channel_id": e.channel_id, "message_id": list(e.message_ids)}
    return {"channel_id": e.message.channel_id, "message_id": e.message.message_id}
