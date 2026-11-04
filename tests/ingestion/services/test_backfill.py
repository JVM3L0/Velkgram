import dataclasses
from datetime import UTC, datetime, timedelta

from tests.fakes.clock import FakeClock
from tests.fakes.messages import msg
from tests.fakes.repositories import InMemoryMessageRepository
from tests.fakes.telegram import FakeTelegramGateway
from velkgram.ingestion.ports.telegram import TelegramDeferred
from velkgram.ingestion.services.backfill import backfill_all, backfill_channel
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import Event, MessageReceived

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def build(channels: frozenset[int] = frozenset({10, 11, 12})):
    repo = InMemoryMessageRepository()
    bus = MemoryBus()
    received: list[Event] = []

    async def collect(e: MessageReceived) -> None:
        received.append(e)

    bus.subscribe(MessageReceived, collect)
    clock = FakeClock(NOW)
    ingestor = Ingestor(repo, bus, clock, lambda: channels)
    return repo, bus, clock, ingestor, received


async def test_backfill_respects_cursor_and_caps() -> None:
    repo, bus, clock, ingestor, received = build()
    old = [dataclasses.replace(msg(i), date=NOW - timedelta(hours=7)) for i in range(1, 11)]
    fresh = [dataclasses.replace(msg(i), date=NOW - timedelta(hours=1)) for i in range(11, 261)]
    gw = FakeTelegramGateway({10: old + fresh}, {})
    n = await backfill_channel(gw, ingestor, repo, clock, 10)
    await bus.drain()
    assert n == 200
    assert gw.iter_calls == [(10, None, 200, NOW - timedelta(hours=6))]
    assert len(received) == 200
    assert all(isinstance(e, MessageReceived) and e.message.source == "backfill" for e in received)
    assert all(
        isinstance(e, MessageReceived) and e.message.date >= NOW - timedelta(hours=6)
        for e in received
    )
    assert repo.get_cursor(10) == 210

    # Second run starts from the cursor.
    n2 = await backfill_channel(gw, ingestor, repo, clock, 10)
    assert gw.iter_calls[-1][1] == 210
    assert n2 == 50


async def test_backfill_sequential_with_pause() -> None:
    repo, _bus, clock, ingestor, _ = build()
    gw = FakeTelegramGateway({10: [msg(1, 10)], 11: [msg(1, 11), msg(2, 11)], 12: [msg(1, 12)]}, {})
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    total = await backfill_all(gw, ingestor, repo, clock, [10, 11, 12], 1.0, fake_sleep)
    assert total == 4
    assert [c[0] for c in gw.iter_calls] == [10, 11, 12]
    assert sleeps == [1.0, 1.0]


async def test_deferred_channel_is_skipped_and_rest_backfilled() -> None:
    repo, _bus, clock, ingestor, _ = build()
    gw = FakeTelegramGateway({10: [msg(1, 10)], 11: [msg(1, 11)], 12: [msg(1, 12)]}, {})
    gw.deferred[11] = TelegramDeferred(120)

    async def no_sleep(s: float) -> None:
        return None

    total = await backfill_all(gw, ingestor, repo, clock, [10, 11, 12], 1.0, no_sleep)
    assert total == 2
    assert repo.get(10, 1) is not None
    assert repo.get(11, 1) is None
    assert repo.get(12, 1) is not None
