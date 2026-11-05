import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from tests.apps.test_collector_assembly import CH, Env
from tests.fakes.messages import msg
from velkgram.apps.collector import collector as collector_module
from velkgram.shared.events import MessageDeleted, WishlistChanged


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


async def test_wait_idle_returns_with_worker_running(env: Env) -> None:
    env.channel()
    await env.collector.start()
    await asyncio.wait_for(env.collector.wait_idle(), timeout=2)


async def test_collector_builds_offer_after_alert(env: Env) -> None:
    env.channel()
    env.wish()
    await env.collector.start()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado mecanico R$ 200"))
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("alerts", "status='sent'") == 1
    assert env.count("offers") == 1
    assert env.count("offer_matches") == 1


async def test_deleted_message_marks_offer(env: Env) -> None:
    env.channel()
    await env.collector.start()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado mecanico R$ 200"))
    await env.bus.publish(MessageDeleted(CH, (1,), env.clock.now()))
    await env.bus.drain()
    await env.collector.wait_idle()
    assert env.count("offers", "deleted=1") == 1


async def test_start_runs_retro_for_existing_wishes(env: Env) -> None:
    env.channel()
    await env.collector.start()
    await env.collector.ingestor.on_new(msg(1, CH, "Teclado mecanico R$ 200"))
    await env.bus.drain()
    await env.collector.wait_idle()
    env.wish()
    second = env.build()
    await second.start()
    await second.wait_idle()
    assert env.count("offer_matches") == 1


async def test_wishlist_changed_during_run_still_calls_retro(env: Env) -> None:
    env.channel()
    await env.collector.start()
    await env.collector.wait_idle()
    calls = 0
    release = asyncio.Event()

    async def slow(_e: WishlistChanged) -> None:
        nonlocal calls
        calls += 1
        await release.wait()

    env.collector.retro.on_wishlist_changed = slow  # type: ignore[method-assign]
    await env.bus.publish(WishlistChanged(1))
    await env.bus.drain()
    for _ in range(5):
        await asyncio.sleep(0)
    assert calls == 1  # run in flight
    await env.bus.publish(WishlistChanged(2))
    await env.bus.drain()
    for _ in range(5):
        await asyncio.sleep(0)
    assert calls == 2
    release.set()
    await env.collector.wait_idle()


async def test_retention_runs_both_purges_and_isolates_failures(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def failing(_repo: object, cutoff: object) -> int:
        seen.append(("messages", cutoff))
        raise RuntimeError("boom")

    def offers(_repo: object, cutoff: object) -> int:
        seen.append(("offers", cutoff))
        return 3

    monkeypatch.setattr(collector_module, "purge_text_before", failing)
    monkeypatch.setattr(collector_module, "purge_offer_text_before", offers)
    await env.collector.run_retention()
    cutoff = env.clock.now() - timedelta(days=90)
    assert seen == [("messages", cutoff), ("offers", cutoff)]


async def test_housekeeping_runs_retention_once_per_day(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = 0

    async def fake() -> None:
        nonlocal runs
        runs += 1

    monkeypatch.setattr(env.collector, "run_retention", fake)
    # NOW is 12:00 UTC = 09:00 in Sao Paulo, past 04:00.
    await env.collector.housekeeping_tick()
    await env.collector.housekeeping_tick()
    assert runs == 1
