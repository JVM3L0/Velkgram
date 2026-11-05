from datetime import UTC, datetime

from velkgram.alerting.domain.format import format_alert, message_link, telegram_link
from velkgram.alerting.domain.models import AlertMessage
from velkgram.shared.events import MessageData


def _md(links: tuple[str, ...]) -> MessageData:
    now = datetime(2026, 11, 4, tzinfo=UTC)
    return MessageData(
        channel_id=-1001234,
        message_id=9,
        date=now,
        received_at=now,
        text="x",
        links=links,
        fwd_from_channel_id=None,
        fwd_from_message_id=None,
        grouped_id=None,
        has_photo=False,
        source="live",
    )


def _msg(**kw: object) -> AlertMessage:
    base = AlertMessage(
        wish_name="SSD",
        text="oferta",
        price_cents=129990,
        channel_name="Promos",
        link="https://t.me/c/1234/9",
        delayed_minutes=None,
    )
    from dataclasses import replace

    return replace(base, **kw)  # type: ignore[arg-type]


def test_message_link_prefers_offer_link() -> None:
    assert telegram_link(-1001234, 9) == "https://t.me/c/1234/9"
    assert message_link(_md(("https://loja.com/x",))) == "https://loja.com/x"
    assert message_link(_md(())) == "https://t.me/c/1234/9"


def test_format_brl() -> None:
    out = format_alert(_msg())
    lines = out.splitlines()
    assert lines[0] == "🔔 SSD"
    assert "R$ 1.299,90" in out
    assert "via Promos" in out
    assert "https://t.me/c/1234/9" in out


def test_format_price_unknown_and_delayed() -> None:
    out = format_alert(_msg(price_cents=None, delayed_minutes=12, text="y" * 400))
    assert "⚠️ preço não identificado" in out
    assert "⏱ atrasado 12 min" in out
    assert "y" * 300 in out
    assert "y" * 301 not in out


def test_alert_mentions_the_coupon_right_after_the_price() -> None:
    text = "Placa de Video Palit RTX 5070\n\nR$ 4679\n-CUPOM: ZAFADINHO10\n\n-Anúncio"
    lines = format_alert(_msg(price_cents=467900, text=text)).splitlines()
    assert lines[1] == "R$ 4.679,00 com cupom ZAFADINHO10"


def test_alert_lists_several_coupons() -> None:
    text = "Teclado\nR$ 80\ncupom: AAA111\nCódigo: BBB222"
    assert format_alert(_msg(price_cents=8000, text=text)).splitlines()[1] == (
        "R$ 80,00 com cupons AAA111, BBB222"
    )


def test_alert_without_a_coupon_keeps_the_plain_price_line() -> None:
    assert format_alert(_msg()).splitlines()[1] == "R$ 1.299,90"
