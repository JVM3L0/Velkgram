import pytest

from velkgram.offers.domain.coupon import CouponDeal, coupon_deal, starts_with_coupon_word

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
