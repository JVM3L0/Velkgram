from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import match, offer, put
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.domain.models import MatchSource, RetroRun, RetroStatus
from velkgram.shared.db import connect, read_versions

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path) -> TestClient:
    client = make_client(tmp_path, clock=FakeClock(NOW))
    response = client.post(
        "/wishes/new",
        data={
            "name": "SSD <b>1TB</b>",
            "required_terms": "ssd",
            "excluded_terms": "usado",
            "max_price": "300,00",
        },
    )
    assert response.status_code == 303
    return client


def _seed(
    tmp_path: Path,
    rows: list[tuple[int, int, int | None, MatchSource]],
    run: RetroStatus | None = None,
) -> None:
    """Rows are (message_id, days_ago, price_cents, source) matched to wish 1."""
    conn = connect(make_settings(tmp_path).db_path)
    try:
        repo = SqliteOfferRepository(conn)
        for mid, days_ago, price, source in rows:
            o = offer(mid, at=NOW - timedelta(days=days_ago), price=price, title=f"SSD {mid}")
            put(conn, o)
            repo.add_match(match(1, o, source))
        if run is not None:
            repo.save_retro_run(
                RetroRun(1, "fp", run, NOW, None if run is RetroStatus.running else NOW, None)
            )
    finally:
        conn.close()


def _db(tmp_path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


_LIVE = MatchSource.live
_RETRO = MatchSource.retro


def test_product_page_shows_stats_and_chart(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 5, 25000, _LIVE), (2, 2, 20000, _RETRO)])
    html = client.get("/wishes/1").text
    assert "SSD &lt;b&gt;1TB&lt;/b&gt;" in html
    assert "ativo" in html
    assert "R$ 300,00" in html
    for label in ("Menor preço", "Preço atual", "Ofertas"):
        assert label in html
    assert "Média 30 dias" not in html  # the four equal tiles are gone
    assert "R$ 200,00" in html
    assert "<svg" in html
    assert 'href="/wishes/1/edit"' in html
    assert 'action="/wishes/1/delete"' in html
    assert "Remover" in html


def test_product_page_empty_stats_show_dash(tmp_path: Path) -> None:
    client = _client(tmp_path)
    html = client.get("/wishes/1").text
    assert html.count("—") >= 2
    assert "Sem preços ainda" in html
    assert "Poucos dados para comparar" in html
    banner = _banner(html)
    assert "insight-price" not in banner and "Preço atual" not in banner  # nothing to price


def test_product_range_switch_limits_points(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 60, 11100, _LIVE), (2, 3, 22200, _LIVE)])
    assert "R$ 111,00" in client.get("/wishes/1").text  # default 90 days
    thirty = client.get("/wishes/1", params={"range": "30"}).text
    assert "Sem preços ainda" not in thirty
    assert "<title>Histórico de preços" in thirty
    # the 60 day old point is outside the 30 day chart (the stats still show the lowest price)
    chart30 = thirty[thirty.index("<svg") : thirty.index("</svg>")]
    assert "111,00" not in chart30 and "222,00" in chart30
    junk = client.get("/wishes/1", params={"range": "zzz"})
    assert junk.status_code == 200


def test_product_404_for_unknown_wish(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/wishes/99").status_code == 404
    assert client.get("/wishes/99/matches").status_code == 404
    assert client.get("/wishes/99/chart").status_code == 404
    assert client.get("/wishes/99/history").status_code == 404
    assert client.get("/wishes/99999999999999999999999").status_code in (404, 422)


def test_wishes_new_is_not_captured_by_product_route(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/wishes/new")
    assert response.status_code == 200
    assert "Termos obrigatórios" in response.text


def test_retro_status_fragments_for_each_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    none = client.get("/wishes/1/history")
    assert "Buscando no histórico" in none.text
    assert 'hx-trigger="every 2s"' in none.text
    assert "<html" not in none.text

    _seed(tmp_path, [], RetroStatus.running)
    assert 'hx-trigger="every 2s"' in client.get("/wishes/1/history").text

    conn = connect(make_settings(tmp_path).db_path)
    SqliteOfferRepository(conn).save_retro_run(RetroRun(1, "fp", RetroStatus.done, NOW, NOW, None))
    done = client.get("/wishes/1/history")
    assert "Histórico atualizado" in done.text and "every 2s" not in done.text

    SqliteOfferRepository(conn).save_retro_run(
        RetroRun(1, "fp", RetroStatus.failed, NOW, NOW, "boom")
    )
    conn.close()
    failed = client.get("/wishes/1/history")
    assert "Não foi possível buscar o histórico" in failed.text
    assert "Tentar de novo" in failed.text
    assert 'hx-post="/wishes/1/history/retry"' in failed.text
    assert "boom" not in failed.text


def test_retry_deletes_run_and_bumps_wishlist_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 5, 25000, _LIVE)], RetroStatus.failed)
    before = read_versions(connect(make_settings(tmp_path).db_path)).get("wishlist", 0)
    response = client.post("/wishes/1/history/retry")
    assert response.status_code == 200
    assert "Buscando no histórico" in response.text
    assert 'hx-trigger="every 2s"' in response.text
    assert _db(tmp_path, "SELECT * FROM retro_runs") == []
    assert _db(tmp_path, "SELECT count(*) FROM offer_matches") == [(1,)]
    after = read_versions(connect(make_settings(tmp_path).db_path)).get("wishlist", 0)
    assert after == before + 1


def test_retry_404_for_unknown_wish(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.post("/wishes/99/history/retry").status_code == 404


def test_match_chips_show_source(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 5, 25000, _LIVE), (2, 4, 24000, _RETRO)])
    html = client.get("/wishes/1").text
    assert "ao vivo" in html and "histórico" in html


def test_done_poll_sends_retro_done_trigger(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [], RetroStatus.done)
    polled = client.get("/wishes/1/history", headers={"HX-Request": "true"})
    assert polled.headers["HX-Trigger"] == "retro-done"
    running = client.get("/wishes/1", headers={})
    assert 'hx-trigger="retro-done from:body"' in running.text
    assert "HX-Trigger" not in client.get("/wishes/1").headers


def test_chart_fragment_respects_range(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 60, 11100, _LIVE), (2, 3, 22200, _LIVE)])
    frag = client.get("/wishes/1/chart", params={"range": "30"}).text
    assert "<html" not in frag
    assert "Menor preço" in frag and "<svg" in frag
    svg = frag[frag.index("<svg") : frag.index("</svg>")]
    assert "111,00" not in svg
    wide = client.get("/wishes/1/chart", params={"range": "all"}).text
    assert "111,00" in wide[wide.index("<svg") : wide.index("</svg>")]


def test_matches_fragment_without_cursor_is_first_page(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(i, 1, 10000 + i, _LIVE) for i in range(1, 36)])
    frag = client.get("/wishes/1/matches", headers={"HX-Request": "true"}).text
    assert "<html" not in frag
    assert "SSD 35" in frag and "SSD 5" not in frag
    assert 'hx-trigger="revealed"' in frag
    junk = client.get("/wishes/1/matches", params={"cursor": "lixo|x|y"})
    assert junk.status_code == 200 and "SSD 35" in junk.text


def test_source_chips_are_explained_and_match_rows_use_a_filled_abrir(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 1, 10000, _LIVE), (2, 2, 20000, _RETRO)])
    html = client.get("/wishes/1").text
    assert 'title="Encontrada na busca retroativa ao criar ou editar o desejo"' in html
    assert 'title="Recebida em tempo real"' in html
    assert html.count('aria-describedby="source-retro-desc"') == 1
    assert html.count('aria-describedby="source-live-desc"') == 1
    assert html.count('id="source-retro-desc"') == 1  # one description per page, not per row
    assert "Encontrada na busca retroativa ao criar ou editar o desejo</span>" in html
    assert "Recebida em tempo real</span>" in html
    assert '<a class="button small" href=' in html


def _banner(html: str) -> str:
    start = html.index('class="insight')
    return html[start : html.index("</div>", html.index("insight-main", start))]


def test_insight_banner_compares_the_current_price_with_the_range_average(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _seed(
        tmp_path,
        [(1, 6, 30000, _LIVE), (2, 5, 30000, _LIVE), (3, 4, 30000, _LIVE), (4, 1, 24000, _LIVE)],
    )
    banner = _banner(client.get("/wishes/1").text)
    assert "insight-below" in banner
    assert "Preço atual" in banner and "R$ 240,00" in banner
    assert "abaixo da média" in banner
    _seed(tmp_path, [(5, 0, 36000, _LIVE)])
    assert "acima da média" in _banner(client.get("/wishes/1").text)


def test_insight_banner_says_when_there_is_too_little_data(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _seed(tmp_path, [(1, 3, 30000, _LIVE), (2, 1, 24000, _LIVE)])
    banner = _banner(client.get("/wishes/1").text)
    assert "insight-unknown" in banner and "Poucos dados para comparar" in banner


def test_non_comparable_match_is_listed_with_a_chip_but_not_charted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = connect(make_settings(tmp_path).db_path)
    try:
        good = offer(1, at=NOW - timedelta(days=2), price=25000, title="SSD bom")
        coupon = offer(
            2, at=NOW - timedelta(days=1), price=100, title="Cupom SSD", comparable=False
        )
        put(conn, good, coupon)
        repo = SqliteOfferRepository(conn)
        repo.add_match(match(1, good))
        repo.add_match(match(1, coupon))
    finally:
        conn.close()
    html = client.get("/wishes/1").text
    assert html.count("não comparável") == 1
    assert "Cupom ou post com vários preços — fora do gráfico e das estatísticas" in html
    svg = html[html.index("<svg") : html.index("</svg>")]
    assert "R$ 1,00" not in svg
    assert "Cupom SSD" in html
