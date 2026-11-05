import html
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client
from velkgram.apps.web.nav import nav_items

PINNED = (
    "https://unpkg.com/htmx.org@2.0.3/dist/htmx.min.js",
    "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/beer.min.css",
    "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/beer.min.js",
    "https://fonts.googleapis.com/css2?family=Roboto+Flex:opsz,wght@8..144,100..1000&display=swap",
    "/static/velkgram.css",
)
PAGES = ("/login", "/wishes", "/wishes/new", "/channels", "/alerts", "/status")


class _Tags(HTMLParser):
    """Collects start tags and the text of every <a>/<button> (ignoring <i>)."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.actions: list[tuple[str, dict[str, str | None], str]] = []
        self._stack: list[list[object]] = []
        self._icon_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag in ("a", "button"):
            self._stack.append([tag, dict(attrs), ""])
        if tag == "i" and self._stack:
            self._icon_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "i" and self._icon_depth:
            self._icon_depth -= 1
        if tag in ("a", "button") and self._stack and self._stack[-1][0] == tag:
            name, attrs, text = self._stack.pop()
            self.actions.append((str(name), attrs, str(text)))  # type: ignore[arg-type]

    def handle_data(self, data: str) -> None:
        if self._stack and not self._icon_depth:
            self._stack[-1][2] = str(self._stack[-1][2]) + data


def _parse(page: str) -> _Tags:
    parser = _Tags()
    parser.feed(page)
    return parser


def _page(client: TestClient, path: str = "/wishes") -> str:
    response = client.get(path)
    assert response.status_code == 200
    return response.text


def test_base_loads_pinned_assets(tmp_path: Path) -> None:
    page = html.unescape(_page(make_client(tmp_path)))
    for url in PINNED:
        assert url in page


def test_base_has_no_inline_style(tmp_path: Path) -> None:
    assert "<style" not in _page(make_client(tmp_path))


def test_base_assets_have_sri(tmp_path: Path) -> None:
    tags = _parse(_page(make_client(tmp_path))).tags
    found = {}
    for name, attrs in tags:
        target = attrs.get("src") or attrs.get("href") or ""
        for key in ("htmx.min.js", "beer.min.css", "beer.min.js"):
            if name in ("script", "link") and target.endswith(key):
                found[key] = attrs
    assert set(found) == {"htmx.min.js", "beer.min.css", "beer.min.js"}
    for attrs in found.values():
        assert re.fullmatch(r"sha384-[A-Za-z0-9+/]{64}", attrs.get("integrity") or "")
        assert attrs.get("crossorigin") == "anonymous"
    assert found["beer.min.js"].get("type") == "module"


def test_nav_marks_current_page(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    for path, current in (
        ("/wishes", "/wishes"),
        ("/wishes/new", "/wishes"),
        ("/status", "/status"),
    ):
        actions = _parse(_page(client, path)).actions
        marked = {a.get("href") for _, a, _ in actions if a.get("aria-current") == "page"}
        assert marked == {current}


def test_nav_has_five_destinations_in_both_bars(tmp_path: Path) -> None:
    page = _page(make_client(tmp_path))
    assert '<nav class="bottom' in page
    assert '<nav class="left' in page
    hrefs = [a.get("href") for _, a, _ in _parse(page).actions]
    for href in ("/", "/wishes", "/alerts", "/channels", "/status"):
        assert hrefs.count(href) == 2


def test_nav_items_current_rules() -> None:
    def current(path: str) -> list[str]:
        return [i.href for i in nav_items(path) if i.current]

    assert current("/") == ["/"]
    assert current("/wishes") == ["/wishes"]
    assert current("/wishes/3") == ["/wishes"]
    assert current("/wishesx") == []
    assert current("/channels/") == ["/channels"]
    assert [i.href for i in nav_items("/")] == ["/", "/wishes", "/alerts", "/channels", "/status"]


def test_static_css_is_served(tmp_path: Path) -> None:
    client = make_client(tmp_path, login=False)
    response = client.get("/static/velkgram.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "Catppuccin" in response.text


def test_logged_in_bar_has_theme_menu_and_logout(tmp_path: Path) -> None:
    page = _page(make_client(tmp_path))
    assert "Sair" in page
    for mode in ("system", "latte", "frappe", "macchiato", "mocha"):
        assert f'name="mode" value="{mode}"' in page


@pytest.mark.parametrize("path", PAGES)
def test_icon_only_buttons_have_labels(tmp_path: Path, path: str) -> None:
    client = make_client(tmp_path, login=path != "/login")
    for name, attrs, text in _parse(_page(client, path)).actions:
        if not text.strip():
            assert attrs.get("aria-label"), f"<{name}> without text or aria-label on {path}"
