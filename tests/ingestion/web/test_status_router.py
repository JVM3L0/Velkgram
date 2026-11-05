from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from velkgram.shared.db import connect

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _client(tmp_path: Path) -> TestClient:
    return make_client(tmp_path, clock=FakeClock(NOW))


def _channel(tmp_path: Path, *, created_at: datetime, last_message: datetime | None) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO channels (id, ref, telegram_id, name, status, enabled, "
            "silent_after_hours, created_at) VALUES (1, '@promos', -1001234567890, 'Promos BR', "
            "'active', 1, 12, ?)",
            (_iso(created_at),),
        )
        if last_message is not None:
            conn.execute(
                "INSERT INTO messages (channel_id, message_id, date, received_at, text, links, "
                "has_photo, source) VALUES (-1001234567890, 1, ?, ?, 't', '[]', 0, 'live')",
                (_iso(last_message), _iso(last_message)),
            )
        conn.commit()
    finally:
        conn.close()


def _heartbeat(
    tmp_path: Path,
    *,
    age_s: int,
    state: str = "connected",
    reason: str | None = None,
    messages: int = 10,
    alerts: int = 2,
) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO collector_heartbeat (id, last_seen, connection_state, fatal_reason, "
            "messages_seen, alerts_sent) VALUES (1, ?, ?, ?, ?, ?)",
            (_iso(NOW - timedelta(seconds=age_s)), state, reason, messages, alerts),
        )
        conn.commit()
    finally:
        conn.close()


def test_status_flags_silent_channel(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(days=5), last_message=NOW - timedelta(hours=13))
    page = client.get("/status")
    assert page.status_code == 200
    assert "Promos BR" in page.text
    assert "silencioso" in page.text


def test_status_recent_message_not_silent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(days=5), last_message=NOW - timedelta(hours=1))
    assert "silencioso (&gt;" not in client.get("/status").text


def test_status_new_channel_without_messages_not_silent_before_threshold(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(hours=2), last_message=None)
    page = client.get("/status")
    assert "Promos BR" in page.text
    assert "silencioso (&gt;" not in page.text


def test_status_new_channel_without_messages_silent_after_threshold(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(hours=13), last_message=None)
    assert "silencioso" in client.get("/status").text


def test_status_marks_stale_heartbeat(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=91)
    page = client.get("/status")
    assert "desatualizado" in page.text
    assert "conectado" in page.text


def test_status_fresh_heartbeat(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=90)
    assert "desatualizado" not in client.get("/status").text


def test_status_fatal_shows_reason_escaped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=5, state="fatal", reason="sessão <x>")
    page = client.get("/status")
    assert "erro fatal" in page.text
    assert "sessão &lt;x&gt;" in page.text


def test_status_without_heartbeat(tmp_path: Path) -> None:
    assert "coletor nunca rodou" in _client(tmp_path).get("/status").text


def test_status_lists_recent_failures_with_wish_name(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO wishes (id, name, required_terms, excluded_terms, max_price_cents, "
            "enabled, created_at, updated_at) VALUES (1, 'Tênis', '[]', '[]', 1000, 1, ?, ?)",
            (_iso(NOW), _iso(NOW)),
        )
        conn.execute(
            "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
            "dedup_key, status, attempts, created_at, latency_telegram_ms, latency_internal_ms) "
            "VALUES (1, -1001234567890, 1, 100, 0, 'k', 'failed', 3, ?, 1, 1)",
            (_iso(NOW),),
        )
        conn.commit()
    finally:
        conn.close()
    page = client.get("/status")
    assert "Tênis" in page.text
    assert "failed" in page.text or "falhou" in page.text


def test_status_compact_summary_counts_channels(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(days=5), last_message=NOW - timedelta(hours=13))
    page = client.get("/status").text
    assert "1 canal, 1 silencioso" in page


def test_status_pluralizes_message_and_alert_counts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=5, messages=1, alerts=1)
    page = client.get("/status").text
    assert ">1 mensagem<" in page and "1 mensagens" not in page
    assert "1 alerta enviado" in page and "1 alertas enviados" not in page


def test_status_plural_counts_above_one(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=5, messages=10, alerts=2)
    page = client.get("/status").text
    assert "10 mensagens" in page and "2 alertas enviados" in page


def test_status_explains_stale_heartbeat(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=91)
    assert "90 segundos" in client.get("/status").text


def test_status_empty_states_hide_table_heads(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/status").text
    assert "Nenhum canal ativo" in page and "Nenhuma falha recente" in page
    assert "<table" not in page
    assert 'class="empty' in page
    assert 'href="/channels"' in page


def test_status_with_a_channel_still_renders_the_table(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(days=5), last_message=NOW - timedelta(hours=1))
    assert "<table" in client.get("/status").text


def test_status_banner_reflects_collector_health(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "health-error" in client.get("/status").text  # never ran
    _heartbeat(tmp_path, age_s=30)
    page = client.get("/status").text
    assert "health-ok" in page and "Coletor funcionando" in page
    assert "(há 30 s)" in page  # relative time beside the absolute one


def test_status_banner_is_amber_when_stale_and_red_when_fatal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _heartbeat(tmp_path, age_s=600)
    page = client.get("/status").text
    assert "health-warning" in page and "Sem sinal há 10 min" in page
    conn = connect(make_settings(tmp_path).db_path)
    conn.execute(
        "UPDATE collector_heartbeat SET connection_state='fatal', last_seen=?", (_iso(NOW),)
    )
    conn.commit()
    conn.close()
    assert "Sessão inválida" in client.get("/status").text


def test_status_channel_rows_show_relative_last_message(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _channel(tmp_path, created_at=NOW - timedelta(days=5), last_message=NOW - timedelta(hours=2))
    assert "(há 2 h)" in client.get("/status").text
