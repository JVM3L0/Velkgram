"""Is the current price low, normal or high for the selected period (pure)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

MIN_POINTS = 3
_BAND_PERCENT = 5  # within ±5 % of the average counts as "na média"


class PriceVerdict(StrEnum):
    below = "below"
    average = "average"
    above = "above"
    unknown = "unknown"


@dataclass(frozen=True, slots=True)
class PriceInsight:
    verdict: PriceVerdict
    average_cents: int | None


def price_insight(current_cents: int | None, history_cents: Sequence[int]) -> PriceInsight:
    """Compare `current_cents` with the average of the comparable prices in the period."""
    if current_cents is None or len(history_cents) < MIN_POINTS:
        return PriceInsight(PriceVerdict.unknown, None)
    total, count = sum(history_cents), len(history_cents)
    average = int((Decimal(total) / count).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    # Integer cross-multiplication keeps the ±5 % edges exact.
    scaled = current_cents * count * 100
    if scaled < total * (100 - _BAND_PERCENT):
        verdict = PriceVerdict.below
    elif scaled > total * (100 + _BAND_PERCENT):
        verdict = PriceVerdict.above
    else:
        verdict = PriceVerdict.average
    return PriceInsight(verdict, average)
