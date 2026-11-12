from pathlib import Path

import pytest

from tests.apps.web_support import make_client, make_user_client


@pytest.mark.parametrize("path", ["/channels", "/status"])
def test_admin_only_pages_are_forbidden_to_a_regular_user(tmp_path: Path, path: str) -> None:
    make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    assert ana.get(path).status_code == 403


@pytest.mark.parametrize("path", ["/channels", "/status"])
def test_admin_only_pages_open_for_the_admin(tmp_path: Path, path: str) -> None:
    assert make_client(tmp_path).get(path).status_code == 200


def test_a_user_cannot_change_channels(tmp_path: Path) -> None:
    make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    assert ana.post("/channels", data={"ref": "@canalqualquer"}).status_code == 403
    assert ana.post("/channels/1/toggle").status_code == 403
    assert ana.post("/channels/1/delete").status_code == 403


def test_the_menu_hides_admin_pages_from_a_regular_user(tmp_path: Path) -> None:
    make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    page = ana.get("/wishes").text
    assert 'href="/wishes"' in page and 'href="/alerts"' in page
    assert 'href="/channels"' not in page and 'href="/status"' not in page
    assert 'href="/usuarios"' not in page
    assert 'href="/perfil"' in page


def test_the_menu_shows_everything_to_the_admin(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/wishes").text
    for href in ("/wishes", "/alerts", "/channels", "/status", "/usuarios", "/perfil"):
        assert f'href="{href}"' in page
