"""Product stats from a wish's matches (pure)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from velkgram.offers.domain.models import ProductStats

_WINDOW = timedelta(days=30)


def product_stats(points: Sequence[tuple[datetime, int | None]], now: datetime) -> ProductStats:
    priced = [(at, cents) for at, cents in points if cents is not None]
    if not priced:
        return ProductStats(None, None, None, len(points))
    recent = [cents for at, cents in priced if at >= now - _WINDOW]
    avg = (
        int((Decimal(sum(recent)) / len(recent)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if recent
        else None
    )
    return ProductStats(
        lowest_cents=min(cents for _, cents in priced),
        avg_30d_cents=avg,
        last_cents=max(priced, key=lambda p: p[0])[1],
        match_count=len(points),
    )
