from pathlib import Path

import pytest

from tests.apps.web_support import make_client
from velkgram.apps.web.theme import THEME_MODES, safe_next, theme_classes


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, ""),
        ("system", ""),
        ("nonsense", ""),
        ("latte", "latte light"),
        ("frappe", "frappe dark"),
        ("macchiato", "macchiato dark"),
        ("mocha", "mocha dark"),
        ("gruvbox-dark", "gruvbox-dark dark"),
        ("gruvbox-light", "gruvbox-light light"),
    ],
)
def test_theme_classes_for_every_mode(mode: str | None, expected: str) -> None:
    assert theme_classes(mode) == expected


def test_theme_modes_are_the_seven_choices() -> None:
    assert THEME_MODES == (
        "system",
        "latte",
        "frappe",
        "macchiato",
        "mocha",
        "gruvbox-dark",
        "gruvbox-light",
    )


def test_post_theme_sets_cookie_and_redirects_to_next(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/theme", data={"mode": "latte", "next": "/channels"})
    assert response.status_code == 303
    assert response.headers["location"] == "/channels"
    cookie = response.headers["set-cookie"].lower()
    assert "theme=latte" in cookie
    assert "max-age=31536000" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "httponly" in cookie


@pytest.mark.parametrize(
    "bad_next",
    [
        "//evil.com",
        "https://evil.com",
        "/\\evil.com",
        "/%5Cevil.com",
        "/%5cevil.com",
        "/%2Fevil.com",
        "/wishes\nSet-Cookie: x=1",
        "/wishes\r\n",
        "",
        "wishes",
    ],
)
def test_post_theme_rejects_offsite_next(tmp_path: Path, bad_next: str) -> None:
    client = make_client(tmp_path)
    response = client.post("/theme", data={"mode": "mocha", "next": bad_next})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "theme=mocha" in response.headers["set-cookie"]


def test_safe_next_keeps_same_site_path_with_query() -> None:
    assert safe_next("/wishes/3?x=1") == "/wishes/3?x=1"
    assert safe_next(None) == "/"


def test_post_theme_rejects_unknown_mode(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/theme", data={"mode": "neon", "next": "/"})
    assert response.status_code == 400
    assert "set-cookie" not in response.headers


def test_post_theme_requires_login(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.post("/theme", data={"mode": "latte", "next": "/"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "theme=" not in response.headers.get("set-cookie", "")


def test_body_class_follows_cookie(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert '<body class="">' in client.get("/wishes").text
    client.cookies.set("theme", "mocha")
    assert '<body class="mocha dark">' in client.get("/wishes").text
    client.cookies.set("theme", "latte")
    assert '<body class="latte light">' in client.get("/wishes").text
    client.cookies.set("theme", "bogus")
    assert '<body class="">' in client.get("/wishes").text
