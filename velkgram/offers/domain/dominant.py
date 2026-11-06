"""The dominant product among a wish's matches (pure)."""

from collections import Counter
from collections.abc import Sequence

MIN_KEYED = 3
MIN_SHARE_PERCENT = 60


def dominant_from_counts(
    counts: Sequence[tuple[tuple[str, str], int]], keyed_total: int
) -> tuple[str, str] | None:
    """Apply the dominance rule to per-pair counts (e.g. from SQL, top first).

    Needs at least 3 keyed matches, a share of at least 60 %, and a strict lead
    over the runner-up.
    """
    if keyed_total < MIN_KEYED or not counts:
        return None
    ranked = sorted(counts, key=lambda item: item[1], reverse=True)
    top_key, top_count = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if top_count * 100 < MIN_SHARE_PERCENT * keyed_total or top_count <= runner_up:
        return None
    return top_key


def dominant_product(keys: Sequence[tuple[str, str] | None]) -> tuple[str, str] | None:
    counter = Counter(key for key in keys if key is not None)
    return dominant_from_counts(counter.most_common(), sum(counter.values()))
