import pytest

from tests import timing


def test_a_slow_run_fails_where_timing_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timing, "ENFORCE_TIMING", True)
    timing.within(0.1, 0.5, "fast")
    with pytest.raises(AssertionError, match="slow"):
        timing.within(0.9, 0.5, "slow")


def test_a_slow_run_is_ignored_on_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timing, "ENFORCE_TIMING", False)
    timing.within(99.0, 0.5, "slow")  # no assertion: a shared runner's speed is noise
