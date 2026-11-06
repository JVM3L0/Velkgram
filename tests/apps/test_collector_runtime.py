import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon import errors

from tests.apps.test_collector_assembly import CH, RES, Env
from tests.fakes.bot_client import FakeBotClient
from tests.fakes.clock import FakeClock
from tests.fakes.messages import NOW, msg
from tests.fakes.notifier import FakeNotifier
from tests.fakes.notifier_state import InMemoryNotifierStateStore
from tests.fakes.telegram import FakeTelegramGateway
from velkgram.alerting.adapters.notify_log import LogNotifier
from velkgram.alerting.adapters.notify_telegram import TelegramBotNotifier
from velkgram.alerting.adapters.sqlite.notifier_state import SqliteNotifierStateStore
from velkgram.alerting.ports.notifier_state import NotifierStatus
from velkgram.apps.cli import MIGRATION_PACKAGES, build_parser
from velkgram.apps.collector import main as collector_main
from velkgram.apps.collector.collector import Collector
from velkgram.apps.collector.main import build_notifier, remember_chat, run, run_loops
from velkgram.apps.notifier_wiring import ChatHolder
from velkgram.ingestion import TelegramDeferred
from velkgram.shared.config import Settings
from velkgram.shared.events import ChannelsChanged, MessageData, WishlistChanged


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


async def test_watcher_recovery_triggers_backfill(tmp_path: Path) -> None:
    # The gap check cannot see anything (latest id unknown) and iteration fails while
    # disconnected, so only the watcher's recovery backfill can ingest the message.
    class DownGateway(FakeTelegramGateway):
        async def latest_message_id(self, channel_id: int) -> int | None:
            return None

        def iter_since(self, *args: Any, **kwargs: Any) -> AsyncIterator[MessageData]:
            if not self.connected:
                raise TelegramDeferred(30)
            return super().iter_since(*args, **kwargs)

    gw = DownGateway({}, dict(RES), connected=False)
    env = Env(tmp_path, gw)
    env.channel()
    await env.collector.start()
    gw.messages[CH] = [msg(9, CH, "Teclado R$ 100")]
    ticks = 0
    original = env.collector.housekeeping_tick

    async def counting_tick() -> None:
        nonlocal ticks
        await original()
        ticks += 1
        if ticks == 2:
            gw.connected = True

    env.collector.housekeeping_tick = counting_tick  # type: ignore[method-assign]
    tasks = run_loops(env.collector, FakeSignal(), sleep=fake_sleep(env))  # type: ignore[arg-type]
    for _ in range(500):
        if env.count("messages") == 1:
            break
        await asyncio.sleep(0)
    await finish(tasks)
    assert env.count("messages") == 1


async def test_loop_intervals(env: Env) -> None:
    await env.collector.start()
    intervals: dict[str, float] = {}

    async def recording_sleep(seconds: float) -> None:
        task = asyncio.current_task()
        assert task is not None
        intervals[task.get_name()] = seconds
        env.clock.advance(seconds)
        await asyncio.sleep(0)

    tasks = run_loops(env.collector, FakeSignal(), sleep=recording_sleep)
    for _ in range(10):
        await asyncio.sleep(0)
    await finish(tasks)
    assert intervals == {"signal": 3, "gap_check": 600, "retry_failed": 60, "housekeeping": 30}


async def test_bus_failure_is_logged(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    await env.collector.start()

    async def dying_run() -> None:
        raise RuntimeError("bus down")

    env.bus.run = dying_run  # type: ignore[method-assign]
    tasks = run_loops(env.collector, FakeSignal(), sleep=fake_sleep(env))  # type: ignore[arg-type]
    for _ in range(10):
        await asyncio.sleep(0)
    await finish(tasks)
    assert any(r.message == "event_bus_stopped" for r in caplog.records)


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


async def test_auth_fatal_during_catch_up_is_fatal(tmp_path: Path) -> None:
    client = _client()
    client.catch_up.side_effect = errors.AuthKeyUnregisteredError(None)
    notifier = FakeNotifier()
    task = asyncio.create_task(run(_settings(tmp_path), client, notifier=notifier))
    await _settle()
    assert not task.done()
    assert len(notifier.system) == 1
    client.run_until_disconnected.assert_not_called()
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


async def test_start_failure_notifies_once_then_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: Collector) -> None:
        raise RuntimeError("db locked")

    monkeypatch.setattr(Collector, "start", boom)
    notifier = FakeNotifier()
    with pytest.raises(RuntimeError, match="db locked"):
        await run(_settings(tmp_path), _client(), notifier=notifier)
    assert notifier.system == ["Velkgram: o coletor falhou ao iniciar: RuntimeError"]


async def test_start_failure_notify_error_does_not_mask_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: Collector) -> None:
        raise RuntimeError("db locked")

    async def bad_notify(text: str) -> None:
        raise ValueError("notifier down")

    monkeypatch.setattr(Collector, "start", boom)
    notifier = FakeNotifier()
    notifier.notify_system = bad_notify  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="db locked"):
        await run(_settings(tmp_path), _client(), notifier=notifier)


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


# --- notifier wiring ---------------------------------------------------------------------


def _tg_settings(tmp_path: Path, chat: int | None = None) -> Settings:
    return Settings(
        db_path=tmp_path / "v.db",
        notifier="telegram",
        alert_bot_token="tok:SECRET",
        alert_chat_id=chat,
    )


def _conn(tmp_path: Path) -> sqlite3.Connection:
    from velkgram.shared.db import connect
    from velkgram.shared.migrate import apply_migrations

    conn = connect(tmp_path / "v.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    return conn


def test_build_notifier_log_records_disabled(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    notifier, bot, holder = build_notifier(
        Settings(db_path=tmp_path / "v.db"), conn, FakeClock(NOW)
    )
    assert isinstance(notifier, LogNotifier)
    assert bot is None and holder is None
    row = SqliteNotifierStateStore(conn).get()
    assert row is not None and row[0] is NotifierStatus.DISABLED


def test_build_notifier_telegram_records_starting_on_empty_table(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    notifier, bot, holder = build_notifier(
        _tg_settings(tmp_path), conn, FakeClock(NOW), FakeBotClient()
    )
    assert notifier is bot and isinstance(bot, TelegramBotNotifier)
    assert holder is not None and holder.override is None
    row = SqliteNotifierStateStore(conn).get()
    assert row is not None and row[:2] == (NotifierStatus.ERROR, "iniciando")


def test_build_notifier_telegram_keeps_existing_row(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    SqliteNotifierStateStore(conn).set(NotifierStatus.OK, None, NOW)
    build_notifier(_tg_settings(tmp_path), conn, FakeClock(NOW), FakeBotClient())
    row = SqliteNotifierStateStore(conn).get()
    assert row is not None and row[:2] == (NotifierStatus.OK, None)


def test_chat_holder_resolution_order() -> None:
    state = InMemoryNotifierStateStore()
    state.set(NotifierStatus.OK, None, NOW)
    state.set_chat_id(3)
    assert ChatHolder(None).resolve(state) == 3
    assert ChatHolder(None, 2).resolve(state) == 2
    assert ChatHolder(1, 2).resolve(state) == 1


def _user(me_id: int = 42) -> MagicMock:
    user = MagicMock()
    user.get_me = AsyncMock(return_value=MagicMock(id=me_id))
    return user


def _state_with_row() -> InMemoryNotifierStateStore:
    state = InMemoryNotifierStateStore()
    state.set(NotifierStatus.ERROR, "iniciando", NOW)
    return state


async def test_remember_chat_stores_me_id() -> None:
    state, holder = _state_with_row(), ChatHolder(None)
    await remember_chat(_user(42), holder, state)
    assert holder.current == 42 and state.get_chat_id() == 42


async def test_remember_chat_override_never_calls_get_me() -> None:
    user, state = _user(), _state_with_row()
    await remember_chat(user, ChatHolder(7), state)
    user.get_me.assert_not_called()
    assert state.get_chat_id() is None


async def test_remember_chat_failure_logs_and_keeps_stored_chat(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state, holder = _state_with_row(), ChatHolder(None)
    state.set_chat_id(9)
    user = _user()
    user.get_me.side_effect = ConnectionError("down")
    await remember_chat(user, holder, state)
    assert holder.current is None and holder.resolve(state) == 9
    rec = [r for r in caplog.records if r.message == "get_me_failed"]
    assert rec and rec[0].__dict__["error"] == "ConnectionError"


async def test_remember_chat_hang_times_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(collector_main, "GET_ME_TIMEOUT_S", 0.01)
    state, holder = _state_with_row(), ChatHolder(None)
    state.set_chat_id(9)
    user = _user()

    async def hang() -> None:
        await asyncio.Event().wait()

    user.get_me = hang
    await remember_chat(user, holder, state)
    assert holder.resolve(state) == 9
    assert any(r.message == "get_me_failed" for r in caplog.records)


async def test_run_with_log_notifier_records_disabled(tmp_path: Path) -> None:
    client = _client()
    task = asyncio.create_task(run(_settings(tmp_path), client))
    await _settle()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    row = SqliteNotifierStateStore(_conn(tmp_path)).get()
    assert row is not None and row[0] is NotifierStatus.DISABLED


async def test_run_with_telegram_closes_bot_on_shutdown(tmp_path: Path) -> None:
    client = _client()
    client.get_me = AsyncMock(return_value=MagicMock(id=5))
    client.run_until_disconnected.side_effect = RuntimeError("stop")
    bot = FakeBotClient()
    with pytest.raises(RuntimeError):
        await run(_tg_settings(tmp_path), client, bot_client=bot)
    assert bot.start_calls == ["tok:SECRET"]
    assert bot.disconnects >= 1
    store = SqliteNotifierStateStore(_conn(tmp_path))
    assert store.get_chat_id() == 5


def test_build_notifier_telegram_without_token_raises(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    settings = Settings(db_path=tmp_path / "v.db", notifier="telegram", alert_bot_token=None)
    with pytest.raises(ValueError, match="ALERT_BOT_TOKEN is required when NOTIFIER=telegram"):
        build_notifier(settings, conn, FakeClock(NOW), FakeBotClient())
    assert SqliteNotifierStateStore(conn).get() is None


async def test_run_does_not_wait_for_bot_login(tmp_path: Path) -> None:
    client = _client()
    client.get_me = AsyncMock(return_value=MagicMock(id=5))
    client.run_until_disconnected.side_effect = RuntimeError("stop")
    bot = FakeBotClient()
    bot.start_gate = asyncio.Event()  # never released: the login hangs
    async with asyncio.timeout(5):
        with pytest.raises(RuntimeError, match="stop"):
            await run(_tg_settings(tmp_path), client, bot_client=bot)
    client.run_until_disconnected.assert_awaited_once()
    assert bot.start_calls == ["tok:SECRET"]


@pytest.mark.parametrize("me", [None, MagicMock(id=None, spec=["id"])])
async def test_remember_chat_without_user_id_is_harmless(
    me: object, caplog: pytest.LogCaptureFixture
) -> None:
    state, holder = _state_with_row(), ChatHolder(None)
    user = _user()
    user.get_me = AsyncMock(return_value=me)
    await remember_chat(user, holder, state)
    assert holder.current is None and state.get_chat_id() is None
    assert any(r.message == "get_me_failed" for r in caplog.records)


async def test_run_closes_bot_even_if_stop_offer_worker_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: Collector) -> None:
        raise OSError("stop failed")

    monkeypatch.setattr(Collector, "stop_offer_worker", boom)
    client = _client()
    client.get_me = AsyncMock(return_value=MagicMock(id=5))
    client.run_until_disconnected.side_effect = RuntimeError("stop")
    bot = FakeBotClient()
    with pytest.raises(OSError, match="stop failed"):
        await run(_tg_settings(tmp_path), client, bot_client=bot)
    assert bot.disconnects >= 1
