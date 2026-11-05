from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.fakes.clock import FakeClock
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.offers import SourceMessage
from velkgram.offers.adapters.ingestion_api import IngestionApiMessageSource
from velkgram.shared.db import connect
from velkgram.shared.events import MessageData
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _msg(message_id: int, text: str) -> MessageData:
    return MessageData(1, message_id, T0, T0, text, (), None, None, None, False, "live")


def test_ingestion_api_maps_stored_messages(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.ingestion"])
    repo = SqliteMessageRepository(conn, FakeClock(T0))
    repo.add(_msg(1, "um"))
    repo.add(_msg(2, "dois"))
    repo.add_version(_msg(2, "esgotado"), T0 + timedelta(minutes=1), True)
    repo.mark_deleted(1, [1], T0)
    got = list(IngestionApiMessageSource(SqliteIngestionQueries(conn)).iter_messages())
    assert got == [
        SourceMessage(_msg(1, "um"), deleted=True, sold_out=False),
        SourceMessage(_msg(2, "esgotado"), deleted=False, sold_out=True),
    ]
    conn.close()
