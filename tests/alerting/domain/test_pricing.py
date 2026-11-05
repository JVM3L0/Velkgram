import pytest

from velkgram.alerting.domain.pricing import extract_price

CASES = [
    ("🔥 SSD Kingston NV2 2TB R$ 589", 58900),
    ("R$349,90 no pix", 34990),
    ("Monitor por R$ 1.299,00", 129900),
    ("de R$ 499 por R$ 349", 34900),
    ("DE R$ 499,90 POR R$ 349,90", 34990),
    ("SSD KINGSTON 2TB POR 589!!", 58900),
    ("só 79,90", 7990),
    ("R$ 1.199 ou 10x de R$ 119,90", 119900),
    ("12x de R$ 35 sem juros", None),
    ("R$ 99/mês", None),
    ("Cupom: TECH10 — confira", None),
    ("", None),
]

EDGE_CASES = [
    ("10x R$ 119,90 ou R$ 1.099 à vista", 109900),
    ("12x R$ 35", None),
    ("10x R$ 12", None),
    ("por 12x de R$ 35", None),
    ("R$ 1.5", None),
    ("R$ 1.299,5", None),
    ("R$ 1.299.00", None),
    ("Pix R$ 1.899,00\n10x R$ 199,90", 189900),
]


@pytest.mark.parametrize(("text", "expected"), CASES + EDGE_CASES)
def test_extract_price(text: str, expected: int | None) -> None:
    assert extract_price(text) == expected


def test_spellings_extract_same_cents() -> None:
    assert {extract_price(t) for t in ("R$ 1.299,00", "R$1299", "por 1299")} == {129900}


def test_first_remaining_value_wins_without_old_price_marker() -> None:
    assert extract_price("R$ 100 ou R$ 90") == 10000


def test_installment_without_spaces_and_sem_juros_after_value() -> None:
    assert extract_price("10xde R$ 50 ou R$ 450 à vista") == 45000
    assert extract_price("R$ 35 sem juros") is None
