"""Port: fetch a link and follow its redirects within a plan's budgets."""

from collections.abc import Callable
from typing import Protocol

from velkgram.offers.domain.links import FetchOutcome, FetchPlan


class HostPaused(Exception):
    """Raised by `before_request` when the hop's host is paused; the fetch ends as `paused`."""


class Fetcher(Protocol):
    def fetch(
        self,
        url: str,
        plan: FetchPlan,
        before_request: Callable[[str], None],
        budget_for: Callable[[str], int],
    ) -> FetchOutcome:
        """`before_request(url)` runs before every request, on every hop.

        `budget_for(final_url)` decides the body budget when `plan.body_budget` is None.
        """
        ...
