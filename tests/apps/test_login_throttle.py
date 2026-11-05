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
