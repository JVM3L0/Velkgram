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


class AlertKind(StrEnum):
    offer = "offer"
    coupon = "coupon"


class SuppressionRule(StrEnum):
    origin = "origin"
    wish_price = "wish_price"
    wish_text = "wish_text"
    wish_coupon = "wish_coupon"


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
    kind: AlertKind = AlertKind.offer
    over_max: bool = False
    offer_channel_id: int | None = None
    offer_message_id: int | None = None
    payload: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveCoupon:
    """A live store coupon as it applies to a price (alerting's own view of an offers coupon)."""

    channel_id: int
    message_id: int
    posted_at: datetime
    discount: str
    min_cents: int | None
    codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlertMessage:
    wish_name: str
    text: str
    price_cents: int | None
    channel_name: str
    link: str | None
    delayed_minutes: int | None
    rendered: str | None = None  # final text (coupon alerts); format_alert returns it verbatim
    coupon_lines: tuple[str, ...] = ()  # active store coupons, already formatted
    over_max_cents: int | None = None  # set on above-max alerts: the wish max, for the suffix
