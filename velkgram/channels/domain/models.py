"""Channel model and reference parsing."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_INVALID_PT = "Use @canal ou um link t.me"
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
_INVITE_HASH = re.compile(r"[A-Za-z0-9_-]+")
_LINK_PREFIX = re.compile(r"(?:https?://)?(?:www\.)?t\.me/", re.IGNORECASE)


class InvalidChannel(ValueError):
    def __init__(self, message_pt: str) -> None:
        super().__init__(message_pt)
        self.message_pt = message_pt


class ChannelStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Channel:
    id: int | None
    ref: str
    telegram_id: int | None
    name: str | None
    status: ChannelStatus
    error: str | None
    enabled: bool
    silent_after_hours: int
    created_at: datetime


def parse_channel_ref(raw: str) -> str:
    """Normalize user input to `@username` or `+hash`; reject anything else."""
    text = raw.strip()
    link = _LINK_PREFIX.match(text)
    if link:
        path = text[link.end() :].split("?", 1)[0].strip("/")
        if path.startswith("joinchat/"):
            return _invite(path.removeprefix("joinchat/"))
        if path.startswith("+"):
            return _invite(path[1:])
        return _username(path)
    return _username(text.removeprefix("@"))


def _username(name: str) -> str:
    if not _USERNAME.fullmatch(name):
        raise InvalidChannel(_INVALID_PT)
    return f"@{name}"


def _invite(code: str) -> str:
    if not _INVITE_HASH.fullmatch(code):
        raise InvalidChannel(_INVALID_PT)
    return f"+{code}"
