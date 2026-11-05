"""Wish model and its validation rules."""

from dataclasses import dataclass

from velkgram.shared.deals import WishView
from velkgram.shared.text import normalize_text


class InvalidWish(ValueError):
    def __init__(self, message_pt: str) -> None:
        super().__init__(message_pt)
        self.message_pt = message_pt


@dataclass(frozen=True, slots=True)
class Wish:
    id: int | None
    name: str
    required_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    max_price_cents: int
    enabled: bool


def split_alternatives(term: str) -> tuple[str, ...]:
    """Split `"a|b|c"` into normalized alternatives, dropping empty parts."""
    parts = (normalize_text(part) for part in term.split("|"))
    return tuple(part for part in parts if part)


def validate_wish(w: Wish) -> None:
    if not w.name.strip():
        raise InvalidWish("Informe um nome")
    if not any(split_alternatives(term) for term in w.required_terms):
        raise InvalidWish("Informe ao menos um termo obrigatório")
    if w.max_price_cents <= 0:
        raise InvalidWish("Preço máximo deve ser maior que zero")


def match_view(w: Wish) -> WishView | None:
    """Matching view of a wish, or None for an unsaved one."""
    if w.id is None:
        return None
    required = tuple(g for g in (split_alternatives(t) for t in w.required_terms) if g)
    excluded = tuple(alt for t in w.excluded_terms for alt in split_alternatives(t))
    return WishView(w.id, w.name, required, excluded, w.max_price_cents)
