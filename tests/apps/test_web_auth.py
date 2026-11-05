from pathlib import Path

import pytest

from tests.apps.web_support import make_client, make_settings
from velkgram.apps.web.main import create_app
from velkgram.shared.config import Settings


def test_requires_login_redirects(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.get("/wishes")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_correct_password_sets_session(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.post("/login", data={"password": "secret"})
    assert response.status_code == 303
    assert response.headers["location"] == "/wishes"
    assert client.get("/wishes").status_code == 200
    assert client.get("/").headers["location"] == "/wishes"


def test_login_wrong_password_shows_error(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.post("/login", data={"password": "nope"})
    assert response.status_code == 401
    assert "Senha incorreta" in response.text
    assert client.get("/wishes").status_code == 303


def test_logout_clears_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/logout").headers["location"] == "/login"
    assert client.get("/wishes").status_code == 303


def test_login_page_renders_form(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    assert "Entrar" in client.get("/login").text


@pytest.mark.parametrize("missing", ["web_secret_key", "web_password_hash"])
def test_create_app_fails_fast_without_web_secrets(tmp_path: Path, missing: str) -> None:
    base = make_settings(tmp_path)
    values = {
        "db_path": base.db_path,
        "web_password_hash": base.web_password_hash,
        "web_secret_key": base.web_secret_key,
        missing: None,
    }
    with pytest.raises(ValueError, match="WEB_"):
        create_app(Settings(**values))  # type: ignore[arg-type]
