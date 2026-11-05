"""Read-side port and view models for the offers feed and product pages."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from velkgram.offers.domain.models import CouponTier, MatchSource, OfferKind, ProductStats, RetroRun


@dataclass(frozen=True, slots=True)
class FeedFilter:
    q: str | None
    min_cents: int | None
    max_cents: int | None
    stores: tuple[str, ...]
    priced_only: bool
    channel_id: int | None


@dataclass(frozen=True, slots=True)
class CouponFilter:
    """Filters of the coupons page; `since` keeps only coupons posted at or after it."""

    q: str | None = None
    store: str | None = None
    since: datetime | None = None
    q_stores: tuple[str, ...] = ()
    """Store keys whose display name matched `q`, so a search by "mercado livre" finds them."""


@dataclass(frozen=True, slots=True)
class FeedCursor:
    posted_at: datetime
    channel_id: int
    message_id: int


@dataclass(frozen=True, slots=True)
class OfferCard:
    channel_id: int
    message_id: int
    posted_at: datetime
    title: str
    price_cents: int | None
    store: str | None
    main_link: str | None
    has_photo: bool
    sold_out: bool
    deleted: bool
    repost_count: int
    comparable: bool = True
    kind: OfferKind = OfferKind.product
    coupons: tuple[str, ...] = ()
    coupon_discount: str | None = None
    coupon_min_cents: int | None = None
    coupon_scope: str | None = None
    redeem_link: str | None = None
    cart_link: str | None = None
    text: str | None = None
    coupon_tiers: tuple[CouponTier, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedPage:
    cards: tuple[OfferCard, ...]
    next_cursor: FeedCursor | None


@dataclass(frozen=True, slots=True)
class PricePoint:
    posted_at: datetime
    price_cents: int


@dataclass(frozen=True, slots=True)
class MatchCard:
    card: OfferCard
    source: MatchSource
    matched_price_cents: int | None


@dataclass(frozen=True, slots=True)
class ProductHistory:
    stats: ProductStats
    points: tuple[PricePoint, ...]
    matches: tuple[MatchCard, ...]
    next_cursor: FeedCursor | None
    retro: RetroRun | None


@dataclass(frozen=True, slots=True)
class WishSummary:
    last_cents: int | None
    match_count: int
    recent_prices: tuple[int, ...]
    """The last 30 priced matches, oldest first."""


class OfferQueries(Protocol):
    def feed(self, f: FeedFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage: ...

    def active_coupons(
        self, now: datetime, hours: int = 6, limit: int = 12
    ) -> tuple[OfferCard, ...]:
        """Coupon offers posted in the last `hours`, newest first."""
        ...

    def coupons(self, f: CouponFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage:
        """Live (not deleted, not a repost) coupon offers, newest first."""
        ...

    def coupon_stores(self) -> list[str]:
        """Stores that have at least one live coupon, sorted."""
        ...

    def coupon_counts(self, now: datetime, hours: int = 24) -> dict[str, int]:
        """Live coupons posted in the last `hours`, by store (store-less offers are left out)."""
        ...

    def product(
        self,
        wish_id: int,
        now: datetime,
        range_days: int | None,
        cursor: FeedCursor | None,
        limit: int = 30,
    ) -> ProductHistory:
        """`range_days` limits only `points` (None = all time); stats use every match."""
        ...

    def summaries(self, wish_ids: Sequence[int]) -> dict[int, WishSummary]: ...

    def stores_seen(self) -> list[str]: ...
