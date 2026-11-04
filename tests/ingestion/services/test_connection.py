from datetime import UTC, datetime

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import InMemoryMessageRepository
from velkgram.ingestion.services.connection import ConnectionWatcher
from velkgram.ingestion.services.heartbeat import HeartbeatWriter

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


async def test_watcher_marks_reconnecting_then_backfills_once_on_recovery() -> None:
    repo = InMemoryMessageRepository()
    state = {"up": True}
    recovered = 0

    async def on_recovered() -> None:
        nonlocal recovered
        recovered += 1

    w = ConnectionWatcher(lambda: state["up"], HeartbeatWriter(repo, FakeClock(NOW)), on_recovered)
    await w.tick()
    hb = repo.read_heartbeat()
    assert hb is not None and hb.connection_state == "connected"
    assert recovered == 0

    state["up"] = False
    await w.tick()
    await w.tick()
    hb = repo.read_heartbeat()
    assert hb is not None and hb.connection_state == "reconnecting"
    assert recovered == 0

    state["up"] = True
    await w.tick()
    await w.tick()
    hb = repo.read_heartbeat()
    assert hb is not None and hb.connection_state == "connected"
    assert recovered == 1
