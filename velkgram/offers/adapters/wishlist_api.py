"""WishReader backed by the wishlist module's public API."""

from velkgram.shared.deals import WishView
from velkgram.wishlist import Wish, WishRepository, match_view


def _views(wishes: list[Wish]) -> list[WishView]:
    return [v for w in wishes if (v := match_view(w)) is not None]


class WishlistApiWishReader:
    def __init__(self, repo: WishRepository) -> None:
        self._repo = repo

    def enabled(self) -> list[WishView]:
        return _views(self._repo.list_enabled())

    def all(self) -> list[WishView]:
        return _views(self._repo.list_all())
