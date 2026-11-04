import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryMessageRepository
from velkgram.ingestion import Heartbeat, MessageRepository
from velkgram.ingestion.adapters.sqlite.repository import SqliteMessageRepository
from velkgram.shared.db import connect, read_versions
from velkgram.shared.events import MessageData
from velkgram.shared.migrate import apply_migrations

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass
class RepoHandle:
    repo: MessageRepository
    conn: sqlite3.Connection | None = None


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[RepoHandle]:
    if request.param == "memory":
        yield RepoHandle(InMemoryMessageRepository())
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.ingestion"])
    yield RepoHandle(SqliteMessageRepository(conn), conn)
    conn.close()


def _msg(message_id: int = 1, channel_id: int = 100, **kw: object) -> MessageData:
    base = MessageData(
        channel_id=channel_id,
        message_id=message_id,
        date=T0,
        received_at=T0 + timedelta(seconds=2),
        text="SSD 1TB R$ 300 https://x.com/a",
        links=("https://x.com/a",),
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=False,
        source="live",
    )
    return replace(base, **kw)


def test_add_round_trip_and_idempotent(handle: RepoHandle) -> None:
    m = _msg(fwd_from_channel_id=5, fwd_from_message_id=6, grouped_id=7, has_photo=True)
    assert handle.repo.add(m) is True
    assert handle.repo.get(100, 1) == m
    assert handle.repo.add(replace(m, text="other")) is False
    assert handle.repo.get(100, 1) == m
    assert handle.repo.get(100, 2) is None


def test_backfill_source_round_trips(handle: RepoHandle) -> None:
    m = _msg(source="backfill")
    handle.repo.add(m)
    assert handle.repo.get(100, 1) == m


def test_versions_increment_per_message(handle: RepoHandle) -> None:
    handle.repo.add(_msg(1))
    handle.repo.add(_msg(2))
    m1 = _msg(1)
    assert handle.repo.add_version(m1, T0, False) == 1
    assert handle.repo.add_version(m1, T0 + timedelta(minutes=1), True) == 2
    assert handle.repo.add_version(_msg(2), T0, False) == 1


def test_mark_deleted_keeps_row(handle: RepoHandle) -> None:
    handle.repo.add(_msg(1))
    handle.repo.add(_msg(2))
    handle.repo.mark_deleted(100, [1, 99], T0)
    assert handle.repo.get(100, 1) == _msg(1)
    assert handle.repo.get(100, 2) == _msg(2)


def test_unprocessed_filters_on_received_at(handle: RepoHandle) -> None:
    old = _msg(1, received_at=T0 - timedelta(hours=1))
    recent = _msg(2, received_at=T0)
    done = _msg(3, received_at=T0 + timedelta(minutes=1))
    pending = _msg(4, received_at=T0 + timedelta(minutes=2))
    for m in (old, recent, done, pending):
        handle.repo.add(m)
    handle.repo.mark_processed(100, 3, T0 + timedelta(minutes=3))
    assert handle.repo.list_unprocessed_since(T0) == [recent, pending]


def test_unprocessed_returns_original_text_after_edit(handle: RepoHandle) -> None:
    m = _msg(1)
    handle.repo.add(m)
    handle.repo.add_version(replace(m, text="esgotado"), T0, True)
    assert handle.repo.list_unprocessed_since(T0) == [m]


def test_cursor_is_monotonic(handle: RepoHandle) -> None:
    assert handle.repo.get_cursor(100) is None
    handle.repo.set_cursor(100, 10)
    handle.repo.set_cursor(100, 5)
    assert handle.repo.get_cursor(100) == 10
    handle.repo.set_cursor(100, 11)
    assert handle.repo.get_cursor(100) == 11
    assert handle.repo.get_cursor(200) is None


def test_heartbeat_round_trip(handle: RepoHandle) -> None:
    assert handle.repo.read_heartbeat() is None
    first = Heartbeat(T0, "connected", None, 10, 2)
    handle.repo.write_heartbeat(first)
    assert handle.repo.read_heartbeat() == first
    fatal = Heartbeat(T0 + timedelta(seconds=30), "fatal", "banned", 11, 2)
    handle.repo.write_heartbeat(fatal)
    assert handle.repo.read_heartbeat() == fatal


def test_message_writes_do_not_bump_state_versions(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.ingestion"])
    repo = SqliteMessageRepository(conn)
    before = read_versions(conn)
    repo.add(_msg(1))
    repo.add_version(_msg(1), T0, False)
    repo.mark_deleted(100, [1], T0)
    repo.mark_processed(100, 1, T0)
    repo.set_cursor(100, 1)
    assert read_versions(conn) == before
