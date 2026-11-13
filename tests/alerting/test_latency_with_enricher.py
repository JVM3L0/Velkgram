"""The alert path keeps its 200 ms budget while the link enricher works in the same process.

The enricher runs as threads of the collector, so it shares the GIL with the event loop that
evaluates alerts. Here the real `EnricherHost` is pushed far past real use: every link is on its
own host (no 2 s request gap) and every page is a worst-case 512 KB meta flood.
"""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.fakes.messages import msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.repositories import (
    InMemoryAlertRepository,
    InMemoryMessageRepository,
    InMemoryWishRepository,
)
from tests.timing import within
from velkgram.alerting.adapters.wishlist_api import WishlistApiReader
from velkgram.alerting.domain.dedup import DedupCache
from velkgram.alerting.services.evaluate import Evaluator
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.enrichment import EnricherHost
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.offers.domain.links import FetchOutcome, FetchPlan
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.config import Settings
from velkgram.shared.db import connect
from velkgram.shared.events import MessageReceived
from velkgram.shared.migrate import apply_migrations
from velkgram.wishlist import Wish

KB = 1024
LINKS = 4000
SAMPLES = 40


def _meta_flood(size: int) -> str:
    tag = "<meta " + 'a="' + "x" * 3900 + '" content="v">'
    return (tag * (size // len(tag) + 1))[:size]


class _FloodFetcher:
    """Answers at once with a worst-case page, on whatever host it is asked."""

    def __init__(self) -> None:
        self.body = _meta_flood(512 * KB)
        self.calls = 0

    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        self.calls += 1
        before_request(url)
        return FetchOutcome(url, (url,), 200, "text/html", self.body, "x.example")


class _NoPages:
    def fetch(self, username: str) -> str | None:
        return None


def _seed(db: Path) -> None:
    conn = connect(db)
    apply_migrations(conn, MIGRATION_PACKAGES)
    base = datetime(2026, 3, 1, tzinfo=UTC)
    rows = []
    for i in range(LINKS):
        posted = (base + timedelta(seconds=i)).isoformat()
        rows.append((i, posted, posted, f"https://h{i}.example/p"))
    conn.executemany(
        "INSERT INTO offers (channel_id, message_id, posted_at, title, has_photo, sold_out, "
        "deleted, updated_at, main_link) VALUES (1, ?, ?, 't', 0, 0, 0, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


class _Alerts:
    """The alert path of `test_internal_path_under_200ms`, one message at a time."""

    def __init__(self) -> None:
        wishes = InMemoryWishRepository()
        for i in range(50):
            wishes.add(Wish(None, f"wish {i}", (f"item{i}",), ("usado",), 100000, True))
        self.notifier = FakeNotifier()
        self.bus = MemoryBus()
        clock = _Clock()
        self.evaluator = Evaluator(
            wishes=WishlistApiReader(wishes),
            repo=InMemoryAlertRepository(),
            cache=DedupCache(timedelta(minutes=30)),
            notifier=self.notifier,
            bus=self.bus,
            clock=clock,
            mark_processed=lambda c, m: None,
            channel_names=lambda: {10: "Promos"},
        )
        self.bus.subscribe(MessageReceived, self.evaluator.on_received)
        self.ingestor = Ingestor(
            InMemoryMessageRepository(), self.bus, clock, lambda: frozenset({10})
        )
        self.runner = asyncio.create_task(self.bus.run())

    async def latency(self, i: int) -> float:
        before = self.notifier.calls
        m = msg(message_id=1000 + i, text=f"Oferta item{i % 50} por R$ 99,90")
        start = time.perf_counter()
        await self.ingestor.on_new(m)
        while self.notifier.calls == before:
            await asyncio.sleep(0)
            assert time.perf_counter() - start < 2, "alert never sent"
        return time.perf_counter() - start

    async def close(self) -> None:
        self.runner.cancel()
        await asyncio.gather(self.runner, return_exceptions=True)
        await self.evaluator.wait_idle()


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


async def measure(tmp_path: Path) -> tuple[list[float], int]:
    """Alert latencies while the enricher runs flat out, and how many links it finished."""
    db = tmp_path / "v.db"
    _seed(db)
    fetcher = _FloodFetcher()
    host = EnricherHost(
        Settings(db_path=db),
        make_fetcher=lambda: fetcher,  # type: ignore[arg-type,return-value]
        make_pages=lambda: _NoPages(),  # type: ignore[arg-type,return-value]
    )
    alerts = _Alerts()
    latencies: list[float] = []
    host.start()
    try:
        while fetcher.calls < 20:  # the enricher is busy before the first sample
            await asyncio.sleep(0.01)
        for i in range(SAMPLES):
            latencies.append(await alerts.latency(i))
            await asyncio.sleep(0.02)  # let the enricher run between alerts, like real traffic
        done = fetcher.calls
    finally:
        await asyncio.to_thread(host.stop)
        await alerts.close()
    return latencies, done


async def test_alert_latency_holds_while_the_enricher_runs_flat_out(tmp_path: Path) -> None:
    latencies, done = await measure(tmp_path)
    assert done > 100, f"the enricher barely ran ({done} links): the test proves nothing"
    within(max(latencies), 0.2, "alert latency under enricher load")
