"""In-memory login throttle (single user, so one global counter)."""

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from velkgram.shared.ports import Clock

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=5)


class LoginThrottle:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
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

    def attempt(self, verify: Callable[[], bool]) -> Literal["locked", "ok", "fail"]:
        """Check, verify and record atomically so a parallel burst cannot bypass the limit."""
        with self._lock:
            if self.is_locked():
                return "locked"
            if verify():
                self.reset()
                return "ok"
            self.record_failure()
            return "fail"
