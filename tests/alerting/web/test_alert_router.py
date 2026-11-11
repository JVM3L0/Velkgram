import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.shared.db import connect

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CHANNEL = -1001234567890


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _seed(tmp_path: Path, alerts: list[tuple[int, int | None, str]]) -> None:
    """alerts: (message_id, price_cents, status); created_at grows with message_id."""
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO wishes (id, name, required_terms, excluded_terms, max_price_cents, "
            "enabled, created_at, updated_at) VALUES (1, 'Tênis <b>', '[]', '[]', 1000, 1, ?, ?)",
            (_iso(NOW), _iso(NOW)),
        )
        conn.execute(
            "INSERT INTO channels (id, ref, telegram_id, name, status, enabled, created_at) "
            "VALUES (1, '@promos', ?, 'Promos BR', 'active', 1, ?)",
            (CHANNEL, _iso(NOW)),
        )
        for message_id, price, status in alerts:
            conn.execute(
                "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
                "dedup_key, status, attempts, created_at, latency_telegram_ms, "
                "latency_internal_ms) VALUES (1, ?, ?, ?, ?, ?, ?, 1, ?, 120, 80)",
                (
                    CHANNEL,
                    message_id,
                    price,
                    price is None,
                    f"k{message_id}",
                    status,
                    _iso(NOW - timedelta(minutes=1000 - message_id)),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _client(tmp_path: Path) -> TestClient:
    return make_client(tmp_path, clock=FakeClock(NOW))


def test_alerts_page_shows_price_unknown_label(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, None, "sent"), (2, 12345, "failed")])
    page = client.get("/alerts")
    assert page.status_code == 200
    assert "preço não identificado" in page.text
    assert "R$ 123,45" in page.text
    assert "Tênis &lt;b&gt;" in page.text
    assert "Promos BR" in page.text
    assert "120" in page.text
    assert 'href="https://t.me/c/1234567890/2"' in page.text
    assert 'rel="noopener noreferrer"' in page.text
    assert 'target="_blank"' in page.text
    assert 'href="/alerts"' in page.text
    assert 'href="/status"' in page.text


def test_alerts_pagination(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(i, 1000, "sent") for i in range(1, 56)])
    first = client.get("/alerts")
    assert "t.me/c/1234567890/55" in first.text
    assert 't.me/c/1234567890/6"' in first.text
    assert 't.me/c/1234567890/5"' not in first.text
    second = client.get("/alerts?page=2")
    assert 't.me/c/1234567890/5"' in second.text
    assert 't.me/c/1234567890/55"' not in second.text
    assert 't.me/c/1234567890/6"' not in second.text
    assert client.get("/alerts?page=abc").text == first.text
    assert client.get("/alerts?page=0").text == first.text


def test_alerts_requires_login(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False, clock=FakeClock(NOW))
    assert client.get("/alerts").status_code == 303


def test_alert_status_labels_are_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(
        tmp_path,
        [(1, 1000, "sent"), (2, 1000, "failed"), (3, 1000, "pending"), (4, 1000, "expired")],
    )
    page = client.get("/alerts").text
    for label in ("enviado", "falhou", "pendente", "expirado"):
        assert label in page
    for raw in (">sent<", ">failed<", ">pending<", ">expired<"):
        assert raw not in page.replace(" ", "").replace("\n", "")


def test_alerts_mark_latency_line_hidden_on_compact(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 1000, "sent")])
    page = client.get("/alerts").text
    assert page.count("hide-compact") >= 1


def test_alerts_empty_state_has_no_list_and_links_to_wishes(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/alerts").text
    assert "Nenhum alerta ainda" in page
    assert "alert-card" not in page
    assert 'class="empty' in page
    assert 'href="/wishes"' in page


def test_alerts_with_rows_render_cards(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 100, "sent")])
    page = client.get("/alerts").text
    assert "alert-card" in page and "Nenhum alerta ainda" not in page


def _seed_kind(
    tmp_path: Path, kind: str, over_max: bool, dedup_key: str, message_id: int = 7
) -> None:
    _seed(tmp_path, [])
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
            "dedup_key, status, attempts, created_at, latency_telegram_ms, latency_internal_ms, "
            "kind, over_max) VALUES (1, ?, ?, 1000, 0, ?, 'sent', 1, ?, 120, 80, ?, ?)",
            (CHANNEL, message_id, dedup_key, _iso(NOW), kind, over_max),
        )
        conn.commit()
    finally:
        conn.close()


def test_coupon_alert_shows_cupom_chip_with_codes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed_kind(tmp_path, "coupon", False, "wcc:1:amazon:OFF10,PROMO5")
    page = client.get("/alerts").text
    assert "cupom" in page
    assert "OFF10" in page and "PROMO5" in page
    assert "acima do limite" not in page
    assert 'href="https://t.me/c/1234567890/7"' in page


def test_coupon_codes_with_html_are_escaped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed_kind(tmp_path, "coupon", False, "wcc:1:amazon:<b>X")
    assert "&lt;b&gt;X" in client.get("/alerts").text


def test_over_max_alert_shows_acima_do_limite_chip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed_kind(tmp_path, "offer", True, "wp:1:1000")
    page = client.get("/alerts").text
    assert "acima do limite" in page
    assert "cupom" not in page


def test_ordinary_alert_shows_neither_chip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 1000, "sent")])
    page = client.get("/alerts").text
    assert "acima do limite" not in page
    assert "cupom" not in page


def _seed_product_alerts(tmp_path: Path) -> None:
    """Offer alert on message 1 (real link), coupon alert on message 2 pointing at offer 3."""
    from tests.offers.adapters._queries_helpers import add_link, offer, put

    _seed(tmp_path, [(1, 1000, "sent")])
    conn = connect(make_settings(tmp_path).db_path)
    try:
        add_link(conn, "https://l/a", store="amazon", product_id="B0C8814GKB")
        add_link(conn, "https://l/b", store="kabum", product_id="123456")
        put(
            conn,
            offer(1, channel_id=CHANNEL, link="https://l/a"),
            offer(3, channel_id=CHANNEL, link="https://l/b"),
        )
        conn.execute(
            "INSERT INTO alerts (wish_id, channel_id, message_id, price_cents, price_unknown, "
            "dedup_key, status, attempts, created_at, latency_telegram_ms, latency_internal_ms, "
            "kind, offer_channel_id, offer_message_id) "
            "VALUES (1, ?, 2, 1000, 0, 'wcc:1:amazon:X', 'sent', 1, ?, 1, 1, 'coupon', ?, 3)",
            (CHANNEL, _iso(NOW), CHANNEL),
        )
        conn.commit()
    finally:
        conn.close()


def test_alerts_show_produto_button_for_offer_and_coupon_alerts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed_product_alerts(tmp_path)
    page = client.get("/alerts").text
    assert 'href="https://www.amazon.com.br/dp/B0C8814GKB"' in page
    assert 'href="https://www.kabum.com.br/produto/123456"' in page
    assert page.count("<span>Produto</span>") == 2  # one per alert card


def test_alerts_without_real_link_have_no_produto_button(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 1000, "sent")])
    assert "Produto" not in client.get("/alerts").text


def test_alerts_render_without_buttons_when_product_links_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(self: object, pairs: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(SqliteOfferQueries, "product_links", boom)
    client = _client(tmp_path)
    _seed_product_alerts(tmp_path)
    with caplog.at_level(logging.ERROR):
        page = client.get("/alerts")
    assert page.status_code == 200
    assert "Produto" not in page.text
    assert any(r.getMessage() == "product_links_failed" for r in caplog.records)
