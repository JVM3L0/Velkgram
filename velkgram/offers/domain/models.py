"""Offers domain models (plain data)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MatchSource(StrEnum):
    live = "live"
    retro = "retro"


class RetroStatus(StrEnum):
    running = "running"
    done = "done"
    failed = "failed"


@dataclass(frozen=True, slots=True)
class Offer:
    channel_id: int
    message_id: int
    posted_at: datetime
    title: str
    price_cents: int | None
    store: str | None
    main_link: str | None
    has_photo: bool
    text: str | None
    norm_text: str | None
    origin_channel_id: int | None
    origin_message_id: int | None
    sold_out: bool
    deleted: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OfferMatch:
    wish_id: int
    channel_id: int
    message_id: int
    price_cents: int | None
    posted_at: datetime
    source: MatchSource
    matched_at: datetime


@dataclass(frozen=True, slots=True)
class RetroRun:
    wish_id: int
    fingerprint: str
    status: RetroStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ProductStats:
    lowest_cents: int | None
    avg_30d_cents: int | None
    last_cents: int | None
    match_count: int
