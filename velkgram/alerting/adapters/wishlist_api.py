"""WishlistReader backed by the wishlist module's public API."""

from collections.abc import Callable

from velkgram.alerting.domain.models import WishView
from velkgram.wishlist import WishRepository, match_view


class WishlistApiReader:
    def __init__(
        self,
        repo: WishRepository,
        active_users: Callable[[], frozenset[int]] | None = None,
    ) -> None:
        self._repo = repo
        self._active_users = active_users

    def enabled(self) -> list[WishView]:
        views = (match_view(w) for w in self._repo.list_enabled())
        found = [v for v in views if v is not None]
        if self._active_users is None:
            return found
        active = self._active_users()
        return [v for v in found if v.user_id in active]  # a disabled user's wishes stay silent
