from datetime import UTC, datetime, timedelta

from velkgram.alerting.domain.format import (
    format_age,
    format_alert,
    format_coupon_alert,
    format_saving,
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
        "store_title": "Mercado Livre",
        "codes": ("OFFNOML",),
        "discount": "15% OFF",
        "min_cents": None,
        "cap_cents": 4000,
        "scope": None,
        "wish_name": "Monitor",
        "offer_title": "Smart Tv Aoc 50'' 50U7066",
        "offer_price_cents": 170900,
        "max_price_cents": 200000,
        "over_max": False,
        "offer_age": timedelta(hours=5, minutes=50),
        "product_url": "https://www.mercadolivre.com.br/p/MLB1",
        "offer_link": "https://meli.la/x",
        "coupon_link": "https://mercadolivre.com/sec/2U6U32Q",
    }
    args.update(kw)
    return format_coupon_alert(**args)  # type: ignore[arg-type]


GOLDEN_A = """🎟️ Cupom Mercado Livre: OFFNOML — 15% OFF, limite de R$ 40,00
Para "Monitor": Smart Tv Aoc 50'' 50U7066
💰 R$ 1.709,00 → R$ 40,00 de desconto (2,3%) → ~R$ 1.669,00 ⚠️ limite baixo
📅 oferta postada há 5 h
🔗 Produto: https://www.mercadolivre.com.br/p/MLB1
🎟️ Resgatar cupom: https://mercadolivre.com/sec/2U6U32Q"""


def test_coupon_alert_golden_with_product_link() -> None:
    assert _coupon() == GOLDEN_A


def test_coupon_alert_golden_without_product_link_uses_the_offer_link() -> None:
    lines = GOLDEN_A.splitlines()
    lines[4] = "🔗 Oferta: https://meli.la/x"
    assert _coupon(product_url=None) == "\n".join(lines)


def test_coupon_alert_golden_without_title() -> None:
    lines = GOLDEN_A.splitlines()
    lines[1] = 'Para "Monitor"'
    assert _coupon(offer_title="") == "\n".join(lines)


def test_coupon_alert_golden_over_max_scope_no_age() -> None:
    text = _coupon(
        wish_name='Monitor "34"',
        offer_title='LG 34" Curvo',
        discount="10% OFF",
        min_cents=7900,
        scope="Selecionados",
        offer_price_cents=151700,
        max_price_cents=150000,
        over_max=True,
        offer_age=None,
        product_url=None,
        offer_link="https://meli.la/y",
    )
    assert text.splitlines() == [
        "🎟️ Cupom Mercado Livre: OFFNOML — 10% OFF a partir de R$ 79,00, "
        "limite de R$ 40,00 em Selecionados",
        'Para "Monitor "34"": LG 34" Curvo',
        "💰 R$ 1.517,00 → R$ 40,00 de desconto (2,6%) → ~R$ 1.477,00 ⚠️ limite baixo "
        "(acima do seu limite de R$ 1.500,00)",
        "• pode não valer para todos os produtos",
        "🔗 Oferta: https://meli.la/y",
        "🎟️ Resgatar cupom: https://mercadolivre.com/sec/2U6U32Q",
    ]


def test_coupon_alert_without_discount_or_minimum() -> None:
    first = _coupon(discount="", min_cents=None, cap_cents=None).splitlines()[0]
    assert first == "🎟️ Cupom Mercado Livre: OFFNOML"


def test_coupon_alert_lists_several_codes() -> None:
    first = _coupon(codes=("ML10", "ML10B")).splitlines()[0]
    assert first.startswith("🎟️ Cupom Mercado Livre: ML10, ML10B — 15% OFF")


def test_format_age() -> None:
    assert format_age(timedelta(seconds=30)) == "1 min"
    assert format_age(timedelta(minutes=59)) == "59 min"
    assert format_age(timedelta(minutes=60)) == "1 h"
    assert format_age(timedelta(hours=5, minutes=50)) == "5 h"
    assert format_age(timedelta(minutes=-2)) == "1 min"


def test_format_saving_minimum_not_met() -> None:
    assert format_saving("10% OFF", 200000, None, 150000) == " (não vale: mínimo R$ 2.000,00)"


def test_format_saving_unparseable_discount_is_empty() -> None:
    assert format_saving("frete grátis", None, None, 150000) == ""


def test_rendered_text_is_returned_verbatim() -> None:
    assert format_alert(_msg(rendered="texto pronto")) == "texto pronto"


def test_coupon_line_one_code() -> None:
    from datetime import UTC, datetime

    from velkgram.alerting.domain.format import format_coupon_line
    from velkgram.alerting.domain.models import ActiveCoupon

    c = ActiveCoupon(1, 2, datetime(2026, 11, 4, tzinfo=UTC), "R$ 10 OFF", 4000, ("QIP98Q1ZXO",))
    assert (
        format_coupon_line(c)
        == "🎟️ Cupom ativo da loja: QIP98Q1ZXO — R$ 10 OFF a partir de R$ 40,00"
    )


def test_coupon_line_two_codes_and_no_discount_or_minimum() -> None:
    from datetime import UTC, datetime

    from velkgram.alerting.domain.format import format_coupon_line
    from velkgram.alerting.domain.models import ActiveCoupon

    at = datetime(2026, 11, 4, tzinfo=UTC)
    two = ActiveCoupon(1, 2, at, "10% OFF", None, ("AAA", "BBB"))
    assert format_coupon_line(two) == "🎟️ Cupom ativo da loja: AAA, BBB — 10% OFF"
    bare = ActiveCoupon(1, 2, at, "", None, ("AAA",))
    assert format_coupon_line(bare) == "🎟️ Cupom ativo da loja: AAA"


def test_alert_with_coupon_lines_places_them_after_the_price() -> None:
    out = format_alert(_msg(coupon_lines=("🎟️ Cupom ativo da loja: AAA",)))
    assert out.splitlines()[1:3] == ["R$ 1.299,90", "🎟️ Cupom ativo da loja: AAA"]


def test_over_max_suffix_on_the_price_line() -> None:
    out = format_alert(_msg(over_max_cents=100000))
    assert out.splitlines()[1] == "R$ 1.299,90 (acima do seu limite de R$ 1.000,00, mas há cupom)"
