from datetime import UTC, datetime

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import InMemoryMessageRepository
from velkgram.ingestion.domain.models import Heartbeat
from velkgram.ingestion.services.heartbeat import HeartbeatWriter

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def test_beat_writes_full_heartbeat_with_counters() -> None:
    repo = InMemoryMessageRepository()
    w = HeartbeatWriter(repo, FakeClock(NOW))
    w.count_message()
    w.count_message()
    w.count_alert()
    w.beat("reconnecting")
    assert repo.read_heartbeat() == Heartbeat(NOW, "reconnecting", None, 2, 1)
    w.beat("fatal", "sessão revogada")
    assert repo.read_heartbeat() == Heartbeat(NOW, "fatal", "sessão revogada", 2, 1)
