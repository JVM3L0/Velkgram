import re
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


def _switch(html: str) -> str:
    return re.search(r'<input[^>]*aria-label="Ativo"[^>]*>', html).group(0)  # type: ignore[union-attr]


def test_channel_switch_is_on_when_enabled(tmp_path: Path) -> None:
    page = _setup(tmp_path).get("/channels").text
    assert "checked" in _switch(page) and 'aria-label="Ativo"' in _switch(page)
    assert "ativo" in page


def test_channel_switch_is_off_and_row_reads_pausado_when_paused(tmp_path: Path) -> None:
    row = _setup(tmp_path).post("/channels/1/toggle").text
    assert "checked" not in _switch(row)
    assert "pausado" in row


def test_channel_pending_state_switch_follows_enabled_only(tmp_path: Path) -> None:
    client = make_client(tmp_path, clock=CLOCK)
    client.post("/channels", data={"ref": "@promos_br"})
    page = client.get("/channels").text
    assert "pendente" in page
    assert "checked" in _switch(page)


def test_channel_error_state_shows_reason_and_keeps_switch(tmp_path: Path) -> None:
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
    assert "checked" in _switch(page)
