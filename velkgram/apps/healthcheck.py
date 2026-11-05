"""Container healthcheck: exit 0 only if the collector heartbeat is fresh and not fatal."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta

from velkgram.ingestion import Heartbeat
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.shared.config import load_settings

MAX_AGE = timedelta(seconds=90)


def healthcheck(h: Heartbeat | None, now: datetime) -> int:
    if h is None or h.connection_state == "fatal":
        return 1
    return 0 if now - h.last_seen < MAX_AGE else 1


def main() -> int:
    path = load_settings(os.environ).db_path
    if not path.exists():
        return 1
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            heartbeat = SqliteIngestionQueries(conn).heartbeat()
        finally:
            conn.close()
    except sqlite3.Error:
        return 1
    return healthcheck(heartbeat, datetime.now(UTC))


if __name__ == "__main__":
    raise SystemExit(main())
