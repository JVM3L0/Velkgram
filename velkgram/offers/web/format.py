"""Display formatting for the offers web views (pt-BR)."""

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from velkgram.offers.domain.suggest import suggest_terms
from velkgram.offers.domain.title import STORE_TITLES
from velkgram.offers.ports.queries import OfferCard

STORE_NAMES = STORE_TITLES
_PRICE_RE = re.compile(r"^(\d+|\d{1,3}(\.\d{3})+)(,\d{1,2})?$")


def brl(cents: int | None) -> str:
    """Format integer cents as "R$ 1.299,90"; None as the unknown-price text."""
    if cents is None:
        return "preço não identificado"
    reais, rest = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{rest:02d}"


SQLITE_MAX_INT = 2**63 - 1  # larger ints overflow SQLite bindings


def parse_price_cents(raw: str) -> int | None:
    """pt-BR decimal (`599,90`, `1.299,90`, `599`) to cents; None when malformed."""
    text = raw.strip()
    if not _PRICE_RE.match(text):
        return None
    whole, _, frac = text.replace(".", "").partition(",")
    cents = int(whole) * 100 + int(frac.ljust(2, "0") or "0")
    return cents if cents <= SQLITE_MAX_INT else None


def format_price(cents: int) -> str:
    """Wishlist form format: `599,90`, `1299,00`."""
    return f"{cents // 100},{cents % 100:02d}"


def relative_time(at: datetime, now: datetime, tz: ZoneInfo) -> str:
    """ "agora", "há N min", "há N h", "ontem HH:MM" or "DD/MM HH:MM", local to `tz`."""
    delta = now - at
    if delta < timedelta(minutes=1):
        return "agora"
    local, local_now = at.astimezone(tz), now.astimezone(tz)
    if local.date() == local_now.date():
        minutes = int(delta.total_seconds() // 60)
        return f"há {minutes} min" if minutes < 60 else f"há {minutes // 60} h"
    if local.date() == local_now.date() - timedelta(days=1):
        return f"ontem {local:%H:%M}"
    return f"{local:%d/%m %H:%M}"


def safe_href(url: str | None) -> str | None:
    """The URL only when its scheme is http or https (never javascript:, tg:, data:)."""
    if url is None:
        return None
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:  # e.g. "http://[::1" — a garbled link must not break the page
        return None
    return url if scheme in ("http", "https") else None


def follow_url(card: OfferCard) -> str:
    """The new-wish form prefilled from an offer: name, suggested terms and price."""
    params: dict[str, object] = {
        "name": card.title,
        "required": list(suggest_terms(card.title)),
    }
    if card.price_cents is not None:
        params["max_price"] = format_price(card.price_cents)
    return "/wishes/new?" + urlencode(params, doseq=True)
