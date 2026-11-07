"""Card thumbnails and the seen-in-channels / other-product chips."""

import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import T0, add_link, match, offer, put
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.shared.db import connect

NOW = T0 + timedelta(days=30)
OTHER_TITLE = "Produto diferente do mais frequente deste desejo"


def _client(tmp_path: Path) -> TestClient:
    client = make_client(tmp_path, clock=FakeClock(NOW))
    conn = connect(make_settings(tmp_path).db_path)
    try:
        for tid, name in ((1, "Promos BR"), (2, "Achados & Cia")):
            conn.execute(
                "INSERT INTO channels (id, ref, telegram_id, name, status, enabled, "
                "silent_after_hours, created_at) VALUES (?, ?, ?, ?, 'active', 1, 12, ?)",
                (tid, f"@c{tid}", tid, name, T0.isoformat()),
            )
        conn.commit()
    finally:
        conn.close()
    return client


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(make_settings(tmp_path).db_path)


def test_image_renders_for_https_with_lazy_and_no_referrer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    add_link(conn, "https://l/a", product_id="A", image_url="https://img.test/a.jpg")
    put(conn, offer(1, link="https://l/a"))
    conn.close()
    html = client.get("/").text
    assert 'class="offer-thumb"' in html
    assert 'src="https://img.test/a.jpg"' in html
    assert 'loading="lazy"' in html
    assert 'referrerpolicy="no-referrer"' in html


def test_image_not_rendered_without_url_or_when_not_https(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    add_link(conn, "https://l/a", product_id="A", image_url="http://img.test/a.jpg")
    add_link(conn, "https://l/b", product_id="B", image_url=None)
    put(conn, offer(1, link="https://l/a"), offer(2, link="https://l/b"))
    conn.close()
    assert "offer-thumb" not in client.get("/").text


def test_seen_in_channels_chip_lists_names(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    add_link(conn, "https://l/a1", product_id="A")
    add_link(conn, "https://l/a2", product_id="A")
    put(
        conn,
        offer(1, channel_id=1, link="https://l/a1", at=T0),
        offer(2, channel_id=2, link="https://l/a2", at=T0 + timedelta(hours=2)),
    )
    conn.close()
    html = client.get("/").text
    assert "visto em 2 canais" in html
    assert "Promos BR" in html and "Achados &amp; Cia" in html
    assert "title=" in html.split("visto em 2 canais")[0].rsplit("<span", 1)[1]


def test_single_channel_has_no_seen_chip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    put(conn, offer(1))
    conn.close()
    assert "visto em" not in client.get("/").text


def test_other_product_chip_on_product_page(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post(
        "/wishes/new",
        data={
            "name": "SSD",
            "required_terms": "ssd",
            "excluded_terms": "usado",
            "max_price": "300,00",
        },
    )
    conn = _conn(tmp_path)
    repo = SqliteOfferRepository(conn)
    for i, key in enumerate(["A", "A", "A", "B"], start=1):
        add_link(conn, f"https://l/{i}", product_id=key)
        o = offer(i, at=T0 + timedelta(days=i), price=1000 * i, link=f"https://l/{i}")
        put(conn, o)
        repo.add_match(match(1, o))
    conn.close()
    html = client.get("/wishes/1").text
    assert html.count(">outro produto<") == 1
    assert OTHER_TITLE in html


def test_produto_button_only_when_real_link(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = _conn(tmp_path)
    add_link(conn, "https://l/a", store="amazon", product_id="B0C8814GKB")
    add_link(conn, "https://l/b", store="amazon", product_id=None, kind="not_product")
    put(conn, offer(1, link="https://l/a"), offer(2, link="https://l/b"))
    conn.close()
    html = client.get("/").text
    assert html.count("<span>Produto</span>") == 1
    assert 'href="https://www.amazon.com.br/dp/B0C8814GKB"' in html
