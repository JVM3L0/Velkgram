from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings, make_user_client
from velkgram.shared.db import connect

CHANNEL = -1001234567890
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _seed(tmp_path: Path) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        for wish_id, name, owner in ((1, "AdminWish", 1), (2, "AnaWish", 2)):
            conn.execute(
                "INSERT INTO wishes (id, name, required_terms, excluded_terms, max_price_cents, "
                "enabled, created_at, updated_at, user_id) "
                "VALUES (?, ?, '[]', '[]', 1000, 1, ?, ?, ?)",
                (wish_id, name, NOW, NOW, owner),
            )
        for wish_id, message_id, status, error in (
            (1, 10, "sent", None),
            (2, 20, "failed", "no_chat"),
            (2, 21, "failed", "timeout after 10s"),
        ):
            conn.execute(
                "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
                "dedup_key, status, attempts, created_at, latency_telegram_ms, "
                "latency_internal_ms, last_error) VALUES (?, ?, ?, 100, 0, ?, ?, 1, ?, 1, 1, ?)",
                (wish_id, CHANNEL, message_id, f"k{message_id}", status, NOW, error),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clients(tmp_path: Path) -> tuple[TestClient, TestClient]:
    admin = make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    _seed(tmp_path)
    return admin, ana


def test_each_user_sees_only_the_alerts_of_their_own_wishes(
    clients: tuple[TestClient, TestClient],
) -> None:
    admin, ana = clients
    admin_page, ana_page = admin.get("/alerts").text, ana.get("/alerts").text
    assert "AdminWish" in admin_page and "AnaWish" not in admin_page
    assert "AnaWish" in ana_page and "AdminWish" not in ana_page
    link = "t.me/c/1234567890/"
    assert f"{link}10" in admin_page and f"{link}20" not in admin_page
    assert f"{link}20" in ana_page and f"{link}10" not in ana_page


def test_a_user_with_no_wishes_sees_the_empty_state(tmp_path: Path) -> None:
    make_client(tmp_path)
    make_user_client(tmp_path, "ana")  # user 2 owns the seeded wish
    bia = make_user_client(tmp_path, "bia")
    _seed(tmp_path)
    page = bia.get("/alerts")
    assert page.status_code == 200
    assert "Nenhum alerta ainda" in page.text


def test_a_missing_chat_is_explained_on_the_failed_alert(
    clients: tuple[TestClient, TestClient],
) -> None:
    _, ana = clients
    page = ana.get("/alerts").text
    assert page.count("Telegram não configurado") == 1  # only the no_chat alert, not the timeout
