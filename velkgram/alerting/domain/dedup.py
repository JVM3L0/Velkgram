"""Dedup keys and the in-memory suppression cache."""

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta

from velkgram.alerting.domain.models import SuppressionRule

DedupKey = tuple[SuppressionRule, str]

_PREFIX_RULES = {
    "org:": SuppressionRule.origin,
    "wp:": SuppressionRule.wish_price,
    "wt:": SuppressionRule.wish_text,
}


def origin_key(
    wish_id: int,
    channel_id: int,
    message_id: int,
    fwd_channel_id: int | None,
    fwd_message_id: int | None,
) -> str:
    if fwd_channel_id is not None and fwd_message_id is not None:
        return f"org:{wish_id}:{fwd_channel_id}:{fwd_message_id}"
    return f"org:{wish_id}:{channel_id}:{message_id}"


def price_key(wish_id: int, cents: int) -> str:
    return f"wp:{wish_id}:{cents}"


def text_key(wish_id: int, normalized_text: str) -> str:
    digest = hashlib.sha1(normalized_text.encode(), usedforsecurity=False).hexdigest()
    return f"wt:{wish_id}:{digest}"


def rule_for_key(key: str) -> SuppressionRule:
    for prefix, rule in _PREFIX_RULES.items():
        if key.startswith(prefix):
            return rule
    raise ValueError(f"unknown dedup key: {key}")


class DedupCache:
    def __init__(self, window: timedelta) -> None:
        self._window = window
        self._entries: dict[DedupKey, tuple[int, datetime]] = {}

    def find(self, keys: Sequence[DedupKey], now: datetime) -> tuple[SuppressionRule, int] | None:
        for key in keys:
            entry = self._entries.get(key)
            if entry is not None and now - entry[1] <= self._window:
                return key[0], entry[0]
        return None

    def remember(self, keys: Sequence[DedupKey], alert_id: int, at: datetime) -> None:
        for key in keys:
            self._entries[key] = (alert_id, at)

    def prune(self, now: datetime) -> None:
        self._entries = {k: v for k, v in self._entries.items() if now - v[1] <= self._window}
