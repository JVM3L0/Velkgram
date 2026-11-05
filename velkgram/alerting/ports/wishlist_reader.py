"""Read-side view of the wishlist used by the evaluator."""

from typing import Protocol

from velkgram.alerting.domain.models import WishView


class WishlistReader(Protocol):
    def enabled(self) -> list[WishView]: ...
