import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryWishRepository
from velkgram.shared.db import connect, read_versions
from velkgram.shared.migrate import apply_migrations
from velkgram.wishlist import Wish, WishRepository
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository


@dataclass
class RepoHandle:
    repo: WishRepository
    version: Callable[[], int]
    conn: sqlite3.Connection | None = None


@pytest.fixture(params=["memory", "sqlite"])
def handle(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[RepoHandle]:
    if request.param == "memory":
        fake = InMemoryWishRepository()
        yield RepoHandle(fake, lambda: fake.version)
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.wishlist"])
    yield RepoHandle(
        SqliteWishRepository(conn), lambda: read_versions(conn).get("wishlist", 0), conn
    )
    conn.close()


def _wish(name: str = "SSD", enabled: bool = True) -> Wish:
    return Wish(None, name, ("ssd|nvme", "2tb"), ("usado",), 30000, enabled)


def test_round_trip(handle: RepoHandle) -> None:
    stored = handle.repo.add(_wish())
    assert stored.id is not None
    assert handle.repo.get(stored.id) == stored
    assert stored == replace(_wish(), id=stored.id)
    assert handle.repo.list_all() == [stored]
    assert handle.repo.get(stored.id + 1) is None


def test_list_enabled_filters_disabled(handle: RepoHandle) -> None:
    on = handle.repo.add(_wish("on"))
    handle.repo.add(_wish("off", enabled=False))
    assert handle.repo.list_enabled() == [on]
    assert len(handle.repo.list_all()) == 2


def test_update(handle: RepoHandle) -> None:
    stored = handle.repo.add(_wish())
    changed = replace(stored, name="NVMe", max_price_cents=25000, enabled=False)
    handle.repo.update(changed)
    assert handle.repo.get(stored.id or 0) == changed


def test_delete(handle: RepoHandle) -> None:
    stored = handle.repo.add(_wish())
    assert stored.id is not None
    handle.repo.delete(stored.id)
    assert handle.repo.get(stored.id) is None
    assert handle.repo.list_all() == []


def test_every_write_bumps_version(handle: RepoHandle) -> None:
    assert handle.version() == 0
    stored = handle.repo.add(_wish())
    assert handle.version() == 1
    handle.repo.update(replace(stored, name="x"))
    assert handle.version() == 2
    handle.repo.delete(stored.id or 0)
    assert handle.version() == 3


def test_failed_write_does_not_bump_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, ["velkgram.shared", "velkgram.wishlist"])
    repo = SqliteWishRepository(conn)
    repo.add(_wish())
    conn.execute("DROP TABLE state_versions")
    conn.execute(
        "CREATE TABLE state_versions (name TEXT PRIMARY KEY, version INTEGER NOT NULL "
        "CHECK (version < 0))"
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(_wish("second"))
    assert len(repo.list_all()) == 1  # insert rolled back with the failed bump
    assert not conn.in_transaction
    conn.execute("DROP TABLE state_versions")
