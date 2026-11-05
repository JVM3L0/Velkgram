"""Critical path: match wishes, price, dedup, persist, then notify in the background."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta

from velkgram.alerting.domain.dedup import (
    DedupCache,
    DedupKey,
    origin_key,
    price_key,
    rule_for_key,
    text_key,
)
from velkgram.alerting.domain.format import message_link
from velkgram.alerting.domain.matching import matches_terms
from velkgram.alerting.domain.models import Alert, AlertMessage, AlertStatus, WishView
from velkgram.alerting.domain.pricing import extract_price
from velkgram.alerting.ports.notifier import Notifier
from velkgram.alerting.ports.repository import AlertRepository
from velkgram.alerting.ports.wishlist_reader import WishlistReader
from velkgram.alerting.services.notify import send_with_retry
from velkgram.shared.events import AlertTriggered, MessageData, MessageEdited, MessageReceived
from velkgram.shared.ports import Clock, EventBus
from velkgram.shared.text import normalize_text

log = logging.getLogger(__name__)

_BACKFILL_MAX_AGE = timedelta(minutes=30)


def _ms(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() * 1000))


class Evaluator:
    def __init__(
        self,
        wishes: WishlistReader,
        repo: AlertRepository,
        cache: DedupCache,
        notifier: Notifier,
        bus: EventBus,
        clock: Clock,
        mark_processed: Callable[[int, int], None],
        channel_names: Callable[[], dict[int, str]],
        on_alert_sent: Callable[[], None] = lambda: None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._wishes = wishes
        self._repo = repo
        self._cache = cache
        self._notifier = notifier
        self._bus = bus
        self._clock = clock
        self._mark_processed = mark_processed
        self._channel_names = channel_names
        self._on_alert_sent = on_alert_sent
        self._sleep = sleep
        self._tasks: set[asyncio.Task[None]] = set()
        self._wish_names: dict[int, str] = {}

    async def on_received(self, e: MessageReceived) -> None:
        m = e.message
        for alert in self.evaluate(m):
            task = asyncio.create_task(self._notify(m, alert))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def on_edited(self, e: MessageEdited) -> None:
        """Re-evaluate a recent edited message that never produced an alert."""
        m = e.message
        if self._clock.now() - m.date > _BACKFILL_MAX_AGE:
            return
        if self._repo.has_alert_for_message(m.channel_id, m.message_id):
            return
        await self.on_received(MessageReceived(m))

    async def wait_idle(self) -> None:
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)

    def evaluate(self, m: MessageData) -> list[Alert]:
        """Synchronous: decide, persist and remember alerts; return the new pending ones.

        A failing wish is logged and skipped; the message is then left unprocessed.
        """
        created, complete = self._evaluate(m)
        if complete:
            try:
                self._mark_processed(m.channel_id, m.message_id)
            except Exception:
                log.exception(
                    "mark_processed_failed",
                    extra={"channel_id": m.channel_id, "message_id": m.message_id},
                )
        return created

    def _evaluate(self, m: MessageData) -> tuple[list[Alert], bool]:
        text = normalize_text(m.text)
        if not text:
            return [], True
        now = self._clock.now()
        delayed: int | None = None
        if m.source == "backfill":
            age = max(timedelta(0), now - m.date)
            if age > _BACKFILL_MAX_AGE:
                return [], True
            delayed = int(age.total_seconds() // 60)
        price = extract_price(m.text)
        created: list[Alert] = []
        complete = True
        for wish in self._wishes.enabled():
            try:
                if not matches_terms(wish, text):
                    continue
                if price is not None and price > wish.max_price_cents:
                    continue
                alert = self._decide(m, wish, text, price, delayed, now)
            except Exception:
                complete = False
                log.exception(
                    "wish_evaluation_failed",
                    extra={
                        "channel_id": m.channel_id,
                        "message_id": m.message_id,
                        "wish_id": wish.id,
                    },
                )
                continue
            if alert is not None:
                self._wish_names[wish.id] = wish.name
                created.append(alert)
        return created, complete

    def _decide(
        self,
        m: MessageData,
        wish: WishView,
        text: str,
        price: int | None,
        delayed: int | None,
        now: datetime,
    ) -> Alert | None:
        origin = origin_key(
            wish.id, m.channel_id, m.message_id, m.fwd_from_channel_id, m.fwd_from_message_id
        )
        second = price_key(wish.id, price) if price is not None else text_key(wish.id, text)
        raw_keys = (origin, second)
        keys: list[DedupKey] = [(rule_for_key(k), k) for k in raw_keys]
        hit = self._cache.find(keys, now)
        if hit is not None:
            rule, matched_id = hit
            self._repo.add_suppression(m.channel_id, m.message_id, wish.id, rule, matched_id, now)
            return None
        alert = self._repo.add(
            Alert(
                id=None,
                wish_id=wish.id,
                channel_id=m.channel_id,
                message_id=m.message_id,
                price_cents=price,
                price_unknown=price is None,
                dedup_keys=raw_keys,
                status=AlertStatus.pending,
                attempts=0,
                delayed_minutes=delayed,
                created_at=now,
                sent_at=None,
                latency_telegram_ms=0,
                latency_internal_ms=0,
                last_error=None,
            )
        )
        if alert.id is not None:
            self._cache.remember(keys, alert.id, now)
        return alert

    async def _notify(self, m: MessageData, alert: Alert) -> None:
        try:
            await self._notify_and_finalize(m, alert)
        except Exception:
            log.exception("alert_notify_failed", extra={"alert_id": alert.id})

    async def _notify_and_finalize(self, m: MessageData, alert: Alert) -> None:
        t = self._clock.now()
        names = self._channel_names()
        message = AlertMessage(
            wish_name=self._wish_names.get(alert.wish_id, str(alert.wish_id)),
            text=m.text,
            price_cents=alert.price_cents,
            channel_name=names.get(m.channel_id, str(m.channel_id)),
            link=message_link(m),
            delayed_minutes=alert.delayed_minutes,
        )
        ok, attempts, error = await send_with_retry(self._notifier, message, sleep=self._sleep)
        updated = replace(
            alert,
            status=AlertStatus.sent if ok else AlertStatus.failed,
            attempts=attempts,
            sent_at=t if ok else None,
            last_error=error,
            latency_telegram_ms=_ms(t - m.date),
            latency_internal_ms=_ms(t - m.received_at),
        )
        self._repo.update(updated)
        if ok:
            self._on_alert_sent()
        await self._bus.publish(
            AlertTriggered(
                alert_id=alert.id or 0,
                wish_id=alert.wish_id,
                channel_id=alert.channel_id,
                message_id=alert.message_id,
                status=updated.status.value,
            )
        )
