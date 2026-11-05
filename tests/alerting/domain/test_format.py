from datetime import UTC, datetime

from velkgram.alerting.domain.format import (
    format_alert,
    format_coupon_alert,
    message_link,
    telegram_link,
)
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


def _coupon(**kw: object) -> str:
    args: dict[str, object] = {
        "store_title": "Shopee",
        "codes": ("QIP98Q1ZXO",),
        "discount": "R$ 10 OFF",
        "min_cents": 4000,
        "scope": None,
        "wish_name": "SSD",
        "offer_price_cents": 9900,
        "max_price_cents": 20000,
        "over_max": False,
        "link": "https://s.shopee.com.br/x",
    }
    args.update(kw)
    return format_coupon_alert(**args)  # type: ignore[arg-type]


def test_coupon_alert_plain() -> None:
    assert _coupon().splitlines() == [
        "🎟️ Cupom Shopee: QIP98Q1ZXO — R$ 10 OFF a partir de R$ 40,00",
        'Para "SSD": oferta de R$ 99,00',
        "https://s.shopee.com.br/x",
    ]


def test_coupon_alert_over_max() -> None:
    line = _coupon(over_max=True, offer_price_cents=25000).splitlines()[1]
    assert line == 'Para "SSD": oferta de R$ 250,00 (acima do seu limite de R$ 200,00)'


def test_coupon_alert_with_scope_adds_caveat_line() -> None:
    lines = _coupon(scope="eletrônicos").splitlines()
    assert lines[0].endswith("a partir de R$ 40,00 em eletrônicos")
    assert lines[2] == "• pode não valer para todos os produtos"
    assert lines[3] == "https://s.shopee.com.br/x"


def test_coupon_alert_without_discount_or_minimum() -> None:
    first = _coupon(discount="", min_cents=None).splitlines()[0]
    assert first == "🎟️ Cupom Shopee: QIP98Q1ZXO"


def test_coupon_alert_lists_mercado_livre_tier_codes() -> None:
    first = _coupon(
        store_title="Mercado Livre", codes=("ML10", "ML10B"), discount="10% OFF", min_cents=None
    ).splitlines()[0]
    assert first == "🎟️ Cupom Mercado Livre: ML10, ML10B — 10% OFF"


def test_rendered_text_is_returned_verbatim() -> None:
    assert format_alert(_msg(rendered="texto pronto")) == "texto pronto"
