import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from velkgram.channels import ChannelCommands
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.shared.db import connect

CLOCK = FakeClock(datetime(2026, 11, 4, 12, 0, tzinfo=UTC))


def _client(tmp_path: Path) -> TestClient:
    return make_client(tmp_path, clock=CLOCK)


def _commands(tmp_path: Path, action: str, *args: object) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        cmds = ChannelCommands(SqliteChannelRepository(conn), CLOCK)
        getattr(cmds, action)(*args)
    finally:
        conn.close()


def test_add_channel_by_link_shows_pending(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/channels", data={"ref": "https://t.me/Promos_BR"})
    assert response.status_code == 303
    page = client.get("/channels")
    assert "@promos_br" in page.text
    assert "pendente" in page.text
    assert 'href="/channels"' in page.text


def test_add_rejects_numeric_id_with_message(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/channels", data={"ref": "-1001234567890"})
    assert response.status_code == 422
    assert "Use @canal ou um link t.me" in response.text
    assert "pendente" not in client.get("/channels").text


def test_error_channel_shows_reason(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    _commands(tmp_path, "fail", 1, "Canal privado <b>x</b>")
    page = client.get("/channels")
    assert "erro" in page.text
    assert "Canal privado &lt;b&gt;x&lt;/b&gt;" in page.text


def test_active_channel_shows_name_and_toggle_returns_row(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    _commands(tmp_path, "activate", 1, 99, "Promos BR")
    page = client.get("/channels")
    assert "Promos BR" in page.text
    assert "ativo" in page.text
    row = client.post("/channels/1/toggle")
    assert row.status_code == 200
    assert "<html" not in row.text
    assert "pausado" in row.text


def test_duplicate_add_shows_message(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    response = client.post("/channels", data={"ref": "t.me/promos_br"})
    assert response.status_code == 422
    assert "Canal já cadastrado" in response.text


def test_delete_removes_channel(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    assert client.post("/channels/1/delete").status_code == 303
    assert "@promos_br" not in client.get("/channels").text


def test_toggle_unknown_channel_is_404(tmp_path: Path) -> None:
    assert _client(tmp_path).post("/channels/42/toggle").status_code == 404


def test_requires_login(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False, clock=CLOCK)
    response = client.get("/channels")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_channel_delete_asks_for_confirmation_and_add_button_is_labelled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos"})
    page = client.get("/channels").text
    assert "hx-confirm=" in page
    assert "<span>Adicionar</span>" in page
    assert 'class="channel-list"' in page and "<table" not in page
    assert "Estado" not in page
    # the helper text sits below the row, so the button lines up with the input box
    field = page[page.index('class="field') : page.index("</div>", page.index('class="field'))]
    assert "helper" not in field and "@canal ou https://t.me/canal" in page


def test_channel_row_stacks_name_over_handle_with_a_switch_and_a_remove_menu(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    _commands(tmp_path, "activate", 1, 99, "Promos BR")
    page = client.get("/channels").text
    assert '<span class="channel-name">Promos BR</span>' in page
    assert '<span class="channel-handle muted">' in page
    switch = re.search(r'<input[^>]*aria-label="Ativo"[^>]*>', page)
    assert switch is not None
    assert 'aria-label="Ativo"' in switch.group(0) and "checked" in switch.group(0)
    assert 'hx-post="/channels/1/toggle"' in switch.group(0)
    assert 'aria-label="Mais ações"' in page
    menu = page[
        page.index('<menu id="channel-menu-1"') : page.index(
            "</menu>", page.index("channel-menu-1")
        )
    ]
    assert "Remover" in menu and "hx-confirm=" in menu
    assert 'action="/channels/1/delete"' in menu
    toggled = re.search(
        r'<input[^>]*aria-label="Ativo"[^>]*>', client.post("/channels/1/toggle").text
    )
    assert toggled is not None and "checked" not in toggled.group(0)


def test_channel_row_shows_when_the_last_message_arrived(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/channels", data={"ref": "@promos_br"})
    _commands(tmp_path, "activate", 1, -1001234567890, "Promos BR")
    assert "nenhuma mensagem ainda" in client.get("/channels").text
    conn = connect(make_settings(tmp_path).db_path)
    try:
        when = (CLOCK.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "INSERT INTO messages (channel_id, message_id, date, received_at, text, links, "
            "has_photo, source) VALUES (-1001234567890, 1, ?, ?, 't', '[]', 0, 'live')",
            (when, when),
        )
        conn.commit()
    finally:
        conn.close()
    assert "última mensagem há 5 min" in client.get("/channels").text
