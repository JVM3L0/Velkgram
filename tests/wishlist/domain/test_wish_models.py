import pytest

from velkgram.wishlist import InvalidWish, Wish, split_alternatives
from velkgram.wishlist.domain.models import validate_wish


def _wish(**overrides: object) -> Wish:
    base = Wish(None, "SSD", ("ssd|nvme",), ("usado",), 30000, True)
    from dataclasses import replace

    return replace(base, **overrides)  # type: ignore[arg-type]


def test_split_alternatives() -> None:
    assert split_alternatives("2TB| 2 tb |") == ("2tb", "2 tb")


def test_validate_accepts_valid_wish() -> None:
    validate_wish(_wish())


def test_validate_rejects_empty_required_terms() -> None:
    with pytest.raises(InvalidWish, match="termo obrigatório"):
        validate_wish(_wish(required_terms=()))
    with pytest.raises(InvalidWish, match="termo obrigatório"):
        validate_wish(_wish(required_terms=(" | ",)))


def test_validate_rejects_blank_name() -> None:
    with pytest.raises(InvalidWish, match="nome"):
        validate_wish(_wish(name="  "))


@pytest.mark.parametrize("price", [0, -1])
def test_validate_rejects_non_positive_price(price: int) -> None:
    with pytest.raises(InvalidWish, match="Preço máximo"):
        validate_wish(_wish(max_price_cents=price))
