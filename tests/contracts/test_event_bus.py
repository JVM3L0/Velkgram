import logging

import pytest

from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.events import ChannelsChanged, WishlistChanged
from velkgram.shared.ports import EventBus

BUSES = [MemoryBus]


@pytest.fixture(params=BUSES)
def bus(request: pytest.FixtureRequest) -> EventBus:
    return request.param()  # type: ignore[no-any-return]


async def test_handler_receives_published_event(bus: EventBus) -> None:
    got: list[WishlistChanged] = []

    async def handler(e: WishlistChanged) -> None:
        got.append(e)

    bus.subscribe(WishlistChanged, handler)
    await bus.publish(WishlistChanged(version=1))
    await bus.drain()
    assert got == [WishlistChanged(version=1)]


async def test_handlers_only_receive_subscribed_type(bus: EventBus) -> None:
    got: list[WishlistChanged] = []

    async def handler(e: WishlistChanged) -> None:
        got.append(e)

    bus.subscribe(WishlistChanged, handler)
    await bus.publish(ChannelsChanged(version=1))
    await bus.drain()
    assert got == []


async def test_events_delivered_in_publish_order(bus: EventBus) -> None:
    got: list[int] = []

    async def handler(e: WishlistChanged) -> None:
        got.append(e.version)

    bus.subscribe(WishlistChanged, handler)
    for v in (1, 2, 3):
        await bus.publish(WishlistChanged(version=v))
    await bus.drain()
    assert got == [1, 2, 3]


async def test_failing_handler_does_not_stop_dispatch(
    bus: EventBus, caplog: pytest.LogCaptureFixture
) -> None:
    got: list[int] = []

    async def bad(e: WishlistChanged) -> None:
        raise RuntimeError("boom")

    async def good(e: WishlistChanged) -> None:
        got.append(e.version)

    bus.subscribe(WishlistChanged, bad)
    bus.subscribe(WishlistChanged, good)
    with caplog.at_level(logging.ERROR):
        await bus.publish(WishlistChanged(version=1))
        await bus.publish(WishlistChanged(version=2))
        await bus.drain()
    assert got == [1, 2]
    assert any(r.getMessage() == "event_handler_failed" for r in caplog.records)


async def test_drain_dispatches_events_published_by_handlers(bus: EventBus) -> None:
    got: list[ChannelsChanged] = []

    async def first(e: WishlistChanged) -> None:
        await bus.publish(ChannelsChanged(version=e.version))

    async def second(e: ChannelsChanged) -> None:
        got.append(e)

    bus.subscribe(WishlistChanged, first)
    bus.subscribe(ChannelsChanged, second)
    await bus.publish(WishlistChanged(version=7))
    await bus.drain()
    assert got == [ChannelsChanged(version=7)]
