import asyncio
import time
from datetime import UTC, datetime, timedelta

from tests.fakes.messages import msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import (
    InMemoryAlertRepository,
    InMemoryMessageRepository,
    InMemoryWishRepository,
)
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import MessageReceived
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
