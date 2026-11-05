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
