from datetime import UTC, datetime

from tests.fakes.repositories import InMemoryUserRepository
from velkgram.accounts import Role, User
from velkgram.alerting.adapters.accounts_api import AccountsChatDirectory, active_user_ids

NOW = datetime(2026, 11, 12, tzinfo=UTC)


def _repo() -> InMemoryUserRepository:
    repo = InMemoryUserRepository()
    repo.add(User(None, "admin", "x", Role.ADMIN, None, True, NOW))  # id 1
    repo.add(User(None, "ana", "x", Role.USER, 222, True, NOW))  # id 2
    repo.add(User(None, "bia", "x", Role.USER, None, True, NOW))  # id 3
    repo.add(User(None, "cris", "x", Role.USER, 444, False, NOW))  # id 4, disabled
    return repo


def test_the_directory_returns_the_chat_of_an_enabled_user() -> None:
    directory = AccountsChatDirectory(_repo(), admin_fallback=lambda: None)
    assert directory.chat_id(2) == 222


def test_a_user_without_a_chat_or_unknown_or_disabled_has_none() -> None:
    directory = AccountsChatDirectory(_repo(), admin_fallback=lambda: 999)
    assert directory.chat_id(3) is None
    assert directory.chat_id(4) is None
    assert directory.chat_id(77) is None


def test_only_the_admin_falls_back_to_the_bot_chat() -> None:
    directory = AccountsChatDirectory(_repo(), admin_fallback=lambda: 999)
    assert directory.chat_id(1) == 999  # the owner keeps getting alerts without setting a chat


def test_the_admins_own_chat_wins_over_the_fallback() -> None:
    repo = _repo()
    admin = repo.get(1)
    assert admin is not None
    from dataclasses import replace

    repo.update(replace(admin, telegram_chat_id=111))
    assert AccountsChatDirectory(repo, admin_fallback=lambda: 999).chat_id(1) == 111


def test_active_user_ids_lists_only_enabled_users() -> None:
    assert active_user_ids(_repo())() == frozenset({1, 2, 3})
