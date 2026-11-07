"""Link helpers and pt-BR alert text."""

from datetime import timedelta

from velkgram.alerting.domain.models import ActiveCoupon, AlertMessage
from velkgram.shared.deals import coupon_saving, extract_coupons, min_not_met
from velkgram.shared.events import MessageData

_MAX_TEXT = 300


def telegram_link(channel_id: int, message_id: int) -> str:
    return f"https://t.me/c/{str(channel_id)[4:]}/{message_id}"


def message_link(m: MessageData) -> str:
    return m.links[0] if m.links else telegram_link(m.channel_id, m.message_id)


def format_brl(cents: int) -> str:
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def format_alert(msg: AlertMessage) -> str:
    if msg.rendered is not None:
        return msg.rendered
    price = (
        format_brl(msg.price_cents) if msg.price_cents is not None else "⚠️ preço não identificado"
    )
    codes = extract_coupons(msg.text)
    if codes:
        price += f" com {'cupom' if len(codes) == 1 else 'cupons'} {', '.join(codes)}"
    if msg.over_max_cents is not None:
        price += f" (acima do seu limite de {format_brl(msg.over_max_cents)}, mas há cupom)"
    lines = [f"🔔 {msg.wish_name}", price, *msg.coupon_lines]
    if msg.delayed_minutes is not None:
        lines.append(f"⏱ atrasado {msg.delayed_minutes} min")
    lines.append(f"via {msg.channel_name}")
    if msg.link:
        lines.append(msg.link)
    lines.append(msg.text[:_MAX_TEXT])
    return "\n".join(lines)


def format_coupon_line(c: ActiveCoupon) -> str:
    line = f"🎟️ Cupom ativo da loja: {', '.join(c.codes)}"
    if c.discount:
        line += f" — {c.discount}"
    if c.min_cents is not None:
        line += f" a partir de {format_brl(c.min_cents)}"
    return line


def format_saving(
    discount: str, min_cents: int | None, cap_cents: int | None, price_cents: int
) -> str:
    """The saving suffix of a coupon line: what it takes off the price, or why it doesn't apply."""
    if min_not_met(min_cents, price_cents):
        assert min_cents is not None
        return f" (não vale: mínimo {format_brl(min_cents)})"
    saving = coupon_saving(discount, min_cents, cap_cents, price_cents)
    if saving is None:
        return ""
    percent = f"{saving.cents * 100 / price_cents:.1f}".replace(".", ",")
    text = (
        f" → {format_brl(saving.cents)} de desconto ({percent}%)"
        f" → ~{format_brl(price_cents - saving.cents)}"
    )
    return text + " ⚠️ limite baixo" if saving.low else text


def format_age(age: timedelta) -> str:
    """A short age: minutes under an hour, whole hours (rounded down) beyond."""
    minutes = max(0, int(age.total_seconds() // 60))
    if minutes < 60:
        return f"{max(1, minutes)} min"
    return f"{minutes // 60} h"


def format_coupon_alert(
    *,
    store_title: str,
    codes: tuple[str, ...],
    discount: str,
    min_cents: int | None,
    cap_cents: int | None,
    scope: str | None,
    wish_name: str,
    offer_title: str,
    offer_price_cents: int,
    max_price_cents: int,
    over_max: bool,
    offer_age: timedelta | None,
    product_url: str | None,
    offer_link: str,
    coupon_link: str,
) -> str:
    head = f"🎟️ Cupom {store_title}: {', '.join(codes)}"
    if discount:
        head += f" — {discount}"
    if min_cents is not None:
        head += f" a partir de {format_brl(min_cents)}"
    if cap_cents is not None:
        head += f", limite de {format_brl(cap_cents)}"
    if scope:
        head += f" em {scope}"
    wish_line = f'Para "{wish_name}"' + (f": {offer_title}" if offer_title else "")
    price = f"💰 {format_brl(offer_price_cents)}"
    price += format_saving(discount, min_cents, cap_cents, offer_price_cents)
    if over_max:
        price += f" (acima do seu limite de {format_brl(max_price_cents)})"
    lines = [head, wish_line, price]
    if scope:
        lines.append("• pode não valer para todos os produtos")
    if offer_age is not None:
        lines.append(f"📅 oferta postada há {format_age(offer_age)}")
    lines.append(f"🔗 Produto: {product_url}" if product_url else f"🔗 Oferta: {offer_link}")
    lines.append(f"🎟️ Resgatar cupom: {coupon_link}")
    return "\n".join(lines)
