import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon import errors

from tests.apps.test_collector_assembly import CH, Env
from tests.fakes.messages import msg
from tests.fakes.notifier import FakeNotifier
from velkgram.apps.cli import build_parser
from velkgram.apps.collector.main import run, run_loops
from velkgram.shared.config import Settings
from velkgram.shared.events import ChannelsChanged, WishlistChanged


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


class FakeSignal:
    def __init__(self, *batches: dict[str, int]) -> None:
        self._batches = list(batches)

    async def changed(self) -> dict[str, int]:
        return self._batches.pop(0) if self._batches else {}


def fake_sleep(env: Env) -> Callable[[float], object]:
    async def sleep(seconds: float) -> None:
        env.clock.advance(seconds)
        await asyncio.sleep(0)

    return sleep


async def drive(
    env: Env, signal: FakeSignal, until: Callable[[], bool], max_yields: int = 2000
) -> list[asyncio.Task[None]]:
    tasks = run_loops(env.collector, signal, sleep=fake_sleep(env))  # type: ignore[arg-type]
    for _ in range(max_yields):
        if until():
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("condition never reached")
    await env.collector.fatal("test over")
    for _ in range(10):
        await asyncio.sleep(0)
    return tasks


async def finish(tasks: list[asyncio.Task[None]]) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_signal_change_publishes_and_reloads(env: Env) -> None:
    env.channel()
    await env.collector.start()
    seen: list[object] = []

    async def on_wish(e: WishlistChanged) -> None:
        seen.append(e)

    async def on_ch(e: ChannelsChanged) -> None:
        seen.append(e)

    env.bus.subscribe(WishlistChanged, on_wish)
    env.bus.subscribe(ChannelsChanged, on_ch)
    tasks = await drive(env, FakeSignal({"wishlist": 3}, {"channels": 5}), lambda: len(seen) == 2)
    await finish(tasks)
    assert seen == [WishlistChanged(3), ChannelsChanged(5)]


async def test_gap_check_triggers_backfill(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    assert env.count("messages") == 0
    env.gateway.messages[CH] = [msg(7, CH, "Teclado R$ 100")]
    tasks = await drive(env, FakeSignal(), lambda: env.count("messages") == 1)
    await finish(tasks)
    assert env.count("messages") == 1


async def test_watcher_recovery_triggers_backfill(env: Env) -> None:
    env.channel()
    await env.collector.start()
    env.gateway.connected = False
    env.gateway.messages[CH] = [msg(9, CH, "Teclado R$ 100")]
    calls: list[int] = []
    sleep = fake_sleep(env)

    async def counting_sleep(s: float) -> None:
        calls.append(1)
        await sleep(s)  # type: ignore[misc]
        if len(calls) == 40:
            env.gateway.connected = True

    tasks = run_loops(env.collector, FakeSignal(), sleep=counting_sleep)
    for _ in range(500):
        if env.count("messages") == 1:
            break
        await asyncio.sleep(0)
    await finish(tasks)
    # Backfill from the gap check would need 600 s; the watcher alone fires within 30 s ticks.
    assert env.count("messages") == 1


async def test_loops_stop_after_fatal(env: Env) -> None:
    await env.collector.start()
    tasks = run_loops(env.collector, FakeSignal(), sleep=fake_sleep(env))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    await env.collector.fatal("boom")
    for _ in range(10):
        await asyncio.sleep(0)
    loops, bus_task = tasks[1:], tasks[0]
    assert loops
    assert all(t.done() and t.exception() is None for t in loops)
    assert not bus_task.done()
    await finish(tasks)


async def test_loops_survive_entry_point_errors(env: Env) -> None:
    await env.collector.start()

    class Boom:
        calls = 0

        async def changed(self) -> dict[str, int]:
            Boom.calls += 1
            raise RuntimeError("db locked")

    tasks = run_loops(env.collector, Boom(), sleep=fake_sleep(env))  # type: ignore[arg-type]
    for _ in range(50):
        await asyncio.sleep(0)
    assert Boom.calls > 1
    assert not tasks[1].done()
    await finish(tasks)


def _client(*, authorized: bool = True) -> MagicMock:
    client = MagicMock()
    for name in ("connect", "catch_up", "get_dialogs", "run_until_disconnected"):
        setattr(client, name, AsyncMock())
    client.is_user_authorized = AsyncMock(return_value=authorized)
    client.disconnect = AsyncMock()
    client.is_connected.return_value = True
    return client


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "v.db")


async def _settle() -> None:
    for _ in range(100):
        await asyncio.sleep(0)


async def test_auth_fatal_exception_calls_fatal_and_does_not_exit(tmp_path: Path) -> None:
    client = _client()
    client.run_until_disconnected.side_effect = errors.AuthKeyUnregisteredError(None)
    notifier = FakeNotifier()
    task = asyncio.create_task(run(_settings(tmp_path), client, notifier=notifier))
    await _settle()
    assert not task.done()
    assert len(notifier.system) == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_unauthorized_session_is_fatal(tmp_path: Path) -> None:
    client = _client(authorized=False)
    notifier = FakeNotifier()
    task = asyncio.create_task(run(_settings(tmp_path), client, notifier=notifier))
    await _settle()
    assert not task.done()
    assert "session not authorized" in notifier.system[0]
    client.get_dialogs.assert_not_called()
    client.run_until_disconnected.assert_not_called()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_non_auth_exception_propagates(tmp_path: Path) -> None:
    client = _client()
    client.run_until_disconnected.side_effect = RuntimeError("network")
    notifier = FakeNotifier()
    with pytest.raises(RuntimeError, match="network"):
        await run(_settings(tmp_path), client, notifier=notifier)
    assert notifier.system == []


async def test_startup_order(tmp_path: Path) -> None:
    client = _client()
    client.run_until_disconnected.side_effect = RuntimeError("stop")
    with pytest.raises(RuntimeError):
        await run(_settings(tmp_path), client, notifier=FakeNotifier())
    names = [
        c[0]
        for c in client.method_calls
        if c[0]
        in {
            "connect",
            "catch_up",
            "is_user_authorized",
            "get_dialogs",
            "add_event_handler",
            "run_until_disconnected",
        }
    ]
    first_handler = names.index("add_event_handler")
    assert names[:4] == ["connect", "catch_up", "is_user_authorized", "get_dialogs"]
    assert names[first_handler] == "add_event_handler"
    assert names[-1] == "run_until_disconnected"


def test_cli_has_collector_subcommand() -> None:
    assert build_parser().parse_args(["collector"]).command == "collector"
