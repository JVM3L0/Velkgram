import pytest

from velkgram.offers.domain.title import STORE_TITLES
from velkgram.shared.deals import extract_coupons


def _post(*lines: str) -> str:
    return "\n".join(lines)


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        (
            _post(
                "Placa de Video Palit GeForce RTX 5070 WHITE OC 12GB GDDR7 192bit - NE75070U19K9",
                "",
                "R$ 4679",
                "-CUPOM: ZAFADINHO10",
                "",
                "https://cutt.ly/XyIWx4MZ",
                "",
                "-Anúncio",
            ),
            ("ZAFADINHO10",),
        ),
        (
            _post('Monitor Gamer Curvo ASUS TUF 34", WQHD', "", "R$ 1709", "-CUPOM: KORUJAO"),
            ("KORUJAO",),
        ),
        (
            _post("Cooktop 4 Bocas Atlas", "", "R$ 267", "-CUPOM: DESCONTOSESPECIAIS"),
            ("DESCONTOSESPECIAIS",),
        ),
        (
            _post(
                "Cupom Shopee",
                "",
                "R$ 10 OFF em R$ 40: QIP98Q1ZXO",
                "",
                "-Resgate aqui: ",
                "https://s.shopee.com.br/70GSVaUJxC",
                "",
                "-Link carrinho:",
                "https://s.shopee.com.br/7fW9IpEnZG",
            ),
            ("QIP98Q1ZXO",),
        ),
        (
            _post(
                "Cupom Kabum 10% OFF em Selecionados: KORUJAO",
                "",
                "https://tidd.ly/3VLhRy9",
                "",
                "-Teclado Mecânico Machenike K500B-B87 Switch Brown = R$ 80",
            ),
            ("KORUJAO",),
        ),
        (_post("Cupom Amazon Primeira Compra", "50% OFF em R$ 80: TORCIDA50"), ("TORCIDA50",)),
        (_post("Fone X", "R$ 48", "-Resgate cupom do anúncio", "https://amzn.to/x"), ()),
        (_post("Fone X", "R$ 48", "https://amzn.to/x"), ()),
        (_post("Cupom: A", "Cupom: ab", "Cupom: koruja"), ()),
        (_post("Código: ABC-123 e cupom: ABC-123"), ("ABC-123",)),
        (_post("Use o cupom PROMO20 no app"), ("PROMO20",)),
        (_post("Use code: OFF", "cupom: FRETE", "cupom: PIX", "cupom: 12345"), ()),
        (_post("Cupom: A1B", "cupom: B2C"), ("A1B", "B2C")),
        (_post("Cupom: " + "A" * 26), ()),
        (_post("Notebook X", "R$ 3479", "-CUPOM: SELECIONADAS + Resgate cupom do anúncio"), ()),
    ],
)
def test_extract_coupons_real_shapes(text: str, codes: tuple[str, ...]) -> None:
    assert extract_coupons(text) == codes


def test_store_names_are_never_codes() -> None:
    for title in STORE_TITLES.values():
        token = title.upper().replace(" ", "").replace("!", "")
        assert extract_coupons(f"cupom: {token}") == (), token
