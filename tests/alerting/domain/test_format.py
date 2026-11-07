from datetime import UTC, datetime, timedelta

from velkgram.alerting.domain.format import (
    extra_lines,
    format_age,
    format_alert,
    format_coupon_alert,
    format_coupon_line,
    format_saving,
    message_link,
    telegram_link,
)
from velkgram.alerting.domain.models import ActiveCoupon, AlertMessage
from velkgram.shared.events import MessageData

_NOW = datetime(2026, 11, 4, tzinfo=UTC)


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
    out = format_alert(_msg(price_cents=None, delayed_minutes=12))
    assert "⚠️ preço não identificado" in out
    assert "⏱ atrasado 12 min" in out


POST = (
    'Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A\n\n'
    "R$ 1517\n-CUPOM: FAVORITO\n\nhttps://meli.la/2ZeTaW5\n\n-Anúncio"
)
TITLE = 'Monitor Gamer LG UltraGear Curvo 34"- QuadHD 2K -34G600A'


def _rich(**kw: object) -> AlertMessage:
    base: dict[str, object] = {
        "wish_name": "Monitor",
        "text": POST,
        "title": TITLE,
        "body": POST.split("\n", 1)[1],
        "price_cents": 151700,
        "channel_name": "Promotom",
        "link": "https://meli.la/2ZeTaW5",
        "delayed_minutes": None,
        "store_title": "Mercado Livre",
    }
    base.update(kw)
    return AlertMessage(**base)  # type: ignore[arg-type]


def test_golden_full_post() -> None:
    assert format_alert(_rich()) == "\n".join(
        [
            "🔔 Monitor",
            TITLE,
            "💰 R$ 1.517,00 · Mercado Livre",
            "🎟️ Cupom no post: FAVORITO",
            "via Promotom",
            "https://meli.la/2ZeTaW5",
        ]
    )


def test_no_price_with_store() -> None:
    assert format_alert(_rich(price_cents=None)).splitlines()[2] == (
        "💰 ⚠️ preço não identificado · Mercado Livre"
    )


def test_unknown_store_has_no_separator() -> None:
    line = format_alert(_rich(store_title=None)).splitlines()[2]
    assert line == "💰 R$ 1.517,00"


def test_over_max_suffix_follows_the_store() -> None:
    line = format_alert(_rich(over_max_cents=140000)).splitlines()[2]
    assert line == (
        "💰 R$ 1.517,00 · Mercado Livre (acima do seu limite de R$ 1.400,00, mas há cupom)"
    )


def test_delay_line_comes_just_before_the_extra_lines() -> None:
    out = format_alert(_rich(delayed_minutes=7, body="Detalhe", text="x")).splitlines()
    assert out[-4:] == ["⏱ atrasado 7 min", "Detalhe", "via Promotom", "https://meli.la/2ZeTaW5"]


def test_empty_title_has_no_title_line() -> None:
    lines = format_alert(_rich(title="")).splitlines()
    assert lines[:2] == ["🔔 Monitor", "💰 R$ 1.517,00 · Mercado Livre"]


def test_several_post_coupons_share_one_line() -> None:
    text = "Teclado\nR$ 80\ncupom: AAA111\nCódigo: BBB222"
    out = format_alert(_rich(text=text, body="R$ 80\ncupom: AAA111\nCódigo: BBB222"))
    assert "🎟️ Cupom no post: AAA111, BBB222" in out.splitlines()


def test_active_coupon_lines_follow_the_post_coupon_line() -> None:
    out = format_alert(_rich(coupon_lines=("🎟️ Cupom ativo da loja: AAA",)))
    assert out.splitlines()[3:5] == ["🎟️ Cupom no post: FAVORITO", "🎟️ Cupom ativo da loja: AAA"]


def test_extra_lines_are_rendered() -> None:
    out = format_alert(_rich(body="Resgate cupom do anúncio"))
    assert "Resgate cupom do anúncio" in out.splitlines()


def test_extra_lines_keep_a_detail_line() -> None:
    assert extra_lines("Resgate cupom do anúncio", ()) == ("Resgate cupom do anúncio",)


def test_extra_lines_of_a_bare_post_are_empty() -> None:
    assert extra_lines("R$ 1517\n\nhttps://meli.la/2ZeTaW5\n-Anúncio", ()) == ()


def test_extra_lines_drop_coupon_code_lines_and_bullets() -> None:
    body = "-CUPOM: FAVORITO\n- Frete grátis\n🔗 https://x.com/a\n-"
    assert extra_lines(body, ("FAVORITO",)) == ("Frete grátis",)


def test_extra_lines_keep_at_most_three() -> None:
    assert extra_lines("\n".join(f"linha {i}" for i in range(5)), ()) == (
        "linha 0",
        "linha 1",
        "linha 2",
    )


def test_extra_lines_cut_one_long_line_to_the_budget() -> None:
    [line] = extra_lines("a" * 300, ())
    assert len(line) == 200
    assert line.endswith("…")


def test_extra_lines_stop_after_the_cut_line() -> None:
    first, second, *rest = extra_lines("a" * 150 + "\n" + "b" * 150 + "\n" + "c" * 10, ())
    assert first == "a" * 150
    assert second == "b" * 49 + "…"
    assert rest == []


def test_split_title_skips_emoji_only_lines() -> None:
    from velkgram.offers import split_title

    title, rest = split_title("🔥🔥🔥\nMonitor X\nDetalhe", None)
    assert (title, rest) == ("Monitor X", "Detalhe")
    assert extra_lines(rest, ()) == ("Detalhe",)


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


def test_coupon_alert_age_line_comes_before_the_scope_caveat() -> None:
    lines = _coupon(scope="Selecionados").splitlines()
    assert lines[2].startswith("💰 ")
    assert lines[3] == "📅 oferta postada há 5 h"
    assert lines[4] == "• pode não valer para todos os produtos"
    assert lines[5].startswith("🔗 Produto: ")
    assert lines[6].startswith("🎟️ Resgatar cupom: ")


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


def test_format_saving_price_zero_is_empty() -> None:
    assert format_saving("10% OFF", None, None, 0) == ""
    assert format_saving("10% OFF", 5000, None, 0) == ""


def test_format_alert_with_coupon_line_at_price_zero_does_not_raise() -> None:
    line = format_coupon_line(ActiveCoupon(-1, 1, _NOW, "10% OFF", None, ("AAA",)), 0)
    assert line.endswith("— 10% OFF")
    assert "AAA" in format_alert(_msg(price_cents=0, coupon_lines=(line,)))


def test_coupon_alert_with_offer_price_zero_does_not_raise() -> None:
    assert "💰 R$ 0,00" in _coupon(offer_price_cents=0)


def test_rendered_text_is_returned_verbatim() -> None:
    assert format_alert(_msg(rendered="texto pronto")) == "texto pronto"


def test_coupon_line_one_code() -> None:
    from datetime import UTC, datetime

    from velkgram.alerting.domain.format import format_coupon_line
    from velkgram.alerting.domain.models import ActiveCoupon

    c = ActiveCoupon(1, 2, datetime(2026, 11, 4, tzinfo=UTC), "R$ 10 OFF", 4000, ("QIP98Q1ZXO",))
    assert (
        format_coupon_line(c, 90000)
        == "🎟️ Cupom ativo da loja: QIP98Q1ZXO — R$ 10 OFF a partir de R$ 40,00"
        " → R$ 10,00 de desconto (1,1%) → ~R$ 890,00"
    )


def test_coupon_line_two_codes_and_no_discount_or_minimum() -> None:
    from datetime import UTC, datetime

    from velkgram.alerting.domain.format import format_coupon_line
    from velkgram.alerting.domain.models import ActiveCoupon

    at = datetime(2026, 11, 4, tzinfo=UTC)
    two = ActiveCoupon(1, 2, at, "10% OFF", None, ("AAA", "BBB"))
    assert format_coupon_line(two, 10000) == (
        "🎟️ Cupom ativo da loja: AAA, BBB — 10% OFF → R$ 10,00 de desconto (10,0%) → ~R$ 90,00"
    )
    bare = ActiveCoupon(1, 2, at, "", None, ("AAA",))
    assert format_coupon_line(bare, 10000) == "🎟️ Cupom ativo da loja: AAA"


def test_golden_active_coupon_line() -> None:
    from velkgram.alerting.domain.format import format_coupon_line
    from velkgram.alerting.domain.models import ActiveCoupon

    c = ActiveCoupon(
        1, 2, datetime(2026, 11, 4, tzinfo=UTC), "15% OFF", None, ("ESPECIALML",), cap_cents=4000
    )
    assert format_coupon_line(c, 151700) == (
        "🎟️ Cupom ativo da loja: ESPECIALML — 15% OFF, limite de R$ 40,00"
        " → R$ 40,00 de desconto (2,6%) → ~R$ 1.477,00 ⚠️ limite baixo"
    )


def test_extra_lines_stop_when_the_budget_is_used_exactly() -> None:
    assert extra_lines("a" * 100 + "\n" + "b" * 100 + "\n" + "c" * 50, ()) == (
        "a" * 100,
        "b" * 100,
    )


def test_extra_lines_drop_code_lines_ignoring_case() -> None:
    assert extra_lines("use o cupom favorito agora\nDetalhe", ("FAVORITO",)) == ("Detalhe",)
