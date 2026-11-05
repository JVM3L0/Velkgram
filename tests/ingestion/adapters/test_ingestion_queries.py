import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from velkgram.ingestion import DailyCount, Heartbeat, MessageText
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.db import connect
from velkgram.shared.events import MessageData
from velkgram.shared.migrate import apply_migrations

D1 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
D2 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
T0 = D1


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, ["velkgram.shared", "velkgram.ingestion"])
    yield c
    c.close()


def _msg(channel_id: int, message_id: int, when: datetime, text: str = "t") -> MessageData:
    return MessageData(
        channel_id, message_id, when, when, text, (), None, None, None, False, "live"
    )


def _seed(conn: sqlite3.Connection) -> SqliteIngestionQueries:
    repo = SqliteMessageRepository(conn, FakeClock(T0))
    repo.add(_msg(1, 1, D1, "a"))
    repo.add(_msg(1, 2, D1 + timedelta(hours=1), "b"))
    repo.add(_msg(2, 1, D1, "c"))
    repo.add(_msg(1, 3, D2, "d"))
    repo.add(replace(_msg(1, 4, D2), date=D2 + timedelta(hours=14)))
    return SqliteIngestionQueries(conn)


def test_daily_counts_per_day_and_channel(conn: sqlite3.Connection) -> None:
    q = _seed(conn)
    assert q.daily_message_counts(date(2026, 11, 3), date(2026, 11, 4)) == [
        DailyCount(date(2026, 11, 3), 1, 2),
        DailyCount(date(2026, 11, 3), 2, 1),
        DailyCount(date(2026, 11, 4), 1, 1),
    ]
    assert q.daily_message_counts(date(2026, 11, 4), date(2026, 11, 4)) == [
        DailyCount(date(2026, 11, 4), 1, 1)
    ]


def test_daily_counts_use_utc_date_of_message_date(conn: sqlite3.Connection) -> None:
    q = _seed(conn)
    counts = q.daily_message_counts(date(2026, 11, 5), date(2026, 11, 5))
    assert counts == [DailyCount(date(2026, 11, 5), 1, 1)]


def test_texts_between_bounds(conn: sqlite3.Connection) -> None:
    q = _seed(conn)
    got = list(q.texts_between(date(2026, 11, 3), date(2026, 11, 3)))
    assert got == [
        MessageText(date(2026, 11, 3), 1, 1, "a"),
        MessageText(date(2026, 11, 3), 1, 2, "b"),
        MessageText(date(2026, 11, 3), 2, 1, "c"),
    ]
    both = list(q.texts_between(date(2026, 11, 4), date(2026, 11, 5)))
    assert [t.message_id for t in both] == [3, 4]
    assert list(q.texts_between(date(2026, 11, 6), date(2026, 11, 7))) == []


def test_heartbeat(conn: sqlite3.Connection) -> None:
    q = SqliteIngestionQueries(conn)
    assert q.heartbeat() is None
    hb = Heartbeat(D1, "reconnecting", None, 3, 1)
    SqliteMessageRepository(conn, FakeClock(T0)).write_heartbeat(hb)
    assert q.heartbeat() == hb


def test_last_message_at(conn: sqlite3.Connection) -> None:
    q = _seed(conn)
    got = q.last_message_at([1, 2, 3])
    assert got == {1: D2 + timedelta(hours=14), 2: D1}
    assert q.last_message_at([]) == {}
