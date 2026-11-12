"""User accounts: the model and its validation rules."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,31}")
_PASSWORD_MIN = 8
_PASSWORD_MAX = 200


class InvalidUser(ValueError):
    def __init__(self, message_pt: str) -> None:
        super().__init__(message_pt)
        self.message_pt = message_pt


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True, slots=True)
class User:
    id: int | None
    username: str
    password_hash: str  # scrypt; '' means the account cannot log in yet
    role: Role
    telegram_chat_id: int | None
    enabled: bool
    created_at: datetime


def validate_username(raw: str) -> str:
    """The trimmed username, or InvalidUser (Portuguese message) when it is not acceptable."""
    name = raw.strip()
    if not _USERNAME.fullmatch(name):
        raise InvalidUser("Usuário: 3 a 32 letras, números, ponto, hífen ou sublinhado")
    return name


def validate_password(raw: str) -> None:
    if len(raw) < _PASSWORD_MIN:
        raise InvalidUser(f"A senha precisa de ao menos {_PASSWORD_MIN} caracteres")
    if len(raw) > _PASSWORD_MAX:
        raise InvalidUser("Senha longa demais")
