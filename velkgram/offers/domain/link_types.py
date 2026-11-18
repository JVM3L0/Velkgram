"""Plain data of the link rules, shared by `links` and the per-store rules (pure)."""

from dataclasses import dataclass
from typing import Literal

KB = 1024

Status = int | Literal["invalid", "error", "paused"]
Kind = Literal["product", "not_product", "unknown"]


@dataclass(frozen=True, slots=True)
class FetchPlan:
    follow: bool
    first_hop_only: bool
    # None: the budget is decided at the final hop through `budget_for`.
    body_budget: int | None


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    final_url: str
    hops: tuple[str, ...]
    status: Status
    content_type: str | None
    body: str | None
    answered_by: str  # host that gave the final status


@dataclass(frozen=True, slots=True)
class LinkInfo:
    store: str | None
    product_id: str | None
    title: str | None
    image_url: str | None
    kind: Kind
    page_price_cents: int | None = None  # what the page itself states, off the alert path
