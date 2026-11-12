from velkgram.shared.deals import ListItem, product_list

REXONA = """Leve 3 pelo preço de 2

1 https://link.amazon/B0dysqBQ9
2 https://link.amazon/B0eTbRlFF

-12x NIVEA Derma Protect Clinical 150ml = R$ 87
https://link.amazon/B06LZorOc

-12x Rexona V8 Masculino 250ml = R$ 110
https://link.amazon/B0fVH2s7r

-Anúncio"""

VAIO = """Notebook VAIO FE16 8GB RAM 256GB SSD 16" IPS Full HD Antirreflexo

-Use o cupom: SEMPREOFF

-Ryzen 3-7330U = R$ 2374
https://meli.la/1Li7zvZ
-Core i5-1334U = R$ 2659
https://meli.la/2xYYZb8

-Anúncio"""


def test_list_post_yields_one_item_per_priced_line_with_its_link() -> None:
    found = product_list(REXONA, ())
    assert found is not None
    assert found.items == (
        ListItem("12x NIVEA Derma Protect Clinical 150ml", 8700, "https://link.amazon/B06LZorOc"),
        ListItem("12x Rexona V8 Masculino 250ml", 11000, "https://link.amazon/B0fVH2s7r"),
    )


def test_header_is_the_text_before_the_first_item() -> None:
    found = product_list(VAIO, ())
    assert found is not None
    assert found.header.startswith("Notebook VAIO FE16")
    assert "SEMPREOFF" in found.header
    assert "Ryzen" not in found.header
    assert [i.price_cents for i in found.items] == [237400, 265900]


def test_item_link_on_the_same_line_counts() -> None:
    text = "Ofertas\n-Paçoca = R$ 14 https://s.shopee.com.br/a\n-Café = R$ 16 https://s.shopee.com.br/b"
    found = product_list(text, ())
    assert found is not None
    assert [i.link for i in found.items] == [
        "https://s.shopee.com.br/a",
        "https://s.shopee.com.br/b",
    ]
    assert [i.name for i in found.items] == ["Paçoca", "Café"]


def test_link_is_matched_to_the_normalized_links_of_the_message() -> None:
    text = "Ofertas\n-A = R$ 10\nhttps://x.test/a?utm=1\n-B = R$ 20\nhttps://x.test/b?utm=1"
    found = product_list(text, ("https://x.test/a", "https://x.test/b"))
    assert found is not None
    assert [i.link for i in found.items] == ["https://x.test/a", "https://x.test/b"]


def test_single_product_with_extra_links_is_not_a_list() -> None:
    text = (
        "Camiseta Masculina Academia Dry\n\nR$ 19\n-Resgate todos os cupons desta página no APP:\n"
        "https://s.shopee.com.br/9pfnHviqhq\n\n-Link produto: https://s.shopee.com.br/8VAPhTryru"
    )
    assert product_list(text, ()) is None


def test_one_priced_item_is_not_a_list() -> None:
    assert product_list("Fone = R$ 99\nhttps://x.test/a", ()) is None


def test_prices_without_links_are_not_a_list() -> None:
    assert product_list("A = R$ 10\nB = R$ 20", ()) is None


def test_installment_lines_are_not_items() -> None:
    text = "Notebook\n10x de R$ 350 https://x.test/a\n12x de R$ 300 https://x.test/b"
    assert product_list(text, ()) is None
