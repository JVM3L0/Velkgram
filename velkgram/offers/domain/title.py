"""Offer title extraction (pure)."""

import unicodedata

from velkgram.shared.text import URL_PATTERN

MAX_TITLE = 140
FALLBACK_TITLE = "Oferta sem título"
STORE_TITLES = {
    "amazon": "Amazon",
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
    "magalu": "Magalu",
    "kabum": "KaBuM!",
    "aliexpress": "AliExpress",
    "pichau": "Pichau",
    "terabyte": "Terabyte",
    "casasbahia": "Casas Bahia",
    "americanas": "Americanas",
    "carrefour": "Carrefour",
    "netshoes": "Netshoes",
}
_DROPPED = frozenset({"So", "Sk", "Cs", "Co", "Me", "Cf"})


def _clean(line: str) -> str:
    line = URL_PATTERN.sub(" ", line)
    kept = "".join(c for c in line if unicodedata.category(c) not in _DROPPED and not "︀" <= c <= "️")
    return " ".join(kept.split())


def _truncate(line: str) -> str:
    if len(line) <= MAX_TITLE:
        return line
    cut = line.rfind(" ", 0, MAX_TITLE + 1)
    return line[:cut].rstrip() if cut > 0 else line[:MAX_TITLE]


def title_of(text: str, store: str | None) -> str:
    for raw in text.split("\n"):
        line = _clean(raw)
        if line:
            return _truncate(line)
    return STORE_TITLES.get(store or "", FALLBACK_TITLE)


def split_title(text: str, store: str | None) -> tuple[str, str]:
    """The title and the text after the title line ("" when no line qualifies)."""
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        if _clean(raw):
            return title_of(text, store), "\n".join(lines[i + 1 :])
    return title_of(text, store), ""


def store_title(slug: str) -> str:
    return STORE_TITLES.get(slug, slug)
