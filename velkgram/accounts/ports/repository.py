"""User persistence port."""

from typing import Protocol

from velkgram.accounts.domain.models import User


class UserRepository(Protocol):
    def add(self, u: User) -> User:
        """Store a new user; ValueError when the username (case-insensitive) is taken."""
        ...

    def update(self, u: User) -> None: ...

    def get(self, id: int) -> User | None: ...

    def get_by_username(self, username: str) -> User | None: ...

    def list_all(self) -> list[User]: ...
