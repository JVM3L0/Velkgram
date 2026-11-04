"""Pure text normalization shared by domain code (stdlib only)."""

import re
import unicodedata

_URL = re.compile(r"https?://\S+|t\.me/\S+")
_SPACE_CATEGORIES = frozenset({"So", "Sk", "Sm", "Pd", "Cf", "Cs"})


def normalize_text(text: str) -> str:
    text = _URL.sub(" ", text)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()
    spaced = "".join(" " if unicodedata.category(c) in _SPACE_CATEGORIES else c for c in stripped)
    return " ".join(spaced.split())
