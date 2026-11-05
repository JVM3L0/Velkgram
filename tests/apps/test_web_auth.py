from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
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
    assert response.headers["location"] == "/"
    assert client.get("/wishes").status_code == 200
    assert client.get("/").status_code == 200


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


def test_openapi_and_docs_are_disabled(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


_THROTTLE_MSG = "Muitas tentativas. Tente novamente em alguns minutos."


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 4, tzinfo=UTC))


def test_login_throttled_after_five_failures(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False, clock=_clock())
    for _ in range(5):
        assert client.post("/login", data={"password": "bad"}).status_code == 401
    response = client.post("/login", data={"password": "secret"})
    assert response.status_code == 429
    assert _THROTTLE_MSG in response.text


def test_throttle_expires_after_five_minutes(tmp_path: Path) -> None:
    clock = _clock()
    client = make_client(tmp_path, login=False, clock=clock)
    for _ in range(5):
        client.post("/login", data={"password": "bad"})
    clock.advance(4 * 60)
    assert client.post("/login", data={"password": "secret"}).status_code == 429
    clock.advance(61)
    assert client.post("/login", data={"password": "secret"}).status_code == 303


def test_successful_login_resets_failures(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False, clock=_clock())
    for _ in range(4):
        client.post("/login", data={"password": "bad"})
    assert client.post("/login", data={"password": "secret"}).status_code == 303
    for _ in range(4):
        assert client.post("/login", data={"password": "bad"}).status_code == 401


def test_failures_outside_window_are_forgotten(tmp_path: Path) -> None:
    clock = _clock()
    client = make_client(tmp_path, login=False, clock=clock)
    for _ in range(4):
        client.post("/login", data={"password": "bad"})
    clock.advance(16 * 60)
    assert client.post("/login", data={"password": "bad"}).status_code == 401
    assert client.post("/login", data={"password": "secret"}).status_code == 303


def test_htmx_request_without_session_gets_hx_redirect(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.post("/wishes/1/toggle", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
