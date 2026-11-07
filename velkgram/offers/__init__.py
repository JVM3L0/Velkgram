"""Offers module public API (the SQLite adapters are wired by the apps)."""

from velkgram.offers.domain.build import MessageClass, classify_message
from velkgram.offers.domain.models import MatchSource
from velkgram.offers.domain.title import split_title, store_title
from velkgram.offers.ports.fetcher import HostPaused
from velkgram.offers.ports.links import EnrichHeartbeat, LinkRepository, LinkRow
from velkgram.offers.ports.messages import MessageSource, SourceMessage
from velkgram.offers.ports.queries import (
    ActiveCouponView,
    CouponFilter,
    FeedCursor,
    FeedFilter,
    FeedPage,
    MatchCard,
    OfferCard,
    OfferQueries,
    PricePoint,
    ProductHistory,
    WishSummary,
)
from velkgram.offers.ports.repository import OfferRepository
from velkgram.offers.ports.wishes import WishReader
from velkgram.offers.services.build_offer import OfferBuilder
from velkgram.offers.services.enrich import LinkEnricher
from velkgram.offers.services.rebuild import rebuild_offers
from velkgram.offers.services.retention import purge_offer_text_before
from velkgram.offers.services.retro_match import RetroMatcher
from velkgram.offers.web.chart import sparkline_svg

__all__ = [
    "ActiveCouponView",
    "CouponFilter",
    "EnrichHeartbeat",
    "FeedCursor",
    "FeedFilter",
    "FeedPage",
    "HostPaused",
    "LinkEnricher",
    "LinkRepository",
    "LinkRow",
    "MatchCard",
    "MatchSource",
    "MessageClass",
    "MessageSource",
    "OfferBuilder",
    "OfferCard",
    "OfferQueries",
    "OfferRepository",
    "PricePoint",
    "ProductHistory",
    "RetroMatcher",
    "SourceMessage",
    "WishReader",
    "WishSummary",
    "classify_message",
    "purge_offer_text_before",
    "rebuild_offers",
    "sparkline_svg",
    "split_title",
    "store_title",
]
