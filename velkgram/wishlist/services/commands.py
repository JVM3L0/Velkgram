"""Wish write use cases: validate, then persist."""

from dataclasses import replace

from velkgram.wishlist.domain.models import InvalidWish, Wish, validate_wish
from velkgram.wishlist.ports.repository import WishRepository


class WishCommands:
    def __init__(self, repo: WishRepository) -> None:
        self._repo = repo

    def create(
        self,
        name: str,
        required_terms: tuple[str, ...],
        excluded_terms: tuple[str, ...],
        max_price_cents: int,
        enabled: bool = True,
        user_id: int = 1,
    ) -> Wish:
        wish = Wish(
            None, name.strip(), required_terms, excluded_terms, max_price_cents, enabled, user_id
        )
        validate_wish(wish)
        return self._repo.add(wish)

    def update(self, w: Wish) -> None:
        if w.id is None:
            raise InvalidWish("Desejo não encontrado")
        validate_wish(w)
        self._repo.update(w)

    def toggle(self, id: int, enabled: bool) -> None:
        current = self._repo.get(id)
        if current is None:
            raise InvalidWish("Desejo não encontrado")
        self._repo.update(replace(current, enabled=enabled))

    def delete(self, id: int) -> None:
        self._repo.delete(id)
