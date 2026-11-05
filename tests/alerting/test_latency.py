import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from tests.fakes.messages import msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import (
    InMemoryAlertRepository,
    InMemoryMessageRepository,
    InMemoryOfferRepository,
    InMemoryWishRepository,
)
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.offers import OfferBuilder, RetroMatcher
from velkgram.offers.adapters.wishlist_api import WishlistApiWishReader
from velkgram.offers.domain.models import Offer
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import MessageData, MessageReceived, WishlistChanged
from velkgram.wishlist import Wish


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


async def test_internal_path_under_200ms() -> None:
    wishes = InMemoryWishRepository()
    for i in range(50):
        wishes.add(Wish(None, f"wish {i}", (f"item{i}",), ("usado",), 100000, True))
    notifier = FakeNotifier()
    bus = MemoryBus()
    clock = SystemClock()
    evaluator = Evaluator(
        wishes=WishlistApiReader(wishes),
        repo=InMemoryAlertRepository(),
        cache=DedupCache(timedelta(minutes=30)),
        notifier=notifier,
        bus=bus,
        clock=clock,
        mark_processed=lambda c, m: None,
        channel_names=lambda: {10: "Promos"},
    )
    bus.subscribe(MessageReceived, evaluator.on_received)
    ingestor = Ingestor(InMemoryMessageRepository(), bus, clock, lambda: frozenset({10}))
    runner = asyncio.create_task(bus.run())
    m = msg(text="Oferta item25 por R$ 99,90")
    start = time.perf_counter()
    await ingestor.on_new(m)
    while notifier.calls == 0:
        await asyncio.sleep(0)
        assert time.perf_counter() - start < 1
    elapsed = time.perf_counter() - start
    runner.cancel()
    await evaluator.wait_idle()
    assert elapsed < 0.2


class _SlowRepo(InMemoryOfferRepository):
    """Offer repo whose `upsert` records the notifier's call count, then blocks."""

    def __init__(self, notifier: FakeNotifier, block_s: float) -> None:
        super().__init__()
        self._notifier = notifier
        self._block_s = block_s
        self.calls_at_upsert: list[int] = []

    def upsert(self, o: Offer) -> None:
        self.calls_at_upsert.append(self._notifier.calls)
        deadline = time.perf_counter() + self._block_s
        while time.perf_counter() < deadline:
            time.sleep(self._block_s)
        super().upsert(o)


class _Rig:
    def __init__(
        self, block_s: float, retro_sleep: Callable[[float], Awaitable[None]] | None = None
    ):
        wishes = InMemoryWishRepository()
        wishes.add(Wish(None, "wish", ("item25",), ("usado",), 100000, True))
        self.notifier = FakeNotifier()
        self.bus = MemoryBus()
        clock = SystemClock()
        self.repo = _SlowRepo(self.notifier, block_s)
        evaluator = Evaluator(
            wishes=WishlistApiReader(wishes),
            repo=InMemoryAlertRepository(),
            cache=DedupCache(timedelta(minutes=30)),
            notifier=self.notifier,
            bus=self.bus,
            clock=clock,
            mark_processed=lambda c, m: None,
            channel_names=lambda: {10: "Promos"},
        )
        self.evaluator = evaluator
        self.builder = OfferBuilder(self.repo, WishlistApiWishReader(wishes), clock)
        self.retro = RetroMatcher(
            self.repo,
            WishlistApiWishReader(wishes),
            clock,
            90,
            sleep=retro_sleep or asyncio.sleep,
            chunk_size=1,
        )
        self.bus.subscribe(MessageReceived, evaluator.on_received)
        self.bus.subscribe(MessageReceived, self.builder.on_received)
        self.worker = asyncio.create_task(self.builder.run())
        self.runner = asyncio.create_task(self.bus.run())

    async def notified_within(self, limit_s: float) -> float:
        start = time.perf_counter()
        while self.notifier.calls == 0:
            await asyncio.sleep(0)
            assert time.perf_counter() - start < limit_s * 5
        return time.perf_counter() - start

    async def close(self) -> None:
        self.runner.cancel()
        self.worker.cancel()
        await asyncio.gather(self.runner, self.worker, return_exceptions=True)
        await self.evaluator.wait_idle()


async def test_notify_starts_before_offer_work() -> None:
    rig = _Rig(0.05)
    await rig.bus.publish(MessageReceived(msg(1, 10, "Oferta item25 por R$ 99,90")))
    elapsed = await rig.notified_within(0.2)
    await asyncio.sleep(0.1)
    await rig.close()
    assert rig.repo.calls_at_upsert[0] >= 1
    assert elapsed < 0.2


async def test_backfill_burst_does_not_delay_live_alert() -> None:
    rig = _Rig(0.005)
    for i in range(200):
        await rig.bus.publish(MessageReceived(msg(1000 + i, 10, f"nada {i}")))
    await asyncio.sleep(0)
    await rig.bus.publish(MessageReceived(msg(5, 10, "Oferta item25 por R$ 99,90")))
    elapsed = await rig.notified_within(0.2)
    await rig.close()
    assert elapsed < 0.2


async def test_offer_worker_survives_failing_event() -> None:
    rig = _Rig(0.0)
    real = rig.builder.ingest
    seen: list[int] = []

    def flaky(m: MessageData, **kw: Any) -> bool:
        seen.append(m.message_id)
        if m.message_id == 1:
            raise RuntimeError("boom")
        return real(m, **kw)

    rig.builder.ingest = flaky  # type: ignore[method-assign]
    await rig.bus.publish(MessageReceived(msg(1, 10, "x")))
    await rig.bus.publish(MessageReceived(msg(2, 10, "y")))
    for _ in range(50):
        await asyncio.sleep(0)
    await rig.close()
    assert seen == [1, 2]
    assert rig.repo.get(10, 2) is not None


async def test_retro_run_does_not_block_alerts() -> None:
    release = asyncio.Event()

    async def blocked(_s: float) -> None:
        await release.wait()

    rig = _Rig(0.0, retro_sleep=blocked)
    rig.repo.upsert(_offer())
    retro = asyncio.create_task(rig.retro.on_wishlist_changed(WishlistChanged(1)))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not retro.done()  # a run is in progress
    await rig.bus.publish(MessageReceived(msg(1, 10, "Oferta item25 por R$ 99,90")))
    await rig.notified_within(0.2)
    assert not release.is_set()
    release.set()
    await retro
    await rig.close()


def _offer() -> Offer:
    now = datetime.now(UTC)
    return Offer(
        channel_id=10,
        message_id=999,
        posted_at=now,
        title="t",
        price_cents=100,
        store=None,
        main_link=None,
        has_photo=False,
        text="item25",
        norm_text="item25",
        origin_channel_id=None,
        origin_message_id=None,
        sold_out=False,
        deleted=False,
        updated_at=now,
    )


async def test_coupon_burst_does_not_delay_persisting_a_live_alert() -> None:
    from tests.fakes.active_coupons import FakeActiveCoupons
    from tests.fakes.repositories import FakeWishReader
    from velkgram.alerting import Alert
    from velkgram.alerting.domain.models import WishView
    from velkgram.alerting.services.coupon_alerts import CouponAlerter
    from velkgram.shared.events import CouponMatchedWish, CouponTargetData

    wishes = InMemoryWishRepository()
    wishes.add(Wish(None, "wish", ("item25",), ("usado",), 100000, True))
    notifier = FakeNotifier(delay_s=0.01)
    bus = MemoryBus()
    clock = SystemClock()
    alerts = InMemoryAlertRepository()
    cache = DedupCache(timedelta(minutes=30))
    evaluator = Evaluator(
        wishes=WishlistApiReader(wishes),
        repo=alerts,
        cache=cache,
        notifier=notifier,
        bus=bus,
        clock=clock,
        mark_processed=lambda c, m: None,
        channel_names=lambda: {10: "Promos"},
        coupons=FakeActiveCoupons([]),
        classify=lambda m: ("shopee", False),
    )
    views = FakeWishReader()
    views.views = [WishView(i, f"w{i}", (("x",),), (), 100000) for i in range(1, 21)]
    views.enabled_ids = set(range(1, 21))
    alerter = CouponAlerter(views, alerts, cache, notifier, clock)
    bus.subscribe(MessageReceived, evaluator.on_received)
    bus.subscribe(CouponMatchedWish, alerter.on_coupon)
    runner = asyncio.create_task(bus.run())
    worker = asyncio.create_task(alerter.run())
    now = datetime.now(UTC)
    targets = tuple(
        CouponTargetData(i, 10, 1, 9900, False, "R$ 10 OFF", None, ("C",)) for i in range(1, 21)
    )
    event = CouponMatchedWish(10, 50, None, None, now, now, "shopee", "Shopee", None, None, targets)
    for n in range(20):
        await bus.publish(replace(event, coupon_message_id=50 + n))
    start = time.perf_counter()
    await bus.publish(MessageReceived(msg(5, 10, "Oferta item25 por R$ 99,90")))
    persisted: list[Alert] = []
    while not persisted:
        await asyncio.sleep(0)
        persisted = [
            a
            for a in alerts.list_since(datetime(2000, 1, 1, tzinfo=UTC))
            if a.kind.value == "offer"
        ]
        assert time.perf_counter() - start < 1
    elapsed = time.perf_counter() - start
    runner.cancel()
    await alerter.stop()
    worker.cancel()
    await asyncio.gather(runner, worker, return_exceptions=True)
    await evaluator.wait_idle()
    assert elapsed < 0.2
