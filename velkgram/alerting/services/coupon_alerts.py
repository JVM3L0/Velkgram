"""Coupon alerts: a queue fed by the bus handler and a worker that dedups, persists and sends."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta

from velkgram.alerting.domain.dedup import (
    DedupCache,
    DedupKey,
    coupon_content_key,
    coupon_origin_key,
    rule_for_key,
)
from velkgram.alerting.domain.format import format_coupon_alert, telegram_link
from velkgram.alerting.domain.models import Alert, AlertKind, AlertMessage, AlertStatus
from velkgram.alerting.ports.notifier import Notifier
from velkgram.alerting.ports.repository import AlertRepository
from velkgram.alerting.ports.wishlist_reader import WishlistReader
from velkgram.alerting.services.notify import send_with_retry
from velkgram.shared.deals import WishView
from velkgram.shared.events import CouponMatchedWish, CouponTargetData
from velkgram.shared.ports import Clock

log = logging.getLogger(__name__)


def _ms(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() * 1000))


class CouponAlerter:
    def __init__(
        self,
        wishes: WishlistReader,
        repo: AlertRepository,
        cache: DedupCache,
        notifier: Notifier,
        clock: Clock,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_alert_sent: Callable[[], None] = lambda: None,
    ) -> None:
        self._wishes = wishes
        self._repo = repo
        self._cache = cache
        self._notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self._on_alert_sent = on_alert_sent
        self._queue: asyncio.Queue[CouponMatchedWish] = asyncio.Queue()
        # Held while an event is processed so `drain` also waits for one the worker has taken.
        self._busy = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None

    async def on_coupon(self, e: CouponMatchedWish) -> None:
        self._queue.put_nowait(e)  # never holds the bus: a burst of targets is the worker's job

    async def run(self) -> None:
        self._worker = asyncio.current_task()
        while True:
            e = await self._queue.get()
            async with self._busy:
                await self._process_safely(e)
            await asyncio.sleep(0)

    async def drain(self) -> None:
        while True:
            if self._queue.empty():
                async with self._busy:  # waits for an in-flight event
                    pass
                if self._queue.empty():
                    return
            e = self._queue.get_nowait()
            async with self._busy:
                await self._process_safely(e)

    def idle(self) -> bool:
        return self._queue.empty() and not self._busy.locked()

    async def stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None or worker is asyncio.current_task():
            return
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    async def _process_safely(self, e: CouponMatchedWish) -> None:
        try:
            await self._process(e)
        except Exception:
            log.exception(
                "coupon_event_failed",
                extra={"channel_id": e.coupon_channel_id, "message_id": e.coupon_message_id},
            )

    async def _process(self, e: CouponMatchedWish) -> None:
        enabled = {w.id: w for w in self._wishes.enabled()}
        for target in e.targets:
            wish = enabled.get(target.wish_id)
            if wish is None:
                continue
            try:
                await self._alert_target(e, target, wish)
            except Exception:
                log.exception(
                    "coupon_target_failed",
                    extra={
                        "channel_id": e.coupon_channel_id,
                        "message_id": e.coupon_message_id,
                        "wish_id": target.wish_id,
                    },
                )

    async def _alert_target(
        self, e: CouponMatchedWish, target: CouponTargetData, wish: WishView
    ) -> None:
        now = self._clock.now()
        raw_keys = (
            coupon_origin_key(
                wish.id,
                e.coupon_channel_id,
                e.coupon_message_id,
                e.coupon_origin_channel_id,
                e.coupon_origin_message_id,
            ),
            coupon_content_key(wish.id, e.store, target.codes),
        )
        keys: list[DedupKey] = [(rule_for_key(k), k) for k in raw_keys]
        hit = self._cache.find(keys, now)
        if hit is not None:
            rule, matched_id = hit
            self._repo.add_suppression(
                e.coupon_channel_id, e.coupon_message_id, wish.id, rule, matched_id, now
            )
            return
        link = e.link or telegram_link(e.coupon_channel_id, e.coupon_message_id)
        payload = format_coupon_alert(
            e.store_title,
            target.codes,
            target.discount,
            target.min_cents,
            e.scope,
            wish.name,
            target.offer_price_cents,
            wish.max_price_cents,
            target.over_max,
            link,
        )
        alert = self._repo.add(
            Alert(
                id=None,
                wish_id=wish.id,
                channel_id=e.coupon_channel_id,
                message_id=e.coupon_message_id,
                price_cents=target.offer_price_cents,
                price_unknown=False,
                dedup_keys=raw_keys,
                status=AlertStatus.pending,
                attempts=0,
                delayed_minutes=None,
                created_at=now,
                sent_at=None,
                latency_telegram_ms=_ms(e.coupon_received_at - e.coupon_posted_at),
                latency_internal_ms=_ms(now - e.coupon_received_at),
                last_error=None,
                kind=AlertKind.coupon,
                over_max=target.over_max,
                offer_channel_id=target.offer_channel_id,
                offer_message_id=target.offer_message_id,
                payload=payload,
            )
        )
        if alert.id is not None:
            self._cache.remember(keys, alert.id, now)
        message = AlertMessage(
            wish_name=wish.name,
            text="",
            price_cents=target.offer_price_cents,
            channel_name="",
            link=link,
            delayed_minutes=None,
            rendered=payload,
        )
        ok, attempts, error = await send_with_retry(self._notifier, message, sleep=self._sleep)
        self._repo.update(
            replace(
                alert,
                status=AlertStatus.sent if ok else AlertStatus.failed,
                attempts=attempts,
                sent_at=self._clock.now() if ok else None,
                last_error=error,
            )
        )
        if ok:
            self._on_alert_sent()
