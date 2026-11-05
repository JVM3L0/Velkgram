"""Link helpers and pt-BR alert text."""

from velkgram.alerting.domain.models import AlertMessage
from velkgram.shared.deals import extract_coupons
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
    lines = [f"🔔 {msg.wish_name}", price]
    if msg.delayed_minutes is not None:
        lines.append(f"⏱ atrasado {msg.delayed_minutes} min")
    lines.append(f"via {msg.channel_name}")
    if msg.link:
        lines.append(msg.link)
    lines.append(msg.text[:_MAX_TEXT])
    return "\n".join(lines)


def format_coupon_alert(
    store_title: str,
    codes: tuple[str, ...],
    discount: str,
    min_cents: int | None,
    scope: str | None,
    wish_name: str,
    offer_price_cents: int,
    max_price_cents: int,
    over_max: bool,
    link: str,
) -> str:
    head = f"🎟️ Cupom {store_title}: {', '.join(codes)}"
    if discount:
        head += f" — {discount}"
    if min_cents is not None:
        head += f" a partir de {format_brl(min_cents)}"
    if scope:
        head += f" em {scope}"
    price = f'Para "{wish_name}": oferta de {format_brl(offer_price_cents)}'
    if over_max:
        price += f" (acima do seu limite de {format_brl(max_price_cents)})"
    lines = [head, price]
    if scope:
        lines.append("• pode não valer para todos os produtos")
    lines.append(link)
    return "\n".join(lines)
