import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from velkgram.ingestion import StoredMessage
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.db import connect
from velkgram.shared.events import MessageData
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, ["velkgram.shared", "velkgram.ingestion"])
    yield c
    c.close()


def _msg(channel_id: int, message_id: int, when: datetime = T0, text: str = "t") -> MessageData:
    return MessageData(
        channel_id,
        message_id,
        when,
        when,
        text,
        ("https://x.com/a",),
        None,
        None,
        None,
        False,
        "live",
    )


def test_iter_stored_uses_latest_version_text(conn: sqlite3.Connection) -> None:
    repo = SqliteMessageRepository(conn, FakeClock(T0))
    m = _msg(1, 1, text="original")
    repo.add(m)
    repo.add_version(_msg(1, 1, text="second"), T0, False)
    edited = MessageData(
        1, 1, T0, T0, "third", ("https://y.com/b",), None, None, None, False, "live"
    )
    repo.add_version(edited, T0 + timedelta(minutes=1), False)
    [got] = list(SqliteIngestionQueries(conn).iter_stored_messages())
    assert got.message.text == "third"
    assert got.message.links == ("https://y.com/b",)
    assert got.message.date == T0


def test_iter_stored_flags_deleted_and_sold_out(conn: sqlite3.Connection) -> None:
    repo = SqliteMessageRepository(conn, FakeClock(T0))
    for i in (1, 2, 3):
        repo.add(_msg(1, i))
    repo.add_version(_msg(1, 2, text="esgotado"), T0, True)
    repo.add_version(_msg(1, 2, text="back"), T0, False)
    repo.mark_deleted(1, [3], T0)
    got = {s.message.message_id: s for s in SqliteIngestionQueries(conn).iter_stored_messages()}
    assert got[1] == StoredMessage(_msg(1, 1), deleted=False, sold_out=False)
    assert got[2].sold_out is True and got[2].deleted is False
    assert got[2].message.text == "back"
    assert got[3].deleted is True and got[3].sold_out is False


def test_iter_stored_batches_in_order(conn: sqlite3.Connection) -> None:
    repo = SqliteMessageRepository(conn, FakeClock(T0))
    keys = [(2, 1, 0), (1, 5, 0), (1, 2, 0), (3, 1, -1), (1, 9, 1)]
    for ch, mid, hours in keys:
        repo.add(_msg(ch, mid, T0 + timedelta(hours=hours)))
    got = [
        (s.message.channel_id, s.message.message_id)
        for s in SqliteIngestionQueries(conn).iter_stored_messages(batch_size=2)
    ]
    assert got == [(3, 1), (1, 2), (1, 5), (2, 1), (1, 9)]
