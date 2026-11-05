from datetime import UTC, datetime

import pytest

from tests.offers.domain.test_coupon import AMAZON, KABUM, MERCADO_LIVRE, SHOPEE
from velkgram.offers.domain.build import classify_message, offer_from_message
from velkgram.offers.domain.models import OfferKind
from velkgram.shared.events import MessageData

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

POSTS: list[tuple[str, tuple[str, ...]]] = [
    ("Cupom Shopee\n\nR$ 10 OFF em R$ 40: QIP98Q1ZXO", ("https://s.shopee.com.br/70GSVaUJxC",)),
    (SHOPEE, ("https://s.shopee.com.br/70GSVaUJxC",)),
    (KABUM, ("https://tidd.ly/3VLhRy9", "https://cutt.ly/EyIg351i")),
    (AMAZON, ("https://amzn.to/4vYE0Ie",)),
    (MERCADO_LIVRE, ("https://mercadolivre.com/sec/2U6U32Q",)),
    ("Monitor Gamer\nR$ 1709\n-CUPOM: KORUJAO", ("https://amzn.to/abc",)),
    ("SSD Kingston 1TB por R$ 349", ("https://www.kabum.com.br/produto/1",)),
    ("Promoção sem link nenhum R$ 50", ()),
]


def _msg(text: str, links: tuple[str, ...]) -> MessageData:
    return MessageData(
        channel_id=1,
        message_id=2,
        date=NOW,
        received_at=NOW,
        text=text,
        links=links,
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=False,
        source="live",
    )


@pytest.mark.parametrize(("text", "links"), POSTS)
def test_classify_agrees_with_offer_from_message(text: str, links: tuple[str, ...]) -> None:
    m = _msg(text, links)
    offer = offer_from_message(m, sold_out=False, deleted=False, now=NOW)
    cls = classify_message(m)
    assert offer is not None
    assert cls.store == offer.store
    assert cls.is_coupon_post == (offer.kind == OfferKind.coupon)


def test_store_from_title_when_only_a_short_link() -> None:
    assert classify_message(_msg("Cupom Kabum 10% OFF: KORUJAO", ("https://tidd.ly/x",))).store == (
        "kabum"
    )


def test_store_from_amzn_link() -> None:
    assert classify_message(_msg("Fone R$ 99", ("https://amzn.to/4vYE0Ie",))).store == "amazon"


def test_no_links_gives_no_store() -> None:
    cls = classify_message(_msg("Promoção R$ 50", ()))
    assert cls.store is None
    assert not cls.is_coupon_post
