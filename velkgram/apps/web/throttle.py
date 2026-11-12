"""In-memory login throttle: one counter per username plus a global cap.

The per-username counter stops guessing one account's password; the global cap stops a
password spray across many usernames. Both are in memory, so a restart clears them.
"""

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from velkgram.shared.ports import Clock

MAX_FAILURES = 5
MAX_GLOBAL_FAILURES = 30
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=5)
MAX_KEYS = 1000


class _Window:
    """Failures inside a sliding window, then a lockout once `limit` is reached."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._failures: list[datetime] = []
        self._locked_until: datetime | None = None

    def is_locked(self, now: datetime) -> bool:
        return self._locked_until is not None and now < self._locked_until

    def record_failure(self, now: datetime) -> None:
        self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW]
        self._failures.append(now)
        if len(self._failures) >= self._limit:
            self._locked_until = now + LOCKOUT
            self._failures.clear()

    def reset(self) -> None:
        self._failures.clear()
        self._locked_until = None

    def idle(self, now: datetime) -> bool:
        return not self.is_locked(now) and all(now - t >= FAILURE_WINDOW for t in self._failures)


class LoginThrottle:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._global = _Window(MAX_GLOBAL_FAILURES)
        self._keys: dict[str, _Window] = {}

    def tracked_keys(self) -> int:
        return len(self._keys)

    def _window(self, key: str, now: datetime) -> _Window:
        window = self._keys.get(key)
        if window is None:
            if len(self._keys) >= MAX_KEYS:
                self._prune(now)
            window = self._keys[key] = _Window(MAX_FAILURES)
        return window

    def _prune(self, now: datetime) -> None:
        for name in [k for k, w in self._keys.items() if w.idle(now)]:
            del self._keys[name]
        while len(self._keys) >= MAX_KEYS:  # still full of active keys: drop the oldest
            del self._keys[next(iter(self._keys))]

    def attempt(self, verify: Callable[[], bool], key: str = "") -> Literal["locked", "ok", "fail"]:
        """Check, verify and record atomically so a parallel burst cannot bypass the limit."""
        with self._lock:
            now = self._clock.now()
            window = self._window(key, now)
            if window.is_locked(now) or self._global.is_locked(now):
                return "locked"
            if verify():
                window.reset()
                return "ok"
            window.record_failure(now)
            self._global.record_failure(now)
            return "fail"
