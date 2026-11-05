"""Stored-message source port used to rebuild offers."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from velkgram.shared.events import MessageData


@dataclass(frozen=True, slots=True)
class SourceMessage:
    message: MessageData
    deleted: bool
    sold_out: bool


class MessageSource(Protocol):
    def iter_messages(self) -> Iterator[SourceMessage]: ...
