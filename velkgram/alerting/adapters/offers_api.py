"""ActiveCoupons backed by the offers module's public query API."""

from datetime import datetime

from velkgram.alerting.domain.models import ActiveCoupon
from velkgram.offers import OfferQueries


class OffersActiveCoupons:
    def __init__(self, queries: OfferQueries) -> None:
        self._queries = queries

    def for_store(
        self,
        store: str,
        since: datetime,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
    ) -> list[ActiveCoupon]:
        return [
            ActiveCoupon(
                channel_id=v.channel_id,
                message_id=v.message_id,
                posted_at=v.posted_at,
                discount=v.discount,
                min_cents=v.min_cents,
                codes=v.codes,
            )
            for v in self._queries.active_coupons(store, since, price_cents, exclude)
        ]
