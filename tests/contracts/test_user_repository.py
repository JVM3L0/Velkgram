from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fakes.repositories import InMemoryUserRepository
from velkgram.accounts import Role, User, UserRepository
from velkgram.accounts.adapters.sqlite.repository import SqliteUserRepository
from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _user(name: str = "ana", role: Role = Role.USER) -> User:
    return User(None, name, "scrypt$x", role, None, True, NOW)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[UserRepository]:
    if request.param == "memory":
        yield InMemoryUserRepository()
        return
    conn = connect(tmp_path / "t.db")
    apply_migrations(conn, MIGRATION_PACKAGES)
    yield SqliteUserRepository(conn)
    conn.close()


def test_add_assigns_an_id_and_get_returns_the_user(repo: UserRepository) -> None:
    stored = repo.add(_user())
    assert stored.id is not None
    assert repo.get(stored.id) == stored
    assert repo.get(99999) is None


def test_get_by_username_ignores_case(repo: UserRepository) -> None:
    stored = repo.add(_user("Ana"))
    assert repo.get_by_username("ana") == stored
    assert repo.get_by_username("ANA") == stored
    assert repo.get_by_username("bia") is None


def test_add_rejects_a_duplicate_username_ignoring_case(repo: UserRepository) -> None:
    repo.add(_user("Ana"))
    with pytest.raises(ValueError, match="username"):
        repo.add(_user("ana"))


def test_update_changes_every_mutable_field(repo: UserRepository) -> None:
    from dataclasses import replace

    stored = repo.add(_user())
    changed = replace(stored, password_hash="scrypt$y", telegram_chat_id=7, enabled=False)
    repo.update(changed)
    assert repo.get(stored.id or 0) == changed


def test_list_all_is_ordered_by_id_and_count_matches(repo: UserRepository) -> None:
    base = len(repo.list_all())
    a = repo.add(_user("ana"))
    b = repo.add(_user("bia", Role.ADMIN))
    users = repo.list_all()
    assert [u.id for u in users][-2:] == [a.id, b.id]
    assert len(users) == base + 2
