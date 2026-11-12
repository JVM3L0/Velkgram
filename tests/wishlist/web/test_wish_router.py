import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from velkgram.shared.db import connect


def _query(tmp_path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _create(client: TestClient, **overrides: str) -> None:
    data = {
        "name": "GPU",
        "required_terms": "rtx 4070|rtx 4060\nsuper",
        "excluded_terms": "usada",
        "max_price": "1.299,90",
    }
    data.update(overrides)
    response = client.post("/wishes/new", data=data)
    assert response.status_code == 303


def test_create_wish_converts_price_to_cents(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client, max_price="599,90")
    rows = _query(tmp_path, "SELECT name, max_price_cents, required_terms FROM wishes")
    assert rows[0][:2] == ("GPU", 59990)
    assert json.loads(str(rows[0][2])) == ["rtx 4070|rtx 4060", "super"]


def test_price_formats(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client, name="a", max_price="1.299,90")
    _create(client, name="b", max_price="599")
    prices = _query(tmp_path, "SELECT max_price_cents FROM wishes ORDER BY id")
    assert prices == [(129990,), (59900,)]


def test_create_wish_bumps_version(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client)
    assert _query(tmp_path, "SELECT version FROM state_versions WHERE name='wishlist'") == [(1,)]


def test_invalid_wish_rerenders_with_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/wishes/new",
        data={"name": "x", "required_terms": "  \n", "excluded_terms": "", "max_price": "10"},
    )
    assert response.status_code == 422
    assert "Informe ao menos um termo obrigatório" in response.text
    assert _query(tmp_path, "SELECT id FROM wishes") == []


def test_invalid_price_rerenders_with_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/wishes/new",
        data={"name": "x", "required_terms": "a", "excluded_terms": "", "max_price": "abc"},
    )
    assert response.status_code == 422
    assert "Preço inválido" in response.text


def test_list_shows_wishes_and_escapes(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client, name="<script>x</script>")
    page = client.get("/wishes").text
    assert "Desejos" in page
    assert "&lt;script&gt;" in page
    assert "<script>x" not in page
    assert "/static/htmx.min.js" in page


def test_toggle_returns_row_fragment(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client)
    response = client.post("/wishes/1/toggle")
    assert response.status_code == 200
    assert "<html" not in response.text
    assert "GPU" in response.text
    assert _query(tmp_path, "SELECT enabled FROM wishes") == [(0,)]
    client.post("/wishes/1/toggle")
    assert _query(tmp_path, "SELECT enabled FROM wishes") == [(1,)]


def test_edit_updates_wish(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client)
    page = client.get("/wishes/1/edit").text
    assert "Termos obrigatórios" in page
    assert re.search(r"1299,90", page)
    response = client.post(
        "/wishes/1/edit",
        data={"name": "GPU2", "required_terms": "rtx", "excluded_terms": "", "max_price": "10"},
    )
    assert response.status_code == 303
    assert _query(tmp_path, "SELECT name, max_price_cents FROM wishes") == [("GPU2", 1000)]


def test_edit_missing_wish_is_404(tmp_path: Path) -> None:
    assert make_client(tmp_path).get("/wishes/99/edit").status_code == 404


def test_delete_removes_wish(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _create(client)
    assert client.post("/wishes/1/delete").status_code == 303
    assert _query(tmp_path, "SELECT id FROM wishes") == []
