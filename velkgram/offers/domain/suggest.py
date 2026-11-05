"""Suggested wish terms from an offer title (pure)."""

import re

MAX_TERMS = 5
STOPWORDS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "para",
        "pra",
        "com",
        "sem",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "por",
        "e",
        "ou",
        "um",
        "uma",
        "até",
        "off",
        "frete",
        "grátis",
        "gratis",
        "cupom",
        "promoção",
        "promocao",
        "oferta",
        "hoje",
        "só",
        "so",
        "apenas",
        "link",
        "aqui",
        "r$",
    ]
)
_STRIP = ".,;:!?()[]{}\"'*"
_PRICE_LEADS = frozenset({"r$", "por", "só", "apenas"})
_DECIMAL_PRICE = re.compile(r",\d{2}")


def _tokens(title: str) -> list[tuple[str, bool]]:
    result: list[tuple[str, bool]] = []
    previous = ""
    for raw in title.split():
        token = raw.strip(_STRIP)
        if not token:
            continue
        lowered = token.lower()
        is_price = (
            lowered.startswith("r$")
            or previous in _PRICE_LEADS
            or _DECIMAL_PRICE.search(token) is not None
        )
        previous = lowered
        keep = (
            not is_price
            and not lowered.endswith("%")
            and lowered not in STOPWORDS
            and any(c.isalnum() for c in lowered)
        )
        if keep:
            result.append((lowered, any(c.isdigit() for c in lowered)))
    return result


def suggest_terms(title: str) -> tuple[str, ...]:
    tokens = _tokens(title)
    ordered = [t for t, digit in tokens if digit] + [t for t, digit in tokens if not digit]
    return tuple(dict.fromkeys(ordered))[:MAX_TERMS]
