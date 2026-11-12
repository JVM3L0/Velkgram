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
        ("dark", "dark"),
        ("light", "light"),
        # cookies written before the themes were reduced to two keep working
        ("mocha", "dark"),
        ("macchiato", "dark"),
        ("frappe", "dark"),
        ("gruvbox-dark", "dark"),
        ("latte", "light"),
        ("gruvbox-light", "light"),
    ],
)
def test_theme_classes_for_every_mode(mode: str | None, expected: str) -> None:
    assert theme_classes(mode) == expected


def test_theme_modes_are_system_dark_and_light() -> None:
    assert THEME_MODES == ("system", "dark", "light")


@pytest.mark.parametrize("old", ["mocha", "latte", "frappe", "macchiato", "gruvbox-dark"])
def test_a_retired_theme_cannot_be_chosen_any_more(tmp_path: Path, old: str) -> None:
    client = make_client(tmp_path)
    assert client.post("/theme", data={"mode": old, "next": "/"}).status_code == 400


def test_post_theme_sets_cookie_and_redirects_to_next(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post("/theme", data={"mode": "light", "next": "/channels"})
    assert response.status_code == 303
    assert response.headers["location"] == "/channels"
    cookie = response.headers["set-cookie"].lower()
    assert "theme=light" in cookie
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
    response = client.post("/theme", data={"mode": "dark", "next": bad_next})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "theme=dark" in response.headers["set-cookie"]


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
    response = client.post("/theme", data={"mode": "light", "next": "/"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "theme=" not in response.headers.get("set-cookie", "")


def test_body_class_follows_cookie(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert '<body class="">' in client.get("/wishes").text
    client.cookies.set("theme", "dark")
    assert '<body class="dark">' in client.get("/wishes").text
    client.cookies.set("theme", "light")
    assert '<body class="light">' in client.get("/wishes").text
    client.cookies.set("theme", "mocha")  # a retired value still resolves to its nearest theme
    assert '<body class="dark">' in client.get("/wishes").text
    client.cookies.set("theme", "bogus")
    assert '<body class="">' in client.get("/wishes").text
