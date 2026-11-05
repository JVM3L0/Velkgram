"""Term matching over already-normalized text."""

import re
from functools import lru_cache

from velkgram.alerting.domain.models import WishView


@lru_cache(maxsize=4096)
def _pattern(alternative: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(alternative)}(?!\w)")


def _found(alternative: str, text: str) -> bool:
    return _pattern(alternative).search(text) is not None


def matches_terms(wish: WishView, normalized_text: str) -> bool:
    if not all(any(_found(alt, normalized_text) for alt in group) for group in wish.required):
        return False
    return not any(_found(alt, normalized_text) for alt in wish.excluded)
