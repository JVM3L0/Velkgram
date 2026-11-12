import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings, make_user_client, sender_of
from velkgram.shared.db import connect


def _row(tmp_path: Path, username: str) -> tuple[object, ...] | None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        row = conn.execute(
            "SELECT id, role, enabled, telegram_chat_id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else tuple(row)


def _password_in(page: str) -> str:
    match = re.search(r"data-generated-password>([^<]+)<", page)
    assert match is not None, "the generated password must be shown"
    return match.group(1).strip()


@pytest.fixture
def admin(tmp_path: Path) -> TestClient:
    return make_client(tmp_path)


def test_regular_users_cannot_reach_the_user_admin_routes(tmp_path: Path) -> None:
    make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    assert ana.get("/usuarios").status_code == 403
    assert ana.post("/usuarios/novo", data={"username": "x1x", "role": "user"}).status_code == 403
    assert ana.post("/usuarios/1/senha").status_code == 403
    assert ana.post("/usuarios/1/ativo", data={"enabled": "0"}).status_code == 403
    assert ana.post("/usuarios/1/telegram", data={"chat_id": "5"}).status_code == 403


def test_the_list_shows_every_user_with_role_and_status(tmp_path: Path, admin: TestClient) -> None:
    make_user_client(tmp_path, "ana")
    page = admin.get("/usuarios").text
    assert "admin" in page and "ana" in page


def test_creating_a_user_shows_the_generated_password_once(
    tmp_path: Path, admin: TestClient
) -> None:
    response = admin.post("/usuarios/novo", data={"username": "bia", "role": "user"})
    assert response.status_code == 200
    password = _password_in(response.text)
    assert len(password) >= 12
    assert "data-generated-password" not in admin.get("/usuarios").text  # never shown again
    fresh = make_client(tmp_path, login=False)
    assert fresh.post("/login", data={"username": "bia", "password": password}).status_code == 303
    row = _row(tmp_path, "bia")
    assert row is not None and row[1:] == ("user", 1, None)


def test_an_admin_role_can_be_chosen(tmp_path: Path, admin: TestClient) -> None:
    admin.post("/usuarios/novo", data={"username": "chefe", "role": "admin"})
    row = _row(tmp_path, "chefe")
    assert row is not None and row[1] == "admin"


@pytest.mark.parametrize(
    ("username", "role", "message"),
    [("ab", "user", "Usuário"), ("admin", "user", "já existe"), ("ok-name", "root", "Perfil")],
)
def test_invalid_new_users_are_rejected(
    tmp_path: Path, admin: TestClient, username: str, role: str, message: str
) -> None:
    response = admin.post("/usuarios/novo", data={"username": username, "role": role})
    assert response.status_code == 422
    assert message in response.text


def test_resetting_a_password_shows_a_new_one_and_drops_the_old(
    tmp_path: Path, admin: TestClient
) -> None:
    make_user_client(tmp_path, "ana", "senha-forte-1")
    row = _row(tmp_path, "ana")
    assert row is not None
    response = admin.post(f"/usuarios/{row[0]}/senha")
    assert response.status_code == 200
    new = _password_in(response.text)
    fresh = make_client(tmp_path, login=False)
    assert (
        fresh.post("/login", data={"username": "ana", "password": "senha-forte-1"}).status_code
        == 401
    )
    assert fresh.post("/login", data={"username": "ana", "password": new}).status_code == 303


def test_disabling_a_user_blocks_their_login_and_enabling_restores_it(
    tmp_path: Path, admin: TestClient
) -> None:
    make_user_client(tmp_path, "ana", "senha-forte-1")
    row = _row(tmp_path, "ana")
    assert row is not None
    assert admin.post(f"/usuarios/{row[0]}/ativo", data={"enabled": "0"}).status_code == 303
    fresh = make_client(tmp_path, login=False)
    assert (
        fresh.post("/login", data={"username": "ana", "password": "senha-forte-1"}).status_code
        == 401
    )
    assert admin.post(f"/usuarios/{row[0]}/ativo", data={"enabled": "1"}).status_code == 303
    assert (
        fresh.post("/login", data={"username": "ana", "password": "senha-forte-1"}).status_code
        == 303
    )


def test_the_last_admin_cannot_be_disabled(tmp_path: Path, admin: TestClient) -> None:
    response = admin.post("/usuarios/1/ativo", data={"enabled": "0"})
    assert response.status_code == 422
    assert "administrador" in response.text
    row = _row(tmp_path, "admin")
    assert row is not None and row[2] == 1


def test_the_admin_can_set_a_users_telegram_id(tmp_path: Path, admin: TestClient) -> None:
    make_user_client(tmp_path, "ana")
    row = _row(tmp_path, "ana")
    assert row is not None
    assert admin.post(f"/usuarios/{row[0]}/telegram", data={"chat_id": "4242"}).status_code == 303
    after = _row(tmp_path, "ana")
    assert after is not None and after[3] == 4242
    bad = admin.post(f"/usuarios/{row[0]}/telegram", data={"chat_id": "nope"})
    assert bad.status_code == 422


def test_unknown_user_ids_are_404(admin: TestClient) -> None:
    assert admin.post("/usuarios/999/senha").status_code == 404
    assert admin.post("/usuarios/999/ativo", data={"enabled": "0"}).status_code == 404
    assert admin.post("/usuarios/999/telegram", data={"chat_id": "5"}).status_code == 404


def _set_chat(admin: TestClient, tmp_path: Path, username: str, chat: str) -> int:
    row = _row(tmp_path, username)
    assert row is not None
    admin.post(f"/usuarios/{row[0]}/telegram", data={"chat_id": chat})
    return int(str(row[0]))


def test_regular_users_cannot_broadcast_a_test(tmp_path: Path) -> None:
    make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    assert ana.post("/usuarios/teste").status_code == 403
    assert sender_of(ana).chats == []


def test_the_test_goes_to_every_enabled_user_with_a_chat(tmp_path: Path, admin: TestClient) -> None:
    make_user_client(tmp_path, "ana")
    make_user_client(tmp_path, "bia")
    make_user_client(tmp_path, "cris")
    admin.post("/perfil/telegram", data={"chat_id": "100"})
    _set_chat(admin, tmp_path, "ana", "200")
    _set_chat(admin, tmp_path, "cris", "400")
    cris = _row(tmp_path, "cris")
    assert cris is not None
    admin.post(f"/usuarios/{cris[0]}/ativo", data={"enabled": "0"})  # disabled: left out
    response = admin.post("/usuarios/teste")
    assert response.status_code == 200
    assert sender_of(admin).chats == [100, 200]
    page = response.text
    assert page.count("enviado") >= 2
    assert "bia" in page and "sem id do Telegram" in page  # tells who is missing
    results = page.split("Resultado do teste")[1].split("</article>")[0]
    assert "ana" in results and "cris" not in results  # a disabled user is not tested


def test_failures_are_reported_per_user_with_what_to_do(tmp_path: Path, admin: TestClient) -> None:
    make_user_client(tmp_path, "ana")
    admin.post("/perfil/telegram", data={"chat_id": "100"})
    _set_chat(admin, tmp_path, "ana", "200")
    sender_of(admin).results = {200: "needs_start"}
    page = admin.post("/usuarios/teste").text
    assert "Iniciar" in page  # ana never pressed Start
    assert page.count("enviado") >= 1  # the admin still got theirs


def test_the_broadcast_needs_at_least_one_chat(tmp_path: Path, admin: TestClient) -> None:
    make_user_client(tmp_path, "ana")
    row = _row(tmp_path, "admin")
    assert row is not None and row[3] is None
    response = admin.post("/usuarios/teste")
    assert response.status_code == 422
    assert "id do Telegram" in response.text
    assert sender_of(admin).chats == []
