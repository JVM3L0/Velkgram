from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings, make_user_client
from velkgram.shared.db import connect

FORM = {
    "name": "GPU",
    "required_terms": "rtx 4070",
    "excluded_terms": "",
    "max_price": "1.299,90",
}


def _rows(tmp_path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


@pytest.fixture
def clients(tmp_path: Path) -> tuple[TestClient, TestClient]:
    admin = make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    return admin, ana


def test_a_new_wish_belongs_to_the_user_who_created_it(
    tmp_path: Path, clients: tuple[TestClient, TestClient]
) -> None:
    admin, ana = clients
    admin.post("/wishes/new", data=FORM)
    ana.post("/wishes/new", data={**FORM, "name": "Ana's"})
    rows = _rows(tmp_path, "SELECT name, user_id FROM wishes ORDER BY id")
    assert rows == [("GPU", 1), ("Ana's", 2)]


def test_the_list_shows_only_my_wishes(clients: tuple[TestClient, TestClient]) -> None:
    admin, ana = clients
    admin.post("/wishes/new", data={**FORM, "name": "AdminOnlyWish"})
    ana.post("/wishes/new", data={**FORM, "name": "AnaOnlyWish"})
    assert "AnaOnlyWish" in ana.get("/wishes").text
    assert "AdminOnlyWish" not in ana.get("/wishes").text
    assert "AdminOnlyWish" in admin.get("/wishes").text
    assert "AnaOnlyWish" not in admin.get("/wishes").text


def test_someone_elses_wish_is_a_404_on_every_route(
    tmp_path: Path, clients: tuple[TestClient, TestClient]
) -> None:
    admin, ana = clients
    admin.post("/wishes/new", data=FORM)
    wish_id = int(str(_rows(tmp_path, "SELECT id FROM wishes")[0][0]))
    assert ana.get(f"/wishes/{wish_id}/edit").status_code == 404
    assert ana.post(f"/wishes/{wish_id}/edit", data=FORM).status_code == 404
    assert ana.post(f"/wishes/{wish_id}/toggle").status_code == 404
    assert ana.post(f"/wishes/{wish_id}/delete").status_code == 404
    still = _rows(tmp_path, "SELECT name, enabled, user_id FROM wishes")
    assert still == [("GPU", 1, 1)]  # nothing changed


def test_the_owner_can_still_edit_toggle_and_delete(
    tmp_path: Path, clients: tuple[TestClient, TestClient]
) -> None:
    _, ana = clients
    ana.post("/wishes/new", data=FORM)
    wish_id = int(str(_rows(tmp_path, "SELECT id FROM wishes")[0][0]))
    assert ana.get(f"/wishes/{wish_id}/edit").status_code == 200
    assert ana.post(f"/wishes/{wish_id}/edit", data={**FORM, "name": "Renamed"}).status_code == 303
    assert ana.post(f"/wishes/{wish_id}/toggle").status_code == 200
    assert ana.post(f"/wishes/{wish_id}/delete").status_code == 303
    assert _rows(tmp_path, "SELECT * FROM wishes") == []


def test_editing_keeps_the_owner(tmp_path: Path, clients: tuple[TestClient, TestClient]) -> None:
    _, ana = clients
    ana.post("/wishes/new", data=FORM)
    wish_id = int(str(_rows(tmp_path, "SELECT id FROM wishes")[0][0]))
    ana.post(f"/wishes/{wish_id}/edit", data={**FORM, "name": "Renamed"})
    assert _rows(tmp_path, "SELECT name, user_id FROM wishes") == [("Renamed", 2)]
