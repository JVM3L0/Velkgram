"""Ports for post images read from the public web view of Telegram channels."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from velkgram.offers.domain.channel_page import PostImage


class PostImageRepository(Protocol):
    def upsert(self, channel_id: int, images: Sequence[PostImage], now: datetime) -> None: ...

    def get(self, channel_id: int, message_id: int) -> str | None: ...

    def purge_before(self, cutoff: datetime) -> int: ...


class ChannelPages(Protocol):
    def fetch(self, username: str) -> str | None:
        """The HTML of the channel's public web view, or None when it is not available."""
        ...


class PublicChannels(Protocol):
    def public_channels(self) -> list[tuple[int, str]]:
        """(telegram id, username) of every enabled, active channel that has a public name."""
        ...
