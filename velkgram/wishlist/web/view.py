"""View models for the wishes list."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class WishCardStats:
    last_price_cents: int | None
    match_count: int
    sparkline_svg: str
    previous_price_cents: int | None = None
    """The comparable price before the last one, for the change indicator."""

    @property
    def delta_percent(self) -> int | None:
        """Signed whole-percent change since the previous price; None when it is 0 or unknown."""
        last, before = self.last_price_cents, self.previous_price_cents
        if last is None or before is None or before <= 0:
            return None
        pct = (Decimal(last - before) * 100 / before).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return int(pct) or None


def is_below_alert(last_price_cents: int | None, max_price_cents: int) -> bool:
    return last_price_cents is not None and last_price_cents <= max_price_cents


def format_brl(cents: int) -> str:
    """`R$ 1.299,90` for display."""
    whole = f"{cents // 100:,}".replace(",", ".")
    return f"R$ {whole},{cents % 100:02d}"
