import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from tests.fakes.repositories import InMemoryMessageRepository
from velkgram.ingestion.services.ingest import Ingestor
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import (
    Event,
    MessageData,
    MessageDeleted,
    MessageEdited,
    MessageReceived,
)


class Harness:
    def __init__(self, repo: InMemoryMessageRepository | None = None) -> None:
        self.repo = repo or InMemoryMessageRepository()
        self.bus = MemoryBus()
        self.events: list[Event] = []
        for t in (MessageReceived, MessageEdited, MessageDeleted):
            self.bus.subscribe(t, self._collect)
        self.seen = 0
        self.ingestor = Ingestor(
            self.repo, self.bus, FakeClock(NOW), lambda: frozenset({10}), self._count
        )

    async def _collect(self, e: Event) -> None:
        self.events.append(e)

    def _count(self) -> None:
        self.seen += 1

    async def events_after_drain(self) -> list[Event]:
        await self.bus.drain()
        return self.events


async def test_disabled_channel_dropped() -> None:
    h = Harness()
    await h.ingestor.on_new(msg(channel_id=99))
    await h.ingestor.on_edit(msg(channel_id=99), NOW)
    await h.ingestor.on_delete(99, [1])
    assert await h.events_after_drain() == []
    assert h.repo.get(99, 1) is None
    assert h.seen == 0


async def test_new_message_stored_and_published() -> None:
    h = Harness()
    m = msg(5)
    await h.ingestor.on_new(m)
    assert await h.events_after_drain() == [MessageReceived(m)]
    assert h.repo.get(10, 5) == m
    assert h.repo.get_cursor(10) == 5
    assert h.seen == 1


async def test_duplicate_not_republished() -> None:
    h = Harness()
    await h.ingestor.on_new(msg(5))
    await h.ingestor.on_new(msg(5))
    assert len(await h.events_after_drain()) == 1
    assert h.seen == 1


class FailingAddRepo(InMemoryMessageRepository):
    def add(self, m: MessageData) -> bool:
        raise RuntimeError("disk full")


async def test_store_failure_still_publishes(caplog: pytest.LogCaptureFixture) -> None:
    h = Harness(FailingAddRepo())
    m = msg(7)
    with caplog.at_level(logging.ERROR):
        await h.ingestor.on_new(m)
    assert await h.events_after_drain() == [MessageReceived(m)]
    record = next(r for r in caplog.records if r.getMessage() == "raw_store_failed")
    assert getattr(record, "channel_id") == 10  # noqa: B009
    assert getattr(record, "message_id") == 7  # noqa: B009


async def test_edit_publishes_version_and_sold_out_hint() -> None:
    h = Harness()
    m = msg(3, text="Produto ESGOTADO")
    edited_at = datetime(2026, 11, 4, 12, 5, tzinfo=UTC)
    await h.ingestor.on_edit(m, edited_at)
    await h.ingestor.on_edit(msg(3, text="de volta"), edited_at)
    events: Sequence[Event] = await h.events_after_drain()
    assert events[0] == MessageEdited(m, 1, edited_at, True)
    assert isinstance(events[1], MessageEdited)
    assert events[1].version == 2
    assert events[1].sold_out_hint is False


async def test_delete_marks_and_publishes() -> None:
    h = Harness()
    await h.ingestor.on_new(msg(1))
    await h.ingestor.on_delete(10, [1, 2])
    events = await h.events_after_drain()
    assert events[1] == MessageDeleted(10, (1, 2), NOW)
    assert h.repo.list_unprocessed_since(NOW) == []


async def test_stopped_ingestor_ignores_messages() -> None:
    h = Harness()
    h.ingestor.stop()
    await h.ingestor.on_new(msg(1))
    await h.ingestor.on_edit(msg(1), NOW)
    await h.ingestor.on_delete(10, [1])
    assert await h.events_after_drain() == []
    assert h.repo.get(10, 1) is None
