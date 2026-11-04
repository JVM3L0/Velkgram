"""SQLite alert repository. Datetimes are stored as UTC ISO-8601 strings."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from velkgram.alerting.domain.models import Alert, AlertStatus, SuppressionRule
from velkgram.shared.db import transaction

COLUMNS = (
    "id, wish_id, channel_id, message_id, price_cents, price_unknown, dedup_key, status, "
    "attempts, delayed_minutes, created_at, sent_at, latency_telegram_ms, "
    "latency_internal_ms, last_error"
)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _opt_int(value: object) -> int | None:
    return None if value is None else int(cast(int, value))


def to_alert(row: sqlite3.Row) -> Alert:
    return Alert(
        id=int(row["id"]),
        wish_id=int(row["wish_id"]),
        channel_id=int(row["channel_id"]),
        message_id=int(row["message_id"]),
        price_cents=_opt_int(row["price_cents"]),
        price_unknown=bool(row["price_unknown"]),
        dedup_keys=tuple(str(row["dedup_key"]).split()),
        status=AlertStatus(row["status"]),
        attempts=int(row["attempts"]),
        delayed_minutes=_opt_int(row["delayed_minutes"]),
        created_at=from_iso(row["created_at"]),
        sent_at=from_iso(row["sent_at"]) if row["sent_at"] is not None else None,
        latency_telegram_ms=int(row["latency_telegram_ms"]),
        latency_internal_ms=int(row["latency_internal_ms"]),
        last_error=row["last_error"],
    )


def _params(a: Alert) -> tuple[object, ...]:
    return (
        a.wish_id,
        a.channel_id,
        a.message_id,
        a.price_cents,
        int(a.price_unknown),
        " ".join(a.dedup_keys),
        a.status.value,
        a.attempts,
        a.delayed_minutes,
        to_iso(a.created_at),
        to_iso(a.sent_at) if a.sent_at is not None else None,
        a.latency_telegram_ms,
        a.latency_internal_ms,
        a.last_error,
    )


class SqliteAlertRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _select(self, where: str, params: tuple[object, ...]) -> list[Alert]:
        rows = self._conn.execute(
            f"SELECT {COLUMNS} FROM alerts WHERE {where} ORDER BY created_at, id", params
        ).fetchall()
        return [to_alert(r) for r in rows]

    def add(self, a: Alert) -> Alert:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, "
                "price_unknown, dedup_key, status, attempts, delayed_minutes, created_at, "
                "sent_at, latency_telegram_ms, latency_internal_ms, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _params(a),
            )
        return replace(a, id=cursor.lastrowid)

    def update(self, a: Alert) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE alerts SET wish_id = ?, channel_id = ?, message_id = ?, "
                "price_cents = ?, price_unknown = ?, dedup_key = ?, status = ?, attempts = ?, "
                "delayed_minutes = ?, created_at = ?, sent_at = ?, latency_telegram_ms = ?, "
                "latency_internal_ms = ?, last_error = ? WHERE id = ?",
                (*_params(a), a.id),
            )

    def add_suppression(
        self,
        channel_id: int,
        message_id: int,
        wish_id: int,
        rule: SuppressionRule,
        matched_alert_id: int,
        at: datetime,
    ) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO alert_suppressions "
                "(channel_id, message_id, wish_id, rule, matched_alert_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (channel_id, message_id, wish_id, rule.value, matched_alert_id, to_iso(at)),
            )

    def list_since(self, since: datetime) -> list[Alert]:
        return self._select("created_at >= ?", (to_iso(since),))

    def list_retryable(self, since: datetime, stuck_before: datetime) -> list[Alert]:
        return self._select(
            "created_at >= ? AND (status = 'failed' OR (status = 'pending' AND created_at < ?))",
            (to_iso(since), to_iso(stuck_before)),
        )

    def list_failed_before(self, before: datetime) -> list[Alert]:
        return self._select("status = 'failed' AND created_at < ?", (to_iso(before),))

    def has_alert_for_message(self, channel_id: int, message_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts WHERE channel_id = ? AND message_id = ? LIMIT 1",
            (channel_id, message_id),
        ).fetchone()
        return row is not None
