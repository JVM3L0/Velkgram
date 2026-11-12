from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings, make_user_client, sender_of
from velkgram.shared.db import connect


def _chat(tmp_path: Path, username: str) -> int | None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        row = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


@pytest.fixture
def ana(tmp_path: Path) -> TestClient:
    make_client(tmp_path)
    return make_user_client(tmp_path, "ana")


def test_the_profile_requires_login(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.get("/perfil")
    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_the_profile_shows_the_username_and_current_chat(tmp_path: Path, ana: TestClient) -> None:
    ana.post("/perfil/telegram", data={"chat_id": "123456"})
    page = ana.get("/perfil").text
    assert "ana" in page and "123456" in page


def test_saving_a_telegram_id_stores_it_and_blank_clears_it(
    tmp_path: Path, ana: TestClient
) -> None:
    assert ana.post("/perfil/telegram", data={"chat_id": " 987654 "}).status_code == 303
    assert _chat(tmp_path, "ana") == 987654
    assert ana.post("/perfil/telegram", data={"chat_id": ""}).status_code == 303
    assert _chat(tmp_path, "ana") is None


@pytest.mark.parametrize("raw", ["abc", "-5", "0", "12.5", "9" * 25])
def test_an_invalid_telegram_id_is_rejected(tmp_path: Path, ana: TestClient, raw: str) -> None:
    response = ana.post("/perfil/telegram", data={"chat_id": raw})
    assert response.status_code == 422
    assert "id do Telegram" in response.text
    assert _chat(tmp_path, "ana") is None


def test_changing_the_password_needs_the_current_one(tmp_path: Path, ana: TestClient) -> None:
    wrong = ana.post(
        "/perfil/senha",
        data={"current": "errada-123", "new": "nova-senha-1", "repeat": "nova-senha-1"},
    )
    assert wrong.status_code == 422 and "Senha atual incorreta" in wrong.text


@pytest.mark.parametrize(
    ("new", "repeat", "message"),
    [("nova-senha-1", "outra-coisa-9", "não conferem"), ("curta", "curta", "ao menos 8")],
)
def test_the_new_password_must_match_and_be_strong(
    tmp_path: Path, ana: TestClient, new: str, repeat: str, message: str
) -> None:
    response = ana.post(
        "/perfil/senha", data={"current": "senha-forte-1", "new": new, "repeat": repeat}
    )
    assert response.status_code == 422 and message in response.text


def test_a_changed_password_works_at_the_next_login(tmp_path: Path, ana: TestClient) -> None:
    done = ana.post(
        "/perfil/senha",
        data={"current": "senha-forte-1", "new": "nova-senha-1", "repeat": "nova-senha-1"},
    )
    assert done.status_code == 303
    fresh = make_client(tmp_path, login=False)
    assert (
        fresh.post("/login", data={"username": "ana", "password": "senha-forte-1"}).status_code
        == 401
    )
    assert (
        fresh.post("/login", data={"username": "ana", "password": "nova-senha-1"}).status_code
        == 303
    )


def test_the_test_alert_needs_a_chat_first(tmp_path: Path, ana: TestClient) -> None:
    response = ana.post("/perfil/teste")
    assert response.status_code == 422
    assert "id do Telegram" in response.text
    assert sender_of(ana).chats == []


def test_the_test_alert_is_sent_to_the_users_chat(tmp_path: Path, ana: TestClient) -> None:
    ana.post("/perfil/telegram", data={"chat_id": "555"})
    response = ana.post("/perfil/teste")
    assert response.status_code == 303
    assert sender_of(ana).chats == [555]
    assert "Alerta de teste enviado" in ana.get(response.headers["location"]).text


@pytest.mark.parametrize(
    ("code", "message"),
    [("UserIsBlockedError", "Iniciar"), ("PeerIdInvalidError", "Iniciar"), ("Boom", "Boom")],
)
def test_a_failed_test_alert_explains_what_to_do(
    tmp_path: Path, ana: TestClient, code: str, message: str
) -> None:
    ana.post("/perfil/telegram", data={"chat_id": "555"})
    sender_of(ana).result = code
    response = ana.post("/perfil/teste")
    assert response.status_code == 502
    assert message in response.text
