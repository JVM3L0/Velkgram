"""In-memory login throttle (single user, so one global counter)."""

from datetime import datetime, timedelta

from velkgram.shared.ports import Clock

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=5)


class LoginThrottle:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._failures: list[datetime] = []
        self._locked_until: datetime | None = None

    def is_locked(self) -> bool:
        return self._locked_until is not None and self._clock.now() < self._locked_until

    def record_failure(self) -> None:
        now = self._clock.now()
        self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW]
        self._failures.append(now)
        if len(self._failures) >= MAX_FAILURES:
            self._locked_until = now + LOCKOUT
            self._failures.clear()

    def reset(self) -> None:
        self._failures.clear()
        self._locked_until = None
