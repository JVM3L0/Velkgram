import time
from datetime import datetime

from velkgram.alerting.domain.models import ActiveCoupon


class FakeActiveCoupons:
    """Programmable ActiveCoupons: returns `coupons`, optionally slow or failing; records calls."""

    def __init__(
        self,
        coupons: list[ActiveCoupon] | None = None,
        error: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.coupons = coupons or []
        self.error = error
        self.delay_s = delay_s
        self.calls: list[tuple[str, datetime, int | None, tuple[int, int] | None]] = []

    def for_store(
        self,
        store: str,
        since: datetime,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
    ) -> list[ActiveCoupon]:
        self.calls.append((store, since, price_cents, exclude))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        return list(self.coupons)
