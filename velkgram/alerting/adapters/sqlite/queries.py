"""SQLite read queries for reporting and the web. "Day" is the UTC date of `created_at`."""

import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from velkgram.alerting.adapters.sqlite.repository import COLUMNS, to_alert, to_iso
from velkgram.alerting.domain.models import Alert, SuppressionRule
from velkgram.alerting.ports.queries import DailyAlerts, DailySuppressions, LatencySample


def _bounds(since: date, until: date) -> tuple[str, str]:
    """Half-open [start of `since`, start of day after `until`) in UTC, index friendly."""
    start = datetime.combine(since, time.min, tzinfo=UTC)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=UTC)
    return to_iso(start), to_iso(end)


class SqliteAlertQueries:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def history(self, limit: int, offset: int) -> list[Alert]:
        rows = self._conn.execute(
            f"SELECT {COLUMNS} FROM alerts ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [to_alert(r) for r in rows]

    def recent_failures(self, limit: int) -> list[Alert]:
        rows = self._conn.execute(
            f"SELECT {COLUMNS} FROM alerts WHERE status IN ('failed', 'expired') "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [to_alert(r) for r in rows]

    def daily_alert_counts(self, since: date, until: date) -> list[DailyAlerts]:
        start, end = _bounds(since, until)
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, channel_id, COUNT(*) AS n, "
            "SUM(status IN ('failed', 'expired')) AS failures FROM alerts "
            "WHERE created_at >= ? AND created_at < ? GROUP BY day, channel_id "
            "ORDER BY day, channel_id",
            (start, end),
        ).fetchall()
        return [
            DailyAlerts(
                date.fromisoformat(r["day"]), int(r["channel_id"]), int(r["n"]), int(r["failures"])
            )
            for r in rows
        ]

    def daily_suppressions(self, since: date, until: date) -> list[DailySuppressions]:
        start, end = _bounds(since, until)
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, channel_id, rule, COUNT(*) AS n "
            "FROM alert_suppressions WHERE created_at >= ? AND created_at < ? "
            "GROUP BY day, channel_id, rule ORDER BY day, channel_id, rule",
            (start, end),
        ).fetchall()
        return [
            DailySuppressions(
                date.fromisoformat(r["day"]),
                int(r["channel_id"]),
                SuppressionRule(r["rule"]),
                int(r["n"]),
            )
            for r in rows
        ]

    def suppressed_messages(self, since: date, until: date) -> set[tuple[int, int]]:
        start, end = _bounds(since, until)
        rows = self._conn.execute(
            "SELECT DISTINCT channel_id, message_id FROM alert_suppressions "
            "WHERE created_at >= ? AND created_at < ?",
            (start, end),
        ).fetchall()
        return {(int(r["channel_id"]), int(r["message_id"])) for r in rows}

    def latency_samples(self, since: date, until: date) -> list[LatencySample]:
        start, end = _bounds(since, until)
        rows = self._conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, channel_id, latency_telegram_ms, "
            "latency_internal_ms FROM alerts WHERE created_at >= ? AND created_at < ? "
            "AND kind = 'offer' "
            "ORDER BY created_at, id",
            (start, end),
        ).fetchall()
        return [
            LatencySample(
                date.fromisoformat(r["day"]),
                int(r["channel_id"]),
                int(r["latency_telegram_ms"]),
                int(r["latency_internal_ms"]),
            )
            for r in rows
        ]
