from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from velkgram.channels import ChannelCommands
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.shared.db import connect

CLOCK = FakeClock(datetime(2026, 11, 4, 12, 0, tzinfo=UTC))


def _setup(tmp_path: Path) -> TestClient:
    client = make_client(tmp_path, clock=CLOCK)
    client.post("/channels", data={"ref": "@promos_br"})
    conn = connect(make_settings(tmp_path).db_path)
    try:
        ChannelCommands(SqliteChannelRepository(conn), CLOCK).activate(1, 99, "Promos BR")
    finally:
        conn.close()
    return client


def _button_label(html: str) -> str:
    start = html.index("hx-post")
    return html[start : html.index("</button>", start)]


def test_channel_toggle_reads_pausar_when_enabled(tmp_path: Path) -> None:
    page = _setup(tmp_path).get("/channels").text
    assert "Pausar" in _button_label(page)
    assert "Retomar" not in _button_label(page)
    assert "ativo" in page


def test_channel_toggle_reads_retomar_when_paused(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    row = client.post("/channels/1/toggle").text
    assert "Retomar" in _button_label(row)
    assert "pausado" in row
    assert "Pausar" not in row


def test_channel_pending_state_toggle_follows_enabled_only(tmp_path: Path) -> None:
    client = make_client(tmp_path, clock=CLOCK)
    client.post("/channels", data={"ref": "@promos_br"})
    page = client.get("/channels").text
    assert "pendente" in page
    assert "Pausar" in _button_label(page)


def test_channel_error_state_shows_reason_and_keeps_toggle(tmp_path: Path) -> None:
    client = make_client(tmp_path, clock=CLOCK)
    client.post("/channels", data={"ref": "@promos_br"})
    conn = connect(make_settings(tmp_path).db_path)
    try:
        ChannelCommands(SqliteChannelRepository(conn), CLOCK).fail(1, "Canal privado")
    finally:
        conn.close()
    page = client.get("/channels").text
    assert "erro: " in page
    assert "Canal privado" in page
    assert "Pausar" in _button_label(page)
