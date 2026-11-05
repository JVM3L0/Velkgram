"""View models for the wishes list."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WishCardStats:
    last_price_cents: int | None
    match_count: int
    sparkline_svg: str


def format_brl(cents: int) -> str:
    """`R$ 1.299,90` for display."""
    whole = f"{cents // 100:,}".replace(",", ".")
    return f"R$ {whole},{cents % 100:02d}"
