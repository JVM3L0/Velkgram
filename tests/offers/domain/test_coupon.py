import pytest

from velkgram.offers.domain.coupon import (
    CouponDeal,
    best_tier,
    coupon_deal,
    coupon_title,
    starts_with_coupon_word,
    store_in_title,
)
from velkgram.offers.domain.models import CouponTier

SHOPEE = (
    "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui: \n"
    "https://s.shopee.com.br/70GSVaUJxC\n\n-Link carrinho:\n"
    "https://s.shopee.com.br/7fW9IpEnZG\n\n-Anúncio"
)
KABUM = (
    "Cupom Kabum 10% OFF em Selecionados: KORUJAO\n\nhttps://tidd.ly/3VLhRy9\n\n"
    "-Teclado Mecânico Machenike K500B-B87 Switch Brown = R$ 80\nhttps://cutt.ly/EyIg351i\n"
)
AMAZON = (
    "Cupom Amazon Primeira Compra\n\n50% OFF em R$ 80, limite de R$ 50 OFF: TORCIDA50\n\n"
    "-Resgate aqui: https://amzn.to/4vYE0Ie"
)


def test_only_posts_titled_cupom_are_coupon_deals() -> None:
    assert coupon_deal("Monitor Gamer", "Monitor\nR$ 1709\n-CUPOM: KORUJAO", ()) is None


@pytest.mark.parametrize("title", ["Cupom Shopee", "CÚPOM Shopee", "  cupom x"])
def test_title_prefix_ignores_accents_and_case(title: str) -> None:
    assert starts_with_coupon_word(title)


def test_shopee_cash_coupon_with_redeem_and_cart_links() -> None:
    assert coupon_deal("Cupom Shopee", SHOPEE, ()) == CouponDeal(
        discount="R$ 10 OFF",
        min_cents=4000,
        scope=None,
        redeem_link="https://s.shopee.com.br/70GSVaUJxC",
        cart_link="https://s.shopee.com.br/7fW9IpEnZG",
        tiers=(CouponTier("R$ 10 OFF", 4000, None, ("QIP98Q1ZXO",)),),
    )


def test_percent_coupon_with_scope_and_no_minimum() -> None:
    deal = coupon_deal("Cupom Kabum 10% OFF em Selecionados: KORUJAO", KABUM, ())
    assert deal is not None
    assert (deal.discount, deal.min_cents, deal.scope) == ("10% OFF", None, "Selecionados")
    assert deal.redeem_link is None
    assert deal.cart_link is None


def test_redeem_link_on_the_same_line_and_first_discount_wins() -> None:
    deal = coupon_deal("Cupom Amazon Primeira Compra", AMAZON, ())
    assert deal is not None
    assert (deal.discount, deal.min_cents) == ("50% OFF", 8000)
    assert deal.redeem_link == "https://amzn.to/4vYE0Ie"


@pytest.mark.parametrize(
    "phrase", ["em R$ 40", "acima de R$ 40", "a partir de R$ 40", "A PARTIR DE R$40,00"]
)
def test_minimum_spend_phrases(phrase: str) -> None:
    deal = coupon_deal("Cupom X", f"Cupom X\nR$ 10 OFF {phrase}: ABC123", ())
    assert deal is not None
    assert deal.min_cents == 4000


def test_title_only_coupon_has_no_extras() -> None:
    deal = coupon_deal("Cupom Misterioso", None, ())
    assert deal == CouponDeal("", None, None, None, None)


@pytest.mark.parametrize(
    ("title", "store"),
    [
        ("Cupom KaBuM em Memórias ram selecionadas - 15% OFF", "kabum"),
        ("CUPOM MAGALU 10% OFF", "magalu"),
        ("Cupom Mercado Livre 20% OFF", "mercadolivre"),
        ("Cupom Casas Bahia R$ 50 OFF", "casasbahia"),
        ("Cupom Amazon Primeira Compra", "amazon"),
        ("Cupom Shopee", "shopee"),
        ("Cupom Americanas", "americanas"),
        ("Cupom de desconto geral", None),
        ("Cupom Amazonas 10% OFF", None),
    ],
)
def test_store_is_inferred_from_a_coupon_title_by_whole_word(title: str, store: str | None) -> None:
    assert store_in_title(title) == store


MERCADO_LIVRE = (
    "Cupom Mercado Livre\n\n"
    "R$ 90 OFF em R$ 699: MOVEIS0511\n"
    "10% OFF em R$ 79, Limite de R$ 40 OFF: SEMPRESAUDE\n"
    "10% OFF em R$ 79, Limite de R$ 100 OFF: DESCONTOSESPECIAIS\n"
    "10% OFF em R$ 149, Limite de R$ 200 OFF: PROMOSML, CLIENTESTOP\n"
    "12% OFF em R$ 79, Limite de R$ 60 OFF: MODAMELI\n"
    "18% OFF em R$ 99, Limite de R$ 60 OFF: AUTOAQUI\n"
    "20% OFF em R$ 79, Limite de R$ 80 OFF: CONSTRUIRAQUI, CASAAQUI\n"
    "25% OFF em R$ 1, Limite de R$ 500 OFF: GARANTAJA, OFERTABOA\n"
    "30% OFF em R$ 1, Limite de R$ 500 OFF: ECONOMIZAML, DESCONTONAHORA\n\n"
    "-Resgate aqui: https://mercadolivre.com/sec/2U6U32Q"
)


def test_multi_tier_coupon_pairs_each_tier_with_its_cap_and_codes() -> None:
    deal = coupon_deal("Cupom Mercado Livre", MERCADO_LIVRE, ())
    assert deal is not None
    assert deal.tiers == (
        CouponTier("R$ 90 OFF", 69900, None, ("MOVEIS0511",)),
        CouponTier("10% OFF", 7900, 4000, ("SEMPRESAUDE",)),
        CouponTier("10% OFF", 7900, 10000, ("DESCONTOSESPECIAIS",)),
        CouponTier("10% OFF", 14900, 20000, ("PROMOSML", "CLIENTESTOP")),
        CouponTier("12% OFF", 7900, 6000, ("MODAMELI",)),
        CouponTier("18% OFF", 9900, 6000, ("AUTOAQUI",)),
        CouponTier("20% OFF", 7900, 8000, ("CONSTRUIRAQUI", "CASAAQUI")),
        CouponTier("25% OFF", 100, 50000, ("GARANTAJA", "OFERTABOA")),
        CouponTier("30% OFF", 100, 50000, ("ECONOMIZAML", "DESCONTONAHORA")),
    )
    assert (deal.discount, deal.min_cents) == ("R$ 90 OFF", 69900)
    assert deal.redeem_link == "https://mercadolivre.com/sec/2U6U32Q"


def test_identical_tiers_collapse_into_one() -> None:
    text = "Cupom X\n10% OFF em R$ 79: AAA111\n10% OFF em R$ 79: AAA111\n10% OFF em R$ 79: BBB222"
    deal = coupon_deal("Cupom X", text, ())
    assert deal is not None
    assert [t.codes for t in deal.tiers] == [("AAA111",), ("BBB222",)]


def test_best_tier_prefers_the_largest_cash_discount_then_the_largest_percent() -> None:
    deal = coupon_deal("Cupom Mercado Livre", MERCADO_LIVRE, ())
    assert deal is not None
    assert best_tier(deal.tiers) == deal.tiers[0]
    percents = (CouponTier("10% OFF", None), CouponTier("30% OFF", 100), CouponTier("5% OFF", None))
    assert best_tier(percents) == CouponTier("30% OFF", 100)
    assert best_tier(()) is None


@pytest.mark.parametrize(
    ("title", "shown"),
    [
        ("Cupom KaBuM em produtos selecionados - 11% OFF", "em produtos selecionados"),
        ("Cupom Shopee", ""),
        ("Cupom Mercado Livre", ""),
        ("CUPOM MAGALU 10% OFF", ""),
        ("Cupom Amazon Primeira Compra", "Primeira Compra"),
        ("Cupom Casas Bahia R$ 50 OFF em eletro", "em eletro"),
        ("Cupom de desconto R$ 10 OFF", "de desconto"),
    ],
)
def test_coupon_title_drops_the_discount_and_the_leading_cupom_store(
    title: str, shown: str
) -> None:
    assert coupon_title(title) == shown
