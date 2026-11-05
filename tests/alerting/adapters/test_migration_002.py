import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from velkgram.alerting.domain.models import AlertKind
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = connect(tmp_path / "t.db")
    apply_migrations(c, ["velkgram.shared"])
    directory = files("velkgram.alerting") / "migrations"
    c.executescript((directory / "001_alerting.sql").read_text(encoding="utf-8"))
    c.execute(
        "INSERT INTO schema_migrations (package, name) "
        "VALUES ('velkgram.alerting', '001_alerting.sql')"
    )
    c.execute(
        "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
        "dedup_key, status, attempts, created_at, latency_telegram_ms, latency_internal_ms) "
        "VALUES (1, 2, 3, 100, 0, 'org:1:2:3', 'sent', 1, '2026-11-04T12:00:00.000000Z', 5, 6)"
    )
    for rule in ("origin", "wish_price", "wish_text"):
        c.execute(
            "INSERT INTO alert_suppressions VALUES (2, 3, 1, ?, 1, '2026-11-04T12:00:00.000000Z')",
            (rule,),
        )
    apply_migrations(c, ["velkgram.alerting"])
    return c


def test_existing_alerts_get_defaults(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT * FROM alerts").fetchone()
    assert row["kind"] == AlertKind.offer.value
    assert row["over_max"] == 0
    assert row["offer_channel_id"] is None
    assert row["offer_message_id"] is None
    assert row["payload"] is None
    assert row["dedup_key"] == "org:1:2:3"


def test_suppressions_kept_and_wish_coupon_accepted(conn: sqlite3.Connection) -> None:
    rules = [r[0] for r in conn.execute("SELECT rule FROM alert_suppressions ORDER BY rowid")]
    assert rules == ["origin", "wish_price", "wish_text"]
    conn.execute(
        "INSERT INTO alert_suppressions VALUES (2, 4, 1, 'wish_coupon', 1, '2026-11-04T12:00:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO alert_suppressions VALUES (2, 4, 1, 'bogus', 1, '2026-11-04T12:00:00Z')"
        )


def test_suppression_index_recreated_and_kind_checked(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "idx_alert_suppressions_created_at" in names
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE alerts SET kind = 'bogus'")
