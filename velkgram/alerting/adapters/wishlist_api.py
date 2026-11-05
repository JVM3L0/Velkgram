"""WishlistReader backed by the wishlist module's public API."""

from velkgram.alerting.domain.models import WishView
from velkgram.wishlist import WishRepository, match_view


class WishlistApiReader:
    def __init__(self, repo: WishRepository) -> None:
        self._repo = repo

    def enabled(self) -> list[WishView]:
        views = (match_view(w) for w in self._repo.list_enabled())
        return [v for v in views if v is not None]
