from pathlib import Path
from urllib.parse import urlencode

from tests.apps.web_support import make_client, make_settings
from velkgram.shared.db import connect


def test_new_form_prefills_from_query(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    query = urlencode(
        [
            ("name", 'Placa "RTX" <b>'),
            ("required", "rtx 4070"),
            ("required", "super|ti"),
            ("excluded", "usada"),
            ("excluded", "defeito"),
            ("max_price", "1.299,90"),
        ]
    )
    page = client.get(f"/wishes/new?{query}").text
    assert 'value="Placa &#34;RTX&#34; &lt;b&gt;"' in page
    assert "rtx 4070\nsuper|ti" in page
    assert "usada\ndefeito" in page
    assert 'value="1.299,90"' in page


def test_new_form_prefill_does_not_create_wish(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/wishes/new?name=Algo&required=algo&max_price=10").status_code == 200
    conn = connect(make_settings(tmp_path).db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM wishes").fetchone()[0] == 0
    finally:
        conn.close()


def test_new_form_ignores_invalid_max_price(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    page = client.get("/wishes/new?name=Algo&max_price=abc").text
    assert 'value="Algo"' in page
    assert "abc" not in page


def test_new_form_without_params_is_empty(tmp_path: Path) -> None:
    page = make_client(tmp_path).get("/wishes/new").text
    assert 'name="max_price" value=""' in page
