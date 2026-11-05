import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryChannelRepository
from velkgram.channels import Channel, ChannelRepository, ChannelStatus
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.shared.db import connect, read_versions
from velkgram.shared.migrate import apply_migrations

CREATED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass
class RepoHandle:
    repo: ChannelRepository
    version: Callable[[], int]
    conn: sqlite3.Connection | None = None


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[RepoHandle]:
    if request.param == "memory":
        fake = InMemoryChannelRepository()
        yield RepoHandle(fake, lambda: fake.version)
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.channels"])
    yield RepoHandle(
        SqliteChannelRepository(conn), lambda: read_versions(conn).get("channels", 0), conn
    )
    conn.close()


def _channel(ref: str = "@promotech", enabled: bool = True) -> Channel:
    return Channel(None, ref, None, None, ChannelStatus.PENDING, None, enabled, 12, CREATED)


def test_round_trip(handle: RepoHandle) -> None:
    stored = handle.repo.add(_channel())
    assert stored.id is not None
    assert stored == replace(_channel(), id=stored.id)
    assert handle.repo.get(stored.id) == stored
    assert handle.repo.get_by_ref("@promotech") == stored
    assert handle.repo.get_by_ref("@other") is None
    assert handle.repo.list_all() == [stored]
    assert handle.repo.get(stored.id + 1) is None


def test_update_persists_resolution(handle: RepoHandle) -> None:
    stored = handle.repo.add(_channel())
    changed = replace(
        stored,
        telegram_id=-1001234,
        name="Promo",
        status=ChannelStatus.ACTIVE,
        silent_after_hours=6,
    )
    handle.repo.update(changed)
    assert handle.repo.get(stored.id or 0) == changed


def test_update_persists_error(handle: RepoHandle) -> None:
    stored = handle.repo.add(_channel())
    changed = replace(stored, status=ChannelStatus.ERROR, error="Flood wait")
    handle.repo.update(changed)
    assert handle.repo.get(stored.id or 0) == changed


def test_list_pending(handle: RepoHandle) -> None:
    pending = handle.repo.add(_channel("@a_pending"))
    active = handle.repo.add(_channel("@b_active"))
    failed = handle.repo.add(_channel("@c_failed"))
    handle.repo.update(replace(active, status=ChannelStatus.ACTIVE, telegram_id=-1001))
    handle.repo.update(replace(failed, status=ChannelStatus.ERROR, error="x"))
    assert handle.repo.list_pending() == [pending]


def test_list_enabled_active(handle: RepoHandle) -> None:
    on = handle.repo.add(_channel("@on_active"))
    off = handle.repo.add(_channel("@off_active"))
    handle.repo.add(_channel("@still_pending"))
    on = replace(on, status=ChannelStatus.ACTIVE, telegram_id=-1001, name="On")
    handle.repo.update(on)
    handle.repo.update(replace(off, status=ChannelStatus.ACTIVE, telegram_id=-1002, enabled=False))
    assert handle.repo.list_enabled_active() == [on]
    assert len(handle.repo.list_all()) == 3


def test_delete(handle: RepoHandle) -> None:
    stored = handle.repo.add(_channel())
    assert stored.id is not None
    handle.repo.delete(stored.id)
    assert handle.repo.get(stored.id) is None
    assert handle.repo.list_all() == []


def test_duplicate_ref_rejected_by_sqlite(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.channels"])
    repo = SqliteChannelRepository(conn)
    repo.add(_channel())
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_channel())
    assert len(repo.list_all()) == 1
    assert read_versions(conn)["channels"] == 1
    conn.close()


def test_every_write_bumps_version(handle: RepoHandle) -> None:
    assert handle.version() == 0
    stored = handle.repo.add(_channel())
    assert handle.version() == 1
    handle.repo.update(replace(stored, enabled=False))
    assert handle.version() == 2
    handle.repo.delete(stored.id or 0)
    assert handle.version() == 3


def test_failed_write_does_not_bump_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.channels"])
    repo = SqliteChannelRepository(conn)
    repo.add(_channel())
    conn.execute("DROP TABLE state_versions")
    conn.execute(
        "CREATE TABLE state_versions (name TEXT PRIMARY KEY, version INTEGER NOT NULL "
        "CHECK (version < 0))"
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_channel("@second"))
    assert len(repo.list_all()) == 1  # insert rolled back with the failed bump
    assert not conn.in_transaction
    conn.close()
