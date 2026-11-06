"""Link enrichment storage port (rows keyed by the offer's exact `main_link`)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from velkgram.offers.domain.links import Kind

LinkStatus = Literal["pending", "done", "failed", "blocked"]


@dataclass(frozen=True, slots=True)
class LinkRow:
    url: str
    host: str
    offer_posted_at: datetime
    created_at: datetime
    id: int | None = None
    final_url: str | None = None
    final_host: str | None = None
    store: str | None = None
    product_id: str | None = None
    title: str | None = None
    image_url: str | None = None
    kind: Kind = "unknown"
    status: LinkStatus = "pending"
    attempts: int = 0
    blocks: int = 0
    next_try_at: datetime | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EnrichHeartbeat:
    last_run_at: datetime
    pending: int
    done: int
    failed: int
    blocked: int


class LinkRepository(Protocol):
    def discover(self, limit: int = 50) -> int:
        """Insert `pending` rows for live offers' unseen links, newest first; return the count."""
        ...

    def next_due(self, now: datetime, paused_hosts: frozenset[str]) -> LinkRow | None: ...

    def earliest_next_try(self, now: datetime, paused_hosts: frozenset[str]) -> datetime | None:
        """Earliest time `next_due` could return a row (`now` for a never-tried row)."""
        ...

    def known_product(self, store: str, product_id: str) -> tuple[str | None, str | None] | None:
        """`(title, image_url)` of a `done` row of this product that has a title."""
        ...

    def save(self, row: LinkRow, *, fix_store: bool) -> int:
        """Update the row; with `fix_store`, give its store to offers that have none.

        Returns the number of offers fixed. A known store is never overwritten.
        """
        ...

    def write_heartbeat(self, now: datetime) -> None: ...

    def heartbeat(self) -> EnrichHeartbeat | None: ...
