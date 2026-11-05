import logging

import pytest

from tests.fakes.notifier import FakeNotifier
from velkgram.alerting import AlertMessage, send_with_retry
from velkgram.alerting.adapters.notify_log import LogNotifier

MSG = AlertMessage(
    wish_name="RTX 4060",
    text="oferta",
    price_cents=150000,
    channel_name="Promos",
    link=None,
    delayed_minutes=None,
)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_succeeds_first_try() -> None:
    notifier, sleep = FakeNotifier(), Sleeps()
    assert await send_with_retry(notifier, MSG, sleep=sleep) == (True, 1, None)
    assert notifier.sent == [MSG]
    assert sleep.delays == []


async def test_retries_then_succeeds() -> None:
    notifier, sleep = FakeNotifier(fail_times=2), Sleeps()
    assert await send_with_retry(notifier, MSG, sleep=sleep) == (True, 3, None)
    assert sleep.delays == [1.0, 3.0]


async def test_gives_up_after_three() -> None:
    notifier, sleep = FakeNotifier(fail_times=10), Sleeps()
    ok, attempts, error = await send_with_retry(notifier, MSG, sleep=sleep)
    assert (ok, attempts) == (False, 3)
    assert error is not None and "boom 3" in error
    assert notifier.sent == []
    assert sleep.delays == [1.0, 3.0]


async def test_attempt_timeout_counts_as_failure() -> None:
    notifier, sleep = FakeNotifier(delay_s=0.2), Sleeps()
    ok, attempts, error = await send_with_retry(notifier, MSG, sleep=sleep, attempt_timeout=0.01)
    assert (ok, attempts) == (False, 3)
    assert error is not None and "timeout" in error.lower()


async def test_unexpected_exception_counts_as_failure() -> None:
    class Broken:
        async def notify(self, message: AlertMessage) -> None:
            raise ValueError("weird")

        async def notify_system(self, text: str) -> None:
            return None

    ok, attempts, error = await send_with_retry(Broken(), MSG, sleep=Sleeps())
    assert (ok, attempts) == (False, 3)
    assert error is not None and "weird" in error


async def test_log_notifier_logs_alert_and_system(caplog: pytest.LogCaptureFixture) -> None:
    notifier = LogNotifier()
    with caplog.at_level(logging.INFO):
        await notifier.notify(MSG)
        await notifier.notify_system("ping")
    messages = [r.getMessage() for r in caplog.records]
    assert "alert_notified" in messages
    assert "system_notified" in messages
    alert = next(r for r in caplog.records if r.getMessage() == "alert_notified")
    assert "RTX 4060" in alert.text  # type: ignore[attr-defined]
