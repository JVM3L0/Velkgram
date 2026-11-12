"""User use cases: create, authenticate and maintain accounts."""

from collections.abc import Callable
from dataclasses import replace

from velkgram.accounts.domain.models import (
    InvalidUser,
    Role,
    User,
    validate_password,
    validate_username,
)
from velkgram.accounts.ports.repository import UserRepository
from velkgram.shared.ports import Clock

_NOBODY = "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 86 + "=="


class UserCommands:
    def __init__(
        self,
        repo: UserRepository,
        clock: Clock,
        hash_password: Callable[[str], str],
        verify_password: Callable[[str, str], bool],
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._hash = hash_password
        self._verify = verify_password

    def create(self, username: str, password: str, role: Role) -> User:
        name = validate_username(username)
        validate_password(password)
        if self._repo.get_by_username(name) is not None:
            raise InvalidUser("Esse usuário já existe")
        return self._repo.add(
            User(None, name, self._hash(password), role, None, True, self._clock.now())
        )

    def authenticate(self, username: str, password: str) -> User | None:
        """The enabled user whose password matches, else None.

        An unknown user still pays one password check, so timing does not reveal who exists.
        """
        user = self._repo.get_by_username(username.strip())
        stored = user.password_hash if user is not None else _NOBODY
        matches = self._verify(stored, password)
        if user is None or not matches or not user.password_hash or not user.enabled:
            return None
        return user

    def set_password(self, user_id: int, password: str) -> None:
        validate_password(password)
        self._repo.update(replace(self._require(user_id), password_hash=self._hash(password)))

    def set_enabled(self, user_id: int, enabled: bool) -> None:
        user = self._require(user_id)
        if not enabled and user.role is Role.ADMIN and user.enabled:
            others = [
                u
                for u in self._repo.list_all()
                if u.role is Role.ADMIN and u.enabled and u.id != user_id
            ]
            if not others:
                raise InvalidUser("Mantenha ao menos um administrador ativo")
        self._repo.update(replace(user, enabled=enabled))

    def set_chat_id(self, user_id: int, chat_id: int | None) -> None:
        self._repo.update(replace(self._require(user_id), telegram_chat_id=chat_id))

    def _require(self, user_id: int) -> User:
        user = self._repo.get(user_id)
        if user is None:
            raise InvalidUser("Usuário não encontrado")
        return user


def ensure_admin(repo: UserRepository, *, password_hash: str | None, chat_id: int | None) -> None:
    """Fill the seeded admin from the environment, never overwriting what is already set."""
    admin = repo.get(1)
    if admin is None or admin.role is not Role.ADMIN:
        return
    updated = admin
    if not admin.password_hash and password_hash:
        updated = replace(updated, password_hash=password_hash)
    if admin.telegram_chat_id is None and chat_id is not None:
        updated = replace(updated, telegram_chat_id=chat_id)
    if updated is not admin:
        repo.update(updated)
