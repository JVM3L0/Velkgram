"""The lowest price of a product across stores over time (pure)."""

from collections.abc import Sequence
from datetime import datetime, timedelta

CURRENT_WINDOW_DAYS = 14  # a store's price counts as current for this long
Offer = tuple[datetime, int, str]  # (posted_at, price_cents, store)


def daily_lowest(offers: Sequence[Offer], since: datetime | None) -> list[tuple[datetime, int]]:
    """The cheapest offer of each (UTC) day, any store, oldest first: "menor preço do dia"."""
    best: dict[str, tuple[datetime, int]] = {}
    for posted_at, price, _store in offers:
        if since is not None and posted_at < since:
            continue
        day = posted_at.date().isoformat()
        if day not in best or price < best[day][1]:
            best[day] = (posted_at, price)
    return sorted(best.values())


def current_lowest(offers: Sequence[Offer], now: datetime, window_days: int) -> int | None:
    """The cheapest of each store's latest price within the window; else the latest price seen."""
    if not offers:
        return None
    latest: dict[str, tuple[datetime, int]] = {}
    for posted_at, price, store in sorted(offers):
        latest[store] = (posted_at, price)
    cutoff = now - timedelta(days=window_days)
    recent = [price for posted_at, price in latest.values() if posted_at >= cutoff]
    if recent:
        return min(recent)
    return max(latest.values())[1]
