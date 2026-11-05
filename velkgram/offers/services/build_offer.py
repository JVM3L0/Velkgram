"""Build offers and wish matches from ingestion events (own queue and worker)."""

import asyncio
import logging
from dataclasses import replace

from velkgram.offers.domain.build import offer_from_message
from velkgram.offers.domain.models import MatchSource, OfferMatch
from velkgram.offers.ports.repository import OfferRepository
from velkgram.offers.ports.wishes import WishReader
from velkgram.shared.deals import matches
from velkgram.shared.events import MessageData, MessageDeleted, MessageEdited, MessageReceived
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)

type _Event = MessageReceived | MessageEdited | MessageDeleted


class OfferBuilder:
    def __init__(self, repo: OfferRepository, wishes: WishReader, clock: Clock) -> None:
        self._repo = repo
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
            await asyncio.sleep(0)

    async def drain(self) -> None:
        while not self._queue.empty():
            self._handle(self._queue.get_nowait())

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
        if not m.text.strip():
            existing = self._repo.get(m.channel_id, m.message_id)
            if existing is not None:
                self._repo.upsert(
                    replace(existing, sold_out=sold_out, deleted=deleted, updated_at=now)
                )
                return True
        offer = offer_from_message(m, sold_out=sold_out, deleted=deleted, now=now)
        if offer is None:
            return False
        self._repo.upsert(offer)
        if offer.deleted or offer.norm_text is None:
            return True
        found = [
            OfferMatch(
                wish_id=w.id,
                channel_id=offer.channel_id,
                message_id=offer.message_id,
                price_cents=offer.price_cents,
                posted_at=offer.posted_at,
                source=source,
                matched_at=now,
            )
            for w in self._wishes.all()
            if matches(w, offer.norm_text, offer.price_cents)
        ]
        if found:
            self._repo.add_matches(found)
        return True


def _ids(e: _Event) -> dict[str, object]:
    if isinstance(e, MessageDeleted):
        return {"channel_id": e.channel_id, "message_id": list(e.message_ids)}
    return {"channel_id": e.message.channel_id, "message_id": e.message.message_id}
