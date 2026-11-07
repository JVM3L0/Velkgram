from datetime import timedelta
from typing import cast

from tests.fakes.messages import NOW
from velkgram.alerting.adapters.offers_api import OffersActiveCoupons
from velkgram.alerting.domain.models import ActiveCoupon
from velkgram.offers import ActiveCouponView, OfferQueries


class _Queries:
    def __init__(self) -> None:
        self.args: tuple[object, ...] = ()

    def active_coupons(
        self,
        store: str,
        since: object,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
        limit: int = 3,
    ) -> list[ActiveCouponView]:
        self.args = (store, since, price_cents, exclude, limit)
        return [ActiveCouponView(1, 2, NOW, "R$ 10 OFF", 4000, ("AAA", "BBB"), 3000)]


def test_adapter_forwards_the_query_and_maps_field_by_field() -> None:
    q = _Queries()
    since = NOW - timedelta(hours=24)
    out = OffersActiveCoupons(cast(OfferQueries, q)).for_store("shopee", since, 9900, (1, 9))
    assert q.args == ("shopee", since, 9900, (1, 9), 3)
    assert out == [ActiveCoupon(1, 2, NOW, "R$ 10 OFF", 4000, ("AAA", "BBB"), 3000)]
