from dataclasses import replace
from datetime import UTC, datetime, timedelta

from tests.fakes.repositories import InMemoryMessageRepository
from velkgram.ingestion import purge_text_before
from velkgram.shared.events import MessageData

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def test_retention_service_returns_count() -> None:
    repo = InMemoryMessageRepository()
    base = MessageData(1, 1, T0, T0, "t", (), None, None, None, False, "live")
    repo.add(replace(base, date=T0 - timedelta(days=100)))
    repo.add(replace(base, message_id=2, date=T0 - timedelta(days=95)))
    repo.add(replace(base, message_id=3))
    assert purge_text_before(repo, T0 - timedelta(days=90)) == 2
    assert purge_text_before(repo, T0 - timedelta(days=90)) == 0
