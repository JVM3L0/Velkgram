from pathlib import Path

from tests.apps.web_support import PASSWORD, make_client, make_settings
from velkgram.accounts import Role, UserCommands
from velkgram.accounts.adapters.sqlite.repository import SqliteUserRepository
from velkgram.apps.web.auth import hash_password, verify_password
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.db import connect


def _commands(tmp_path: Path) -> UserCommands:
    conn = connect(make_settings(tmp_path).db_path)
    return UserCommands(SqliteUserRepository(conn), SystemClock(), hash_password, verify_password)


def test_a_second_user_logs_in_with_their_own_credentials(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    _commands(tmp_path).create("ana", "senha-da-ana", Role.USER)
    response = client.post("/login", data={"username": "ANA", "password": "senha-da-ana"})
    assert response.status_code == 303
    assert client.get("/wishes").status_code == 200


def test_unknown_user_and_wrong_password_give_the_same_error(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    unknown = client.post("/login", data={"username": "ghost", "password": "whatever1"})
    wrong = client.post("/login", data={"username": "admin", "password": "whatever1"})
    assert (unknown.status_code, wrong.status_code) == (401, 401)
    assert "Usuário ou senha incorretos" in unknown.text
    assert "Usuário ou senha incorretos" in wrong.text


def test_login_without_a_username_fails(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 401


def test_a_disabled_user_loses_the_session_on_the_next_request(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    commands = _commands(tmp_path)
    ana = commands.create("ana", "senha-da-ana", Role.USER)
    client.post("/login", data={"username": "ana", "password": "senha-da-ana"})
    assert client.get("/wishes").status_code == 200
    commands.set_enabled(ana.id or 0, False)
    response = client.get("/wishes")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_the_admin_is_filled_from_the_environment_at_startup(tmp_path: Path) -> None:
    make_client(tmp_path, login=False)  # create_app seeds the admin from WEB_PASSWORD_HASH
    conn = connect(make_settings(tmp_path).db_path)
    admin = SqliteUserRepository(conn).get(1)
    assert admin is not None
    assert verify_password(admin.password_hash, PASSWORD)


def test_a_user_whose_row_vanished_is_logged_out(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    conn = connect(make_settings(tmp_path).db_path)
    conn.execute("UPDATE users SET enabled = 0")
    conn.commit()
    assert client.get("/wishes").status_code == 303
