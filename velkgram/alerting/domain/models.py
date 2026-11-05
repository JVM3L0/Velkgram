"""Alerting domain models (pure data)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from velkgram.shared.deals import WishView as WishView


class AlertStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    expired = "expired"


class SuppressionRule(StrEnum):
    origin = "origin"
    wish_price = "wish_price"
    wish_text = "wish_text"


@dataclass(frozen=True, slots=True)
class Alert:
    id: int | None
    wish_id: int
    channel_id: int
    message_id: int
    price_cents: int | None
    price_unknown: bool
    dedup_keys: tuple[str, ...]
    status: AlertStatus
    attempts: int
    delayed_minutes: int | None
    created_at: datetime
    sent_at: datetime | None
    latency_telegram_ms: int
    latency_internal_ms: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class AlertMessage:
    wish_name: str
    text: str
    price_cents: int | None
    channel_name: str
    link: str | None
    delayed_minutes: int | None
