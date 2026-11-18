"""Invariants of the store registry: a new store that is ambiguous fails here, not in production."""

import re
import unicodedata
from collections import Counter

import pytest

from velkgram.offers.domain.stores import STORES, store_of


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in decomposed if not unicodedata.combining(c)))


def test_each_store_is_keyed_by_its_own_slug() -> None:
    assert all(slug == store.slug for slug, store in STORES.items())


def test_display_names_are_unique_once_normalized() -> None:
    counts = Counter(_plain(s.name) for s in STORES.values())
    assert [n for n, c in counts.items() if c > 1] == []


def test_no_domain_belongs_to_two_stores() -> None:
    counts = Counter(d for s in STORES.values() for d in s.domains)
    assert [d for d, c in counts.items() if c > 1] == []


def test_no_store_name_is_a_whole_word_prefix_of_another() -> None:
    # `store_in_title` takes the first match, so "Casas" would swallow "Casas Bahia".
    names = {s.slug: _plain(s.name) for s in STORES.values()}
    clashes = [
        (a, b)
        for a, na in names.items()
        for b, nb in names.items()
        if a != b and (nb == na or nb.startswith(na + " "))
    ]
    assert clashes == []


@pytest.mark.parametrize(
    ("slug", "store"), [(slug, store) for slug, store in STORES.items()], ids=list(STORES)
)
def test_every_domain_resolves_back_to_its_store(slug: str, store: object) -> None:
    domains: tuple[str, ...] = getattr(store, "domains")  # noqa: B009
    assert all(store_of(f"https://www.{d}/x") == slug for d in domains)
