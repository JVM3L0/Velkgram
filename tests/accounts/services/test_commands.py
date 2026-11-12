from datetime import UTC, datetime

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import InMemoryUserRepository
from velkgram.accounts import InvalidUser, Role, UserCommands, ensure_admin

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _hash(pw: str) -> str:
    return f"h({pw})"


def _verify(stored: str, pw: str) -> bool:
    return stored == _hash(pw)


def _commands() -> tuple[UserCommands, InMemoryUserRepository]:
    repo = InMemoryUserRepository()
    return UserCommands(repo, FakeClock(NOW), _hash, _verify), repo


def test_create_stores_a_hashed_password_and_the_role() -> None:
    cmd, repo = _commands()
    user = cmd.create("Ana", "senha-forte", Role.USER)
    assert user.id is not None
    stored = repo.get(user.id)
    assert stored is not None
    assert (stored.username, stored.role, stored.enabled) == ("Ana", Role.USER, True)
    assert stored.password_hash == "h(senha-forte)"
    assert stored.created_at == NOW


def test_create_rejects_a_duplicate_username_ignoring_case() -> None:
    cmd, _ = _commands()
    cmd.create("Ana", "senha-forte", Role.USER)
    with pytest.raises(InvalidUser, match="já existe"):
        cmd.create("ana", "outra-senha", Role.USER)


def test_create_validates_name_and_password() -> None:
    cmd, _ = _commands()
    with pytest.raises(InvalidUser):
        cmd.create("a", "senha-forte", Role.USER)
    with pytest.raises(InvalidUser):
        cmd.create("ana", "curta", Role.USER)


def test_authenticate_accepts_the_right_password_ignoring_username_case() -> None:
    cmd, _ = _commands()
    created = cmd.create("Ana", "senha-forte", Role.USER)
    found = cmd.authenticate("ANA", "senha-forte")
    assert found is not None and found.id == created.id


def test_authenticate_refuses_wrong_unknown_disabled_and_passwordless_users() -> None:
    cmd, repo = _commands()
    ana = cmd.create("Ana", "senha-forte", Role.USER)
    assert cmd.authenticate("Ana", "errada!!") is None
    assert cmd.authenticate("ninguem", "senha-forte") is None
    cmd.set_enabled(ana.id or 0, False)
    assert cmd.authenticate("Ana", "senha-forte") is None
    admin = repo.add_admin_without_password()
    assert cmd.authenticate(admin.username, "") is None  # '' hash can never log in


def test_set_password_replaces_the_hash() -> None:
    cmd, _ = _commands()
    ana = cmd.create("Ana", "senha-forte", Role.USER)
    cmd.set_password(ana.id or 0, "nova-senha-1")
    assert cmd.authenticate("Ana", "senha-forte") is None
    assert cmd.authenticate("Ana", "nova-senha-1") is not None


def test_set_chat_id_stores_and_clears() -> None:
    cmd, repo = _commands()
    ana = cmd.create("Ana", "senha-forte", Role.USER)
    cmd.set_chat_id(ana.id or 0, 123456)
    assert repo.get(ana.id or 0).telegram_chat_id == 123456  # type: ignore[union-attr]
    cmd.set_chat_id(ana.id or 0, None)
    assert repo.get(ana.id or 0).telegram_chat_id is None  # type: ignore[union-attr]


def test_the_last_enabled_admin_cannot_be_disabled() -> None:
    cmd, repo = _commands()
    admin = repo.add_admin_without_password()
    with pytest.raises(InvalidUser, match="administrador"):
        cmd.set_enabled(admin.id or 0, False)
    cmd.create("Bia", "senha-forte", Role.ADMIN)
    cmd.set_enabled(admin.id or 0, False)  # another admin exists now


def test_ensure_admin_fills_only_what_is_missing() -> None:
    _, repo = _commands()
    admin = repo.add_admin_without_password()
    ensure_admin(repo, password_hash="scrypt$x", chat_id=42)
    stored = repo.get(admin.id or 0)
    assert stored is not None
    assert (stored.password_hash, stored.telegram_chat_id) == ("scrypt$x", 42)
    ensure_admin(repo, password_hash="scrypt$other", chat_id=99)  # never overwrites
    again = repo.get(admin.id or 0)
    assert again is not None
    assert (again.password_hash, again.telegram_chat_id) == ("scrypt$x", 42)


def test_ensure_admin_ignores_missing_values() -> None:
    _, repo = _commands()
    admin = repo.add_admin_without_password()
    ensure_admin(repo, password_hash=None, chat_id=None)
    stored = repo.get(admin.id or 0)
    assert stored is not None and stored.password_hash == ""
