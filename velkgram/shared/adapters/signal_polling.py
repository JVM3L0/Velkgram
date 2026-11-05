"""ChangeSignal that polls `state_versions`."""

import sqlite3

from velkgram.shared.db import read_versions


class PollingChangeSignal:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # Seeded now: the starting state is not a change (startup reloads everything itself).
        self._seen: dict[str, int] = read_versions(conn)

    async def changed(self) -> dict[str, int]:
        current = read_versions(self._conn)
        diff = {n: v for n, v in current.items() if self._seen.get(n) != v}
        self._seen = current
        return diff
