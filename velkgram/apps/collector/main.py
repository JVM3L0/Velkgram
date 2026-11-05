"""Collector runtime: background loops and the process entry point (spec §6.1, §6.5, §7)."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from telethon import TelegramClient

from velkgram.alerting import Notifier
from velkgram.alerting.adapters.notify_log import LogNotifier
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.collector.collector import Collector
from velkgram.ingestion.adapters.telethon.client import build_client, is_auth_fatal
from velkgram.ingestion.adapters.telethon.gateway import TelethonGateway
from velkgram.ingestion.adapters.telethon.listener import register_handlers
from velkgram.shared.adapters.bus_memory import MemoryBus
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.adapters.signal_polling import PollingChangeSignal
from velkgram.shared.config import Settings, load_settings
from velkgram.shared.db import connect
from velkgram.shared.events import ChannelsChanged, WishlistChanged
from velkgram.shared.logging import configure_logging
from velkgram.shared.migrate import apply_migrations
from velkgram.shared.ports import ChangeSignal

log = logging.getLogger(__name__)

SIGNAL_INTERVAL_S = 3.0
GAP_CHECK_INTERVAL_S = 600.0
RETRY_INTERVAL_S = 60.0
HOUSEKEEPING_INTERVAL_S = 30.0

Sleep = Callable[[float], Awaitable[None]]


async def _loop(
    collector: Collector,
    sleep: Sleep,
    interval: float,
    entry: Callable[[], Awaitable[None]],
    name: str,
) -> None:
    while not collector.stopped:
        await sleep(interval)
        if collector.stopped:
            return
        try:
            await entry()
        except Exception:
            log.exception("loop_failed", extra={"loop": name})


def run_loops(
    collector: Collector, signal: ChangeSignal, sleep: Sleep = asyncio.sleep
) -> list[asyncio.Task[None]]:
    """Start the background loops. The first task is the bus dispatcher (runs until cancelled)."""

    async def poll_signal() -> None:
        changed = await signal.changed()
        if "wishlist" in changed:
            await collector.bus.publish(WishlistChanged(changed["wishlist"]))
        if "channels" in changed:
            await collector.bus.publish(ChannelsChanged(changed["channels"]))

    specs: list[tuple[str, float, Callable[[], Awaitable[None]]]] = [
        ("signal", SIGNAL_INTERVAL_S, poll_signal),
        ("gap_check", GAP_CHECK_INTERVAL_S, collector.run_gap_check),
        ("retry_failed", RETRY_INTERVAL_S, collector.run_retry_failed),
        ("housekeeping", HOUSEKEEPING_INTERVAL_S, collector.housekeeping_tick),
    ]
    bus_coro: Coroutine[Any, Any, None] = collector.bus.run()  # type: ignore[assignment]
    bus_task = asyncio.create_task(bus_coro, name="event_bus")
    bus_task.add_done_callback(_log_bus_stopped)
    tasks = [bus_task]
    tasks += [
        asyncio.create_task(_loop(collector, sleep, interval, entry, name), name=name)
        for name, interval, entry in specs
    ]
    return tasks


def _log_bus_stopped(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    log.error("event_bus_stopped", exc_info=task.exception())


async def _idle_forever() -> None:
    await asyncio.Event().wait()


async def run(
    settings: Settings,
    client: TelegramClient,
    notifier: Notifier | None = None,
    sleep: Sleep = asyncio.sleep,
) -> None:
    clock = SystemClock()
    conn = connect(settings.db_path)
    apply_migrations(conn, MIGRATION_PACKAGES)  # fatal() writes a heartbeat row
    gateway = TelethonGateway(client, clock)
    collector = Collector(conn, gateway, notifier or LogNotifier(), clock, MemoryBus(), sleep)
    tasks: list[asyncio.Task[None]] = []
    try:
        await client.connect()  # type: ignore[misc]
        await client.catch_up()  # type: ignore[misc]
        if not await client.is_user_authorized():
            await collector.fatal("session not authorized")
        else:
            await gateway.warm_entity_cache()
            register_handlers(client, collector.ingestor, clock)
            await collector.start()
            tasks = run_loops(collector, PollingChangeSignal(conn), sleep)
            await client.run_until_disconnected()  # type: ignore[misc]
    except Exception as exc:
        if not is_auth_fatal(exc):
            log.exception("collector_crashed")
            raise
        log.error("auth_fatal", extra={"reason": str(exc)})
        await collector.fatal(str(exc))
    finally:
        for t in tasks:
            t.cancel()
    await _idle_forever()


async def main() -> None:
    settings = load_settings(os.environ)
    configure_logging(settings.log_level)
    await run(settings, build_client(settings))
