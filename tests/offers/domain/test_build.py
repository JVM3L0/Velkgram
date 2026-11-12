from dataclasses import replace
from datetime import UTC, datetime

import pytest

from velkgram.offers.domain.build import offer_from_message, wish_fingerprint
from velkgram.offers.domain.models import CouponTier, OfferKind
from velkgram.shared.deals import WishView
from velkgram.shared.events import MessageData
from velkgram.shared.text import normalize_text

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _msg(text: str, links: tuple[str, ...] = (), **kw: object) -> MessageData:
    base = MessageData(
        channel_id=1,
        message_id=2,
        date=datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
        received_at=NOW,
        text=text,
        links=links,
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=True,
        source="live",
    )
    return replace(base, **kw)


def test_norm_text_is_normalized_text_or_none() -> None:
    text = "Promoção Fone JBL"
    offer = offer_from_message(
        _msg(text, ("https://x.com/a",)), sold_out=False, deleted=False, now=NOW
    )
    assert offer is not None
    assert offer.norm_text == normalize_text(text)
    blank = offer_from_message(
        _msg("  ", ("https://x.com/a",)), sold_out=False, deleted=False, now=NOW
    )
    assert blank is not None
    assert blank.norm_text is None


def test_offer_from_message_fills_every_field() -> None:
    m = _msg(
        "SSD Kingston por R$ 599,90\nhttps://amzn.to/x",
        ("https://bit.ly/a", "https://amzn.to/x"),
        fwd_from_channel_id=9,
        fwd_from_message_id=8,
    )
    offer = offer_from_message(m, sold_out=True, deleted=False, now=NOW)
    assert offer is not None
    assert (offer.channel_id, offer.message_id, offer.posted_at) == (1, 2, m.date)
    assert offer.title == "SSD Kingston por R$ 599,90"
    assert offer.price_cents == 59990
    assert offer.store == "amazon"
    assert offer.main_link == "https://amzn.to/x"
    assert offer.has_photo is True
    assert offer.text == m.text
    assert (offer.origin_channel_id, offer.origin_message_id) == (9, 8)
    assert (offer.sold_out, offer.deleted, offer.updated_at) == (True, False, NOW)


def test_offer_without_text_and_links_is_none() -> None:
    assert offer_from_message(_msg(" \n"), sold_out=False, deleted=False, now=NOW) is None


def test_offer_with_link_only_has_fallback_title() -> None:
    m = _msg("", ("https://kabum.com.br/p/1",))
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.text is None
    assert offer.title == "KaBuM!"
    assert offer.price_cents is None


def _wish(**kw: object) -> WishView:
    return replace(WishView(1, "A", (("ssd",),), ("usado",), 50000), **kw)


def test_fingerprint_changes_with_terms_and_price() -> None:
    base = wish_fingerprint(_wish())
    assert len(base) == 40
    assert wish_fingerprint(_wish(required=(("hd",),))) != base
    assert wish_fingerprint(_wish(excluded=())) != base
    assert wish_fingerprint(_wish(max_price_cents=1)) != base


def test_fingerprint_ignores_name() -> None:
    assert wish_fingerprint(_wish(name="Outro", id=7)) == wish_fingerprint(_wish())


def test_offer_comparable_flag_follows_the_coupon_and_multi_price_rule() -> None:
    plain = offer_from_message(_msg("Fone JBL por R$ 99"), sold_out=False, deleted=False, now=NOW)
    coupon = offer_from_message(
        _msg("Cupom Kabum 10% OFF\n- A = R$ 80\n- B = R$ 140"),
        sold_out=False,
        deleted=False,
        now=NOW,
    )
    assert plain is not None and coupon is not None
    assert plain.comparable is True
    assert coupon.comparable is False


PALIT = (
    "Placa de Video Palit GeForce RTX 5070 WHITE OC 12GB GDDR7 192bit 3-DP e HDMI\n\n"
    "R$ 4679\n-CUPOM: ZAFADINHO10\n\nhttps://cutt.ly/XyIWx4MZ\n\n-Anúncio"
)
SHOPEE = (
    "Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO\n\n-Resgate aqui: \n"
    "https://s.shopee.com.br/70GSVaUJxC\n\n-Link carrinho:\n"
    "https://s.shopee.com.br/7fW9IpEnZG\n\n-Anúncio"
)


def test_product_with_coupon_keeps_the_posted_price_and_lists_codes() -> None:
    offer = offer_from_message(
        _msg(PALIT, ("https://cutt.ly/XyIWx4MZ",)), sold_out=False, deleted=False, now=NOW
    )
    assert offer is not None
    assert offer.kind is OfferKind.product
    assert offer.price_cents == 467900  # already the final price with the coupon
    assert offer.coupons == ("ZAFADINHO10",)
    assert offer.coupon_discount is None
    assert offer.comparable


def test_coupon_post_has_no_price_and_carries_the_deal() -> None:
    links = ("https://s.shopee.com.br/70GSVaUJxC", "https://s.shopee.com.br/7fW9IpEnZG")
    offer = offer_from_message(_msg(SHOPEE, links), sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.kind is OfferKind.coupon
    assert offer.price_cents is None
    assert not offer.comparable
    assert offer.coupons == ("QIP98Q1ZXO",)
    assert (offer.coupon_discount, offer.coupon_min_cents, offer.coupon_scope) == (
        "R$ 10 OFF",
        4000,
        None,
    )
    assert offer.coupon_tiers == (CouponTier("R$ 10 OFF", 4000, None, ("QIP98Q1ZXO",)),)
    assert offer.redeem_link == links[0]
    assert offer.cart_link == links[1]


def test_post_without_coupon_words_has_no_codes() -> None:
    offer = offer_from_message(
        _msg("SSD por R$ 299", ("https://amzn.to/x",)), sold_out=False, deleted=False, now=NOW
    )
    assert offer is not None
    assert offer.coupons == ()
    assert offer.kind is OfferKind.product


def test_coupon_without_a_store_link_takes_the_store_from_its_title() -> None:
    text = "Cupom KaBuM em Cadeira selecionada - 50% OFF\n\n-CUPOM: BLACK50\n\nhttps://tidd.ly/abc"
    offer = offer_from_message(
        _msg(text, ("https://tidd.ly/abc",)), sold_out=False, deleted=False, now=NOW
    )
    assert offer is not None
    assert offer.store == "kabum"


def test_product_post_never_guesses_its_store_from_the_title() -> None:
    offer = offer_from_message(
        _msg("Fone Amazon Basics R$ 50\nhttps://tidd.ly/x", ("https://tidd.ly/x",)),
        sold_out=False,
        deleted=False,
        now=NOW,
    )
    assert offer is not None
    assert offer.store is None


def test_main_link_is_the_labelled_product_link_not_the_coupon_page_before_it() -> None:
    coupons, product = "https://s.shopee.com.br/30fk4tl3lu", "https://s.shopee.com.br/8fTr4C8eWt"
    m = _msg(
        "DJI Osmo Nano (128GB), Câmera 4K\n\nR$ 1522\n"
        f"-Resgate todos os cupons desta página: {coupons}\n\n-Link produto: {product}",
        (coupons, product),
    )
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.main_link == product
    assert offer.store == "shopee"


def test_coupon_post_keeps_its_first_link_as_the_main_link() -> None:
    redeem, cart = "https://s.shopee.com.br/70GSVaUJxC", "https://s.shopee.com.br/7fW9IpEnZG"
    m = _msg(
        "Cupom Shopee\n\nR$ 40 OFF em R$ 199: CODIGO1\n"
        f"-Resgate aqui: {redeem}\n-Link carrinho: {cart}",
        (redeem, cart),
    )
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.main_link == redeem


def test_list_post_has_no_price_and_no_main_link_but_keeps_its_store() -> None:
    first, second = "https://link.amazon/B06LZorOc", "https://link.amazon/B0fVH2s7r"
    m = _msg(
        "Leve 3 pelo preço de 2\n\n1 https://link.amazon/B0dysqBQ9\n\n"
        f"-12x NIVEA Derma 150ml = R$ 87\n{first}\n\n-12x Rexona V8 250ml = R$ 110\n{second}",
        ("https://link.amazon/B0dysqBQ9", first, second),
    )
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.price_cents is None
    assert offer.main_link is None
    assert offer.store == "amazon"
    assert offer.comparable is False
    assert offer.kind is OfferKind.product


def test_coupon_post_that_lists_products_keeps_its_links() -> None:
    a, b = "https://www.kabum.com.br/produto/1", "https://www.kabum.com.br/produto/2"
    m = _msg(f"Cupom Kabum 10% OFF: KORUJAO\n-A = R$ 10\n{a}\n-B = R$ 20\n{b}", (a, b))
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.kind is OfferKind.coupon
    assert offer.main_link == a


def test_a_store_discount_post_is_a_coupon_not_a_product_priced_at_the_discount() -> None:
    m = _msg("iFood R$ 20 OFF Mercados: ATACADOBF")
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.kind is OfferKind.coupon
    assert offer.price_cents is None  # R$ 20 is the discount, never the price
    assert offer.comparable is False
    assert offer.coupons == ("ATACADOBF",)
    assert offer.coupon_discount == "R$ 20 OFF"


def test_a_similar_looking_product_post_stays_a_product() -> None:
    m = _msg(
        "Notebook Gamer Acer Nitro V15 por R$ 3999 - R$ 200 OFF: CODIGO", ("https://amzn.to/x",)
    )
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None and offer.kind is OfferKind.product


WORDY = "Desconto especial no iFood hoje R$ 20 OFF: ATACADOBF"


def test_a_shape_only_coupon_with_a_wordy_title_is_a_coupon() -> None:
    offer = offer_from_message(_msg(WORDY, has_photo=False), sold_out=False, deleted=False, now=NOW)
    assert offer is not None
    assert offer.kind is OfferKind.coupon
    assert offer.price_cents is None and offer.comparable is False
    assert offer.coupons == ("ATACADOBF",)


def test_the_structural_signal_needs_every_part() -> None:
    # a photo or a link means it is selling something: stays a product
    with_photo = _msg(WORDY, has_photo=True)
    with_link = _msg(WORDY, ("https://www.ifood.com.br/x",), has_photo=False)
    priced = _msg("Desconto especial iFood por R$ 90 e R$ 20 OFF: ATACADOBF", has_photo=False)
    no_code = _msg("Desconto especial no iFood hoje R$ 20 OFF", has_photo=False)
    for m in (with_photo, with_link, priced, no_code):
        offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
        assert offer is not None and offer.kind is OfferKind.product, m.text


def test_classify_message_applies_the_same_structural_signal() -> None:
    from velkgram.offers.domain.build import classify_message

    assert classify_message(_msg(WORDY, has_photo=False)).is_coupon_post
    assert not classify_message(_msg(WORDY, has_photo=True)).is_coupon_post


CHATTER = ["Menor preço histórico?", "Precin", "Última chance!", "BARATO EM", "🔥", "PQP"]


@pytest.mark.parametrize("text", CHATTER)
def test_channel_chatter_with_no_price_link_store_or_photo_is_not_an_offer(text: str) -> None:
    offer = offer_from_message(_msg(text, has_photo=False), sold_out=False, deleted=False, now=NOW)
    assert offer is not None  # still stored, so nothing is lost
    assert offer.kind is OfferKind.chatter
    assert offer.price_cents is None and offer.comparable is False


@pytest.mark.parametrize(
    "m",
    [
        _msg("Menor preço histórico?", has_photo=True),  # a photo may carry the product
        _msg("Menor preço histórico?", ("https://amzn.to/x",), has_photo=False),  # a link
        _msg("Monitor por R$ 999", has_photo=False),  # a price
        _msg("Menor preço histórico? na Kabum", ("https://www.kabum.com.br/p/1",), has_photo=False),
    ],
)
def test_a_post_with_a_photo_a_link_or_a_price_stays_a_product(m: MessageData) -> None:
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    assert offer is not None and offer.kind is OfferKind.product


def test_a_coupon_or_a_list_is_never_chatter() -> None:
    coupon = offer_from_message(
        _msg("iFood R$ 12 OFF Restaurantes: BFFOOD", has_photo=False),
        sold_out=False,
        deleted=False,
        now=NOW,
    )
    assert coupon is not None and coupon.kind is OfferKind.coupon
