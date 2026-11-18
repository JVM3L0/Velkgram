"""`/img/<channel>/<message>`: the local copy of a post picture, else Telegram's own link."""

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings
from tests.fakes.clock import FakeClock
from tests.offers.adapters._queries_helpers import T0, offer, put
from velkgram.offers.adapters.fs.image_store import FsImageStore
from velkgram.offers.adapters.sqlite.post_images import SqlitePostImageRepository
from velkgram.offers.domain.channel_page import PostImage
from velkgram.shared.db import connect

NOW = T0 + timedelta(days=1)
CDN = "https://cdn1.telesco.pe/file/a.jpg"


def _record_url(tmp_path: Path, channel_id: int, message_id: int, url: str) -> None:
    conn = connect(make_settings(tmp_path).db_path)
    try:
        SqlitePostImageRepository(conn).upsert(channel_id, [PostImage(message_id, url)], NOW)
    finally:
        conn.close()


def _keep_copy(tmp_path: Path, channel_id: int, message_id: int, data: bytes) -> None:
    FsImageStore(make_settings(tmp_path).images_path).put(channel_id, message_id, data, NOW)


def _client(tmp_path: Path, *, login: bool = True) -> TestClient:
    return make_client(tmp_path, login=login, clock=FakeClock(NOW))


def test_the_local_copy_is_served_as_a_cacheable_webp(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _keep_copy(tmp_path, -100, 5, b"RIFFwebp")
    response = client.get("/img/-100/5")
    assert response.status_code == 200
    assert response.content == b"RIFFwebp"
    assert response.headers["content-type"] == "image/webp"
    assert "max-age" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_without_a_copy_it_redirects_to_the_link_telegram_gave(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _record_url(tmp_path, -100, 5, CDN)
    response = client.get("/img/-100/5")
    assert response.status_code == 302
    assert response.headers["location"] == CDN


def test_the_copy_wins_over_the_remote_link(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _record_url(tmp_path, -100, 5, CDN)
    _keep_copy(tmp_path, -100, 5, b"local")
    assert client.get("/img/-100/5").content == b"local"


def test_a_stored_link_that_is_not_telegrams_is_never_redirected_to(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _record_url(tmp_path, -100, 5, "https://evil.test/a.jpg")
    assert client.get("/img/-100/5").status_code == 404


def test_a_post_with_neither_copy_nor_link_is_a_404(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/img/-100/5").status_code == 404


def test_a_path_that_is_not_a_number_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    # The file name is built from two integers, so a path can never leave the images directory.
    assert client.get("/img/-100/..%2f..%2fetc").status_code in (404, 422)
    assert client.get("/img/x/5").status_code == 422


def test_the_route_needs_a_login(tmp_path: Path) -> None:
    client = _client(tmp_path, login=False)
    _keep_copy(tmp_path, -100, 5, b"local")
    response = client.get("/img/-100/5")
    assert response.status_code in (302, 303, 401)
    assert response.content != b"local"


def test_a_card_points_at_the_route_when_the_picture_came_from_the_post(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conn = connect(make_settings(tmp_path).db_path)
    try:
        conn.execute(
            "INSERT INTO channels (id, ref, telegram_id, name, status, enabled, "
            "silent_after_hours, created_at) VALUES (1, '@c1', 1, 'Promos', 'active', 1, 12, ?)",
            (T0.isoformat(),),
        )
        conn.commit()
        put(conn, offer(7, link=None))
        SqlitePostImageRepository(conn).upsert(1, [PostImage(7, CDN)], NOW)
    finally:
        conn.close()
    html = client.get("/").text
    assert 'src="/img/1/7"' in html
    assert "telesco.pe" not in html
