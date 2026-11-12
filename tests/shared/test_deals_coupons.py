import pytest

from velkgram.offers.domain.title import STORE_TITLES
from velkgram.shared.deals import extract_coupons, is_coupon_title


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
        (
            _post("Ar Condicionado Hisense", "R$ 1453", "-CUPOM: IFPWBISS ou ISKANDAR5 + moedas"),
            ("IFPWBISS", "ISKANDAR5"),
        ),
        (
            _post(
                "Cupom Mercado Livre",
                "10% OFF em R$ 149, Limite de R$ 200 OFF: PROMOSML, CLIENTESTOP",
            ),
            ("PROMOSML", "CLIENTESTOP"),
        ),
        (
            _post(
                "Cupom Mercado Livre",
                "20% OFF em R$ 79, Limite de R$ 80 OFF: CONSTRUIRAQUI, CASAAQUI",
            ),
            ("CONSTRUIRAQUI", "CASAAQUI"),
        ),
        (
            _post(
                "Cupom Mercado Livre", "25% OFF em R$ 1, Limite de R$ 500 OFF: GARANTAJA, OFERTABOA"
            ),
            ("GARANTAJA", "OFERTABOA"),
        ),
        (
            _post("Cupom: AAA111 / BBB222 + CCC333 e DDD444"),
            ("AAA111", "BBB222", "CCC333", "DDD444"),
        ),
        (_post("Cupom: AAA111, depois fale com a loja, ZZZ999"), ("AAA111",)),
        (_post("Hoje às 10:00 use cupom ABC12"), ("ABC12",)),
        (_post("Cupom Shopee", "ATENÇÃO: LIMITADO"), ()),
        (_post("Cupom Shopee", "R$ 10 OFF em R$ 40: LIMITADO"), ()),
        (
            _post("Cupom: NOVO", "cupom: HOJE", "cupom: ACIMA", "cupom: ATENCAO", "cupom: GRÁTIS"),
            (),
        ),
        (_post("Notebook X", "R$ 3479", "-CUPOM: SELECIONADAS + Resgate cupom do anúncio"), ()),
    ],
)
def test_extract_coupons_real_shapes(text: str, codes: tuple[str, ...]) -> None:
    assert extract_coupons(text) == codes


def test_store_names_are_never_codes() -> None:
    for title in STORE_TITLES.values():
        token = title.upper().replace(" ", "").replace("!", "")
        assert extract_coupons(f"cupom: {token}") == (), token


@pytest.mark.parametrize(
    "title",
    [
        "iFood R$ 20 OFF Mercados: ATACADOBF",
        "iFood R$ 12 OFF Restaurantes: BFFOOD",
        "iFood Farmácia R$ 20 OFF: FARMABF",
        "iFood Mercado R$ 20 OFF: BFDUPLA",
        "iFood R$ 12 OFF em R$ 27 : COMEOUBF",
        "Uber Eats 30% OFF: UBER30",
        "Cupom Shopee R$ 10 OFF em R$ 40: CODIGO1",
        "Cupons Magalu",
    ],
)
def test_coupon_titles_include_store_posts_that_start_with_the_discount(title: str) -> None:
    assert is_coupon_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "SSD Kingston NV2 1TB por R$ 299",
        "Notebook Gamer Acer Nitro V15 por R$ 3999 - R$ 200 OFF: CODIGO",
        "Fone JBL Tune 510BT R$ 20 OFF",
        "Monitor Gamer AOC 27 polegadas Full HD 144Hz 20% OFF: BLACK10",
        "iFood - Subway por R$0,01 centavo",
        "Kit 3 camisetas R$ 99",
        "",
    ],
)
def test_product_titles_are_not_coupon_titles(title: str) -> None:
    assert not is_coupon_title(title)


def test_codes_are_read_from_a_store_discount_post() -> None:
    assert extract_coupons("iFood R$ 12 OFF Restaurantes: BFFOOD") == ("BFFOOD",)
    assert extract_coupons("iFood Farmácia R$ 20 OFF: FARMABF\n\n-Anúncio") == ("FARMABF",)
