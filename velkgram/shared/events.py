"""Plain-data events shared by every module."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class MessageData:
    channel_id: int  # telegram_id
    message_id: int
    date: datetime
    received_at: datetime
    text: str
    links: tuple[str, ...]
    fwd_from_channel_id: int | None
    fwd_from_message_id: int | None
    grouped_id: int | None
    has_photo: bool
    source: Literal["live", "backfill"]


@dataclass(frozen=True, slots=True)
class MessageReceived:
    message: MessageData


@dataclass(frozen=True, slots=True)
class MessageEdited:
    message: MessageData
    version: int
    edited_at: datetime
    sold_out_hint: bool


@dataclass(frozen=True, slots=True)
class MessageDeleted:
    channel_id: int
    message_ids: tuple[int, ...]
    deleted_at: datetime


@dataclass(frozen=True, slots=True)
class AlertTriggered:
    alert_id: int
    wish_id: int
    channel_id: int
    message_id: int
    status: str


@dataclass(frozen=True, slots=True)
class WishlistChanged:
    version: int


@dataclass(frozen=True, slots=True)
class ChannelsChanged:
    version: int


Event = (
    MessageReceived
    | MessageEdited
    | MessageDeleted
    | AlertTriggered
    | WishlistChanged
    | ChannelsChanged
)
