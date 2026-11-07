"""Offer storage port."""

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Protocol

from velkgram.offers.domain.models import Offer, OfferMatch, OfferText, RetroRun


class OfferRepository(Protocol):
    def upsert(self, o: Offer) -> None: ...

    def get(self, channel_id: int, message_id: int) -> Offer | None: ...

    def mark_deleted(self, channel_id: int, message_ids: Sequence[int], at: datetime) -> None: ...

    def add_match(self, m: OfferMatch) -> bool:
        """False when the (wish, offer) match already exists."""
        ...

    def add_matches(self, ms: Sequence[OfferMatch]) -> int:
        """Insert a batch in one transaction, ignoring duplicates; return rows inserted."""
        ...

    def delete_matches(self, wish_id: int, since: datetime | None) -> int:
        """Delete all of the wish's matches, or only those with `posted_at >= since`."""
        ...

    def iter_offers_with_text(self, since: datetime, batch_size: int) -> Iterator[list[OfferText]]:
        """Non-deleted offers with `norm_text` since `since`, ordered by (posted_at, ids)."""
        ...

    def priced_points(
        self, wish_id: int, dominant: tuple[str, str] | None = None
    ) -> list[tuple[datetime, int | None]]:
        """Every match as (posted_at, price_cents), oldest first, unknown prices included.

        With `dominant` (store, product_id), matches of another keyed product get a None price.
        """
        ...

    def dominant_key(self, wish_id: int) -> tuple[str, str] | None:
        """The wish's dominant (store, product_id) over its comparable priced matches, if any."""
        ...

    def recent_store_offers(self, store: str, since: datetime, limit: int = 500) -> list[Offer]:
        """Priced, live product offers of `store` with `posted_at >= since`, newest first."""
        ...

    def product_urls(self, main_links: Sequence[str]) -> dict[str, str]:
        """Real product URL per main link; links without one are left out. No query if empty."""
        ...

    def purge_text_before(self, cutoff: datetime) -> int: ...

    def get_retro_run(self, wish_id: int) -> RetroRun | None: ...

    def save_retro_run(self, r: RetroRun) -> None: ...

    def list_retro_runs(self) -> list[RetroRun]: ...

    def delete_wish_data(self, wish_id: int) -> None:
        """Delete the wish's matches and its retro run."""
        ...

    def delete_retro_run(self, wish_id: int) -> None:
        """Delete only the run; matches stay."""
        ...
