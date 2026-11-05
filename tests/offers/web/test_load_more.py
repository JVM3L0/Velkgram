import re
from pathlib import Path

from tests.offers.web.test_feed_page import _client, _many


def _sentinel(page: str) -> str | None:
    found = re.search(r'<button[^>]*class="button tonal load-more".*?</button>', page, re.DOTALL)
    return found.group(0) if found else None


def test_next_page_is_an_explicit_button_triggered_by_reveal_or_click(tmp_path: Path) -> None:
    page = _client(tmp_path, *_many(35)).get("/").text
    button = _sentinel(page)
    assert button is not None
    assert 'hx-trigger="revealed, click"' in button and 'hx-swap="outerHTML"' in button
    assert "Carregar mais" in button
    assert "Fim da lista" not in page
    assert "hx-trigger" not in page.replace(button, "").split('id="feed"')[1]  # none on the cards


def test_button_has_a_progress_indicator_while_loading(tmp_path: Path) -> None:
    button = _sentinel(_client(tmp_path, *_many(35)).get("/").text)
    assert button is not None
    assert re.search(r"<progress[^>]*htmx-indicator", button)
    assert 'hx-disabled-elt="this"' in button


def test_button_carries_the_error_message_and_stays_a_button(tmp_path: Path) -> None:
    button = _sentinel(_client(tmp_path, *_many(35)).get("/").text)
    assert button is not None
    assert button.startswith("<button") and 'type="button"' in button
    assert "Falha ao carregar. Tentar de novo" in button


def test_last_page_shows_muted_end_of_list_and_no_button(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(3))
    page = client.get("/").text
    assert _sentinel(page) is None
    assert re.search(r'<p class="load-end muted">Fim da lista</p>', page)


def test_empty_list_shows_neither(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/").text
    assert _sentinel(page) is None and "Fim da lista" not in page


def test_pages_include_the_back_to_top_button(tmp_path: Path) -> None:
    client = _client(tmp_path, *_many(3))
    for path in ("/", "/cupons"):
        page = client.get(path).text
        assert 'aria-label="Voltar ao topo"' in page and "arrow_upward" in page
        assert "data-scroll-top" in page
