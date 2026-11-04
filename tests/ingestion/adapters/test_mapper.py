from datetime import UTC, datetime

from telethon.tl import types

from tests.fixtures.telegram.factories import make_message
from velkgram.ingestion.adapters.telethon.mapper import to_message_data

NOW = datetime(2026, 11, 4, 12, 1, tzinfo=UTC)
CH = -1001234


def _map(msg: types.Message):
    return to_message_data(msg, CH, NOW, "live")


def test_maps_text_and_hidden_entity_links() -> None:
    msg = make_message(
        text="Oferta aqui",
        entities=[types.MessageEntityTextUrl(offset=7, length=4, url="https://a.example/x")],
    )
    d = _map(msg)
    assert d.text == "Oferta aqui"
    assert d.links == ("https://a.example/x",)
    assert (d.channel_id, d.message_id, d.received_at, d.source) == (CH, 1, NOW, "live")


def test_maps_plain_url_entity_with_emoji_before_it() -> None:
    url = "https://b.example/p"
    text = f"😀🔥 {url}"
    # emojis are 2 UTF-16 units each; the URL starts at offset 5
    msg = make_message(text=text, entities=[types.MessageEntityUrl(offset=5, length=len(url))])
    assert _map(msg).links == (url,)


def test_maps_url_buttons() -> None:
    msg = make_message(
        text="x",
        entities=[types.MessageEntityTextUrl(offset=0, length=1, url="https://a.example")],
        buttons=["https://c.example", "https://a.example"],
    )
    assert _map(msg).links == ("https://a.example", "https://c.example")


def test_maps_forward_origin_to_full_channel_id() -> None:
    d = _map(make_message(text="x", fwd_channel_id=1234567890, fwd_post=77))
    assert d.fwd_from_channel_id == -1001234567890
    assert d.fwd_from_message_id == 77


def test_photo_without_caption_has_empty_text() -> None:
    d = _map(make_message(text="", photo=True))
    assert d.text == ""
    assert d.has_photo is True
    assert d.links == ()
    assert d.fwd_from_channel_id is None


def test_album_grouped_id() -> None:
    assert _map(make_message(text="x", grouped_id=99)).grouped_id == 99
