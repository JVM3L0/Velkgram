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
    stores: tuple[str, ...] = ()
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
    image_url: str | None = None
    seen_channel_ids: tuple[int, ...] = ()
    """Channels that posted this product at this price within 24 h (feed collapse); newest first."""


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
    other_product: bool = False


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


@dataclass(frozen=True, slots=True)
class ActiveCouponView:
    """A live coupon as it applies to a price: tier-level discount, minimum and codes."""

    channel_id: int
    message_id: int
    posted_at: datetime
    discount: str
    min_cents: int | None
    codes: tuple[str, ...]


class OfferQueries(Protocol):
    def feed(self, f: FeedFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage: ...

    def coupons(self, f: CouponFilter, cursor: FeedCursor | None, limit: int = 30) -> FeedPage:
        """Live (not deleted, not a repost) coupon offers, newest first."""
        ...

    def count_feed_after(self, f: FeedFilter, since: FeedCursor) -> int:
        """Feed rows strictly newer than `since` (same ordering as `feed`) under the filters."""
        ...

    def count_coupons_after(self, f: CouponFilter, since: FeedCursor) -> int:
        """Coupon rows strictly newer than `since` under the filters."""
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

    def matches_page(
        self, wish_id: int, cursor: FeedCursor | None, limit: int = 30
    ) -> tuple[tuple[MatchCard, ...], FeedCursor | None]:
        """One page of a wish's matches, newest first: no stats, no price points."""
        ...

    def summaries(self, wish_ids: Sequence[int]) -> dict[int, WishSummary]: ...

    def active_coupons(
        self,
        store: str,
        since: datetime,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
        limit: int = 3,
    ) -> list[ActiveCouponView]:
        """Newest live coupons of `store` posted since `since` that have codes.

        With `price_cents`, only coupons whose applicable tier the price reaches, described by
        that tier; the limit applies after that filter.
        """
        ...

    def stores_seen(self) -> list[str]: ...
