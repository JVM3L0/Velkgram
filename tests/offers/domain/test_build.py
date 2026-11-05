from dataclasses import replace
from datetime import UTC, datetime

from velkgram.offers.domain.build import offer_from_message, wish_fingerprint
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
