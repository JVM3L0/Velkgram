from collections import Counter

import pytest

from velkgram.offers.domain.dominant import dominant_from_counts, dominant_product

A = ("amazon", "B0AAAAAAAA")
B = ("amazon", "B0BBBBBBBB")
C = ("kabum", "123")


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ([A, A, A, B], A),
        ([A, A, B, B], None),
        ([A, A], None),
        ([A, A, B, None, None], A),
        ([A, B, C], None),
        ([A, A, A], A),
        ([A, A, B, C], None),  # 50 % is below the 60 % bar
        ([None, None, None], None),
        ([], None),
    ],
)
def test_dominant_product_rule(
    keys: list[tuple[str, str] | None], expected: tuple[str, str] | None
) -> None:
    assert dominant_product(keys) == expected
    counts = Counter(k for k in keys if k is not None).most_common()
    assert dominant_from_counts(counts, sum(n for _, n in counts)) == expected


def test_dominant_from_counts_with_empty_counts() -> None:
    assert dominant_from_counts([], 0) is None


def test_dominant_from_counts_needs_lead_over_runner_up() -> None:
    assert dominant_from_counts([(A, 3), (B, 3)], 6) is None
    assert dominant_from_counts([(A, 4), (B, 2)], 6) == A
