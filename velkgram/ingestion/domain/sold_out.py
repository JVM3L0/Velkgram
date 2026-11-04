"""Sold-out hint detection for edited messages."""

from velkgram.shared.text import normalize_text

_MARKERS = ("esgotado", "esgotou", "acabou", "encerrada", "encerrado", "indisponivel")


def detect_sold_out(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in _MARKERS)
