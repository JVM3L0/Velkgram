"""WishlistReader backed by the wishlist module's public API."""

from velkgram.alerting.domain.models import WishView
from velkgram.wishlist import Wish, WishRepository, split_alternatives


def _to_view(w: Wish) -> WishView | None:
    if w.id is None:
        return None
    required = tuple(g for g in (split_alternatives(t) for t in w.required_terms) if g)
    excluded = tuple(alt for t in w.excluded_terms for alt in split_alternatives(t))
    return WishView(w.id, w.name, required, excluded, w.max_price_cents)


class WishlistApiReader:
    def __init__(self, repo: WishRepository) -> None:
        self._repo = repo

    def enabled(self) -> list[WishView]:
        views = (_to_view(w) for w in self._repo.list_enabled())
        return [v for v in views if v is not None]
