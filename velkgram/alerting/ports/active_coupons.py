"""Read-side view of live store coupons used by the evaluator."""

from datetime import datetime
from typing import Protocol

from velkgram.alerting.domain.models import ActiveCoupon


class ActiveCoupons(Protocol):
    def for_store(
        self,
        store: str,
        since: datetime,
        price_cents: int | None,
        exclude: tuple[int, int] | None,
    ) -> list[ActiveCoupon]:
        """Newest first, at most a few. Synchronous and cheap; may raise."""
        ...
