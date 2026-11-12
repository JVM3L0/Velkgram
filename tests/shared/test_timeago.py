from datetime import timedelta

import pytest

from velkgram.shared.timeago import ago


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (5, "há 5\u00a0s"),
        (59, "há 59\u00a0s"),
        (60, "há 1\u00a0min"),
        (3599, "há 59\u00a0min"),
        (3600, "há 1\u00a0h"),
        (86399, "há 23\u00a0h"),
        (86400, "há 1\u00a0d"),
        (-3, "agora"),
    ],
)
def test_ago_uses_the_largest_unit(seconds: int, text: str) -> None:
    assert ago(timedelta(seconds=seconds)) == text
