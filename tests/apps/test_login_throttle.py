import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from tests.fakes.clock import FakeClock
from velkgram.apps.web.throttle import LoginThrottle


def test_parallel_login_burst_respects_limit() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    verifications = 0
    counter_lock = threading.Lock()

    def slow_wrong_password() -> bool:
        nonlocal verifications
        with counter_lock:
            verifications += 1
        time.sleep(0.02)
        return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: throttle.attempt(slow_wrong_password), range(20)))

    assert verifications == 5
    assert results.count("fail") == 5
    assert results.count("locked") == 15


def test_attempt_outcomes_and_reset() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    assert throttle.attempt(lambda: False) == "fail"
    assert throttle.attempt(lambda: True) == "ok"
    for _ in range(5):
        throttle.attempt(lambda: False)
    ran = False

    def verify() -> bool:
        nonlocal ran
        ran = True
        return True

    assert throttle.attempt(verify) == "locked"
    assert not ran


def test_each_username_has_its_own_counter() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    for _ in range(5):
        assert throttle.attempt(lambda: False, key="ana") == "fail"
    assert throttle.attempt(lambda: True, key="ana") == "locked"
    assert throttle.attempt(lambda: True, key="bia") == "ok"  # another user is not locked out


def test_many_usernames_together_trip_the_global_cap() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    for n in range(30):
        assert throttle.attempt(lambda: False, key=f"user{n}") == "fail"
    assert throttle.attempt(lambda: True, key="someone-new") == "locked"


def test_a_success_resets_only_that_username() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    for _ in range(4):
        throttle.attempt(lambda: False, key="ana")
        throttle.attempt(lambda: False, key="bia")
    assert throttle.attempt(lambda: True, key="ana") == "ok"
    for _ in range(4):
        assert throttle.attempt(lambda: False, key="ana") == "fail"
    assert throttle.attempt(lambda: False, key="bia") == "fail"  # her fifth failure
    assert throttle.attempt(lambda: True, key="bia") == "locked"


def test_the_key_table_stays_bounded() -> None:
    throttle = LoginThrottle(FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    for n in range(5000):
        throttle.attempt(lambda: True, key=f"u{n}")
    assert throttle.tracked_keys() <= 1000
