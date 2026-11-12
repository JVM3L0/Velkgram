"""Critical path: match wishes, price, dedup, persist, then notify in the background."""

import asyncio
import logging
import time
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
from velkgram.alerting.domain.format import format_coupon_line, format_list_alert, message_link
from velkgram.alerting.domain.models import (
    ActiveCoupon,
    Alert,
    AlertKind,
    AlertMessage,
    AlertStatus,
)
from velkgram.alerting.ports.active_coupons import ActiveCoupons
from velkgram.alerting.ports.notifier import Notifier
from velkgram.alerting.ports.repository import AlertRepository
from velkgram.alerting.ports.wishlist_reader import WishlistReader
from velkgram.alerting.services.notify import send_with_retry
from velkgram.shared.deals import (
    ListItem,
    ProductList,
    WishView,
    extract_coupons,
    extract_price,
    matches_terms,
    product_list,
    within_over_max,
)
from velkgram.shared.events import AlertTriggered, MessageData, MessageEdited, MessageReceived
from velkgram.shared.ports import Clock, EventBus
from velkgram.shared.text import normalize_text

log = logging.getLogger(__name__)

_BACKFILL_MAX_AGE = timedelta(minutes=30)
_COUPON_ACTIVE_WINDOW = timedelta(hours=24)
_SLOW_PORT_MS = 50
_MAX_COUPON_LINES = 2
_MEMO_CAP = 256  # per-message memos live as long as the evaluator; keep them bounded


def _no_class(_m: MessageData) -> tuple[str | None, bool]:
    return None, False


def _split_first_line(text: str, _store: str | None) -> tuple[str, str]:
    title, _, rest = text.strip().partition("\n")
    return title.strip(), rest


def _list_hits(wish: WishView, listing: ProductList) -> tuple[ListItem, ...]:
    """Items of a list post that match the wish (header terms count), cheapest first."""
    found = [
        item
        for item in listing.items
        if matches_terms(wish, normalize_text(f"{listing.header} {item.name}"))
    ]
    return tuple(sorted(found, key=lambda i: i.price_cents))


def _identity(slug: str) -> str:
    return slug


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
        coupons: ActiveCoupons | None = None,
        classify: Callable[[MessageData], tuple[str | None, bool]] = _no_class,
        split_title: Callable[[str, str | None], tuple[str, str]] = _split_first_line,
        store_title: Callable[[str], str] = _identity,
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
        self._wish_users: dict[int, int] = {}
        self._wish_names: dict[int, str] = {}
        self._wish_max: dict[int, int] = {}
        self._coupons = coupons
        self._classify = classify
        self._split_title = split_title
        self._store_title = store_title
        self._classes: dict[tuple[int, int], tuple[str | None, bool]] = {}
        # (channel, message, price) -> coupon lines: wishes of one message share one lookup.
        self._lines: dict[tuple[int, int, int], tuple[str, ...]] = {}
        # (channel, message, wish) -> the list items that matched, for the alert text
        self._hits: dict[tuple[int, int, int], tuple[ListItem, ...]] = {}

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
        listing = self._listing_of(m)
        created: list[Alert] = []
        over_max: list[WishView] = []
        complete = True
        for wish in self._wishes.enabled():
            try:
                wish_price = price
                if listing is not None:
                    hits = _list_hits(wish, listing)
                    if not hits:
                        continue
                    wish_price = hits[0].price_cents
                    self._remember_hits(m, wish, hits)
                elif not matches_terms(wish, text):
                    continue
                if wish_price is not None and wish_price > wish.max_price_cents:
                    if listing is None and within_over_max(wish_price, wish.max_price_cents):
                        over_max.append(wish)
                    continue
                alert = self._decide(m, wish, text, wish_price, delayed, now)
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
                self._remember_wish(wish)
                created.append(alert)
        if over_max and price is not None and self._has_active_coupon(m, price, now):
            for wish in over_max:
                try:
                    alert = self._decide(m, wish, text, price, delayed, now, over_max=True)
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
                    self._remember_wish(wish)
                    created.append(alert)
        return created, complete

    def _listing_of(self, m: MessageData) -> ProductList | None:
        """The product list of a non-coupon post that lists several priced products."""
        try:
            if self._class_of(m)[1]:
                return None
            return product_list(m.text, m.links)
        except Exception:
            log.exception(
                "list_parse_failed", extra={"channel_id": m.channel_id, "message_id": m.message_id}
            )
            return None

    def _remember_hits(self, m: MessageData, wish: WishView, hits: tuple[ListItem, ...]) -> None:
        if len(self._hits) >= _MEMO_CAP:
            self._hits.pop(next(iter(self._hits)))
        self._hits[(m.channel_id, m.message_id, wish.id)] = hits

    def _remember_wish(self, wish: WishView) -> None:
        self._wish_names[wish.id] = wish.name
        self._wish_max[wish.id] = wish.max_price_cents
        self._wish_users[wish.id] = wish.user_id

    def _class_of(self, m: MessageData) -> tuple[str | None, bool]:
        """Store and coupon-post flag, classified once per message; never raises."""
        key = (m.channel_id, m.message_id)
        known = self._classes.get(key)
        if known is not None:
            return known
        try:
            known = self._classify(m)
        except Exception:
            log.exception(
                "classify_failed", extra={"channel_id": m.channel_id, "message_id": m.message_id}
            )
            known = (None, True)  # unknown: take neither coupon path
        if len(self._classes) >= _MEMO_CAP:
            self._classes.pop(next(iter(self._classes)))
        self._classes[key] = known
        return known

    def _lookup(self, m: MessageData, price: int, now: datetime) -> list[ActiveCoupon] | None:
        """Active coupons of the message's store that apply to `price`; None on port error.

        Only for non-coupon posts with a known store. Logs slow calls and failures, never raises.
        """
        if self._coupons is None:
            return []
        store, is_coupon_post = self._class_of(m)
        if store is None or is_coupon_post or extract_coupons(m.text):
            return []  # a post with its own coupon assumes it in the price
        start = time.perf_counter()
        try:
            found = self._coupons.for_store(
                store, now - _COUPON_ACTIVE_WINDOW, price, (m.channel_id, m.message_id)
            )
        except Exception:
            log.exception(
                "active_coupons_failed",
                extra={"channel_id": m.channel_id, "message_id": m.message_id},
            )
            return None
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if elapsed_ms > _SLOW_PORT_MS:
            log.warning(
                "active_coupons_slow",
                extra={
                    "channel_id": m.channel_id,
                    "message_id": m.message_id,
                    "elapsed_ms": elapsed_ms,
                },
            )
        return found

    def _has_active_coupon(self, m: MessageData, price: int, now: datetime) -> bool:
        return bool(self._lookup(m, price, now))

    def _decide(
        self,
        m: MessageData,
        wish: WishView,
        text: str,
        price: int | None,
        delayed: int | None,
        now: datetime,
        over_max: bool = False,
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
                over_max=over_max,
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

    def _coupon_lines(self, m: MessageData, alert: Alert, now: datetime) -> tuple[str, ...]:
        """Off the persist path: a port error only costs the alert its coupon lines."""
        price = alert.price_cents
        if self._coupons is None or price is None or alert.kind is not AlertKind.offer:
            return ()
        key = (m.channel_id, m.message_id, price)
        lines = self._lines.get(key)
        if lines is None:
            found = self._lookup(m, price, now) or []
            lines = tuple(format_coupon_line(c, price) for c in found[:_MAX_COUPON_LINES])
            if len(self._lines) >= _MEMO_CAP:
                self._lines.pop(next(iter(self._lines)))
            self._lines[key] = lines
        return lines

    async def _notify_and_finalize(self, m: MessageData, alert: Alert) -> None:
        t = self._clock.now()
        names = self._channel_names()
        store, _ = self._class_of(m)
        title, body = self._split_title(m.text, store)
        message = AlertMessage(
            wish_name=self._wish_names.get(alert.wish_id, str(alert.wish_id)),
            text=m.text,
            title=title,
            body=body,
            store_title=self._store_title(store) if store else None,
            price_cents=alert.price_cents,
            channel_name=names.get(m.channel_id, str(m.channel_id)),
            link=message_link(m),
            delayed_minutes=alert.delayed_minutes,
            coupon_lines=self._coupon_lines(m, alert, t),
            over_max_cents=self._wish_max.get(alert.wish_id) if alert.over_max else None,
            user_id=self._wish_users.get(alert.wish_id, 1),
        )
        hits = self._hits.pop((m.channel_id, m.message_id, alert.wish_id), None)
        if hits and alert.kind is AlertKind.offer:
            message = replace(
                message,
                rendered=format_list_alert(
                    wish_name=message.wish_name,
                    title=title,
                    items=hits,
                    channel_name=message.channel_name,
                    delayed_minutes=alert.delayed_minutes,
                    store_title=message.store_title,
                ),
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
