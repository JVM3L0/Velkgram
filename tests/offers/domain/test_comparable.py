import pytest

from velkgram.offers.domain.comparable import is_comparable

COUPON_LIST = (
    "Cupom Kabum 10% OFF em Selecionados: KORUJAO\n\n"
    "-Teclado Mecânico Machenike K500B-B87 Switch Brown = R$ 80\nhttps://cutt.ly/a\n\n"
    "-Teclado Mecânico Husky Anchorage RGB Switch Gateron Brown = R$ 140\nhttps://cutt.ly/b\n"
)
MONITOR = (
    'Monitor Gamer Curvo ASUS TUF 34", WQHD, 250Hz, Fast VA - VG34WQML5A\n\n'
    "R$ 1709\n-CUPOM: KORUJAO\n\nhttps://cutt.ly/ryIg386y"
)


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        ("Cupom Kabum 10% OFF em Selecionados: KORUJAO", COUPON_LIST, False),
        ("Cupom KaBuM em Memórias ram selecionadas - 15% OFF", "-CUPOM: DRAMOFF15", False),
        ("CÚPOM Amazon 20%", None, False),
        ("  cupom Magalu", "Cupom Magalu R$ 50", False),
        ('Monitor Gamer Curvo ASUS TUF 34"', MONITOR, True),
        ("Fone JBL", "de R$ 499 por R$ 349", True),
        ("Fone JBL", "DE R$ 1.499,90 POR R$ 999", True),
        ("Fone JBL", "R$ 349 em 10x de R$ 35", True),
        ("Fone JBL", "R$ 349 ou R$ 349", True),
        ("Fone JBL", "Fone R$ 100 e Capa R$ 40", False),
        ("Fone JBL", "de R$ 499 por R$ 349 e Capa R$ 40", False),
        ("Fone JBL", "por 349!!", True),
        ("Fone JBL", None, True),
    ],
)
def test_is_comparable(title: str, text: str | None, expected: bool) -> None:
    assert is_comparable(title, text) is expected
