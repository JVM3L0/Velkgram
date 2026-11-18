import httpx

from velkgram.offers.adapters.http.image_downloader import HttpxImageDownloader

URL = "https://cdn1.telesco.pe/file/a.jpg"


def _downloader(handler: httpx.MockTransport) -> HttpxImageDownloader:
    return HttpxImageDownloader(httpx.Client(transport=handler))


def _ok(body: bytes = b"jpegbytes", content_type: str = "image/jpeg") -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda _r: httpx.Response(200, content=body, headers={"content-type": content_type})
    )


def test_a_picture_from_the_cdn_is_returned() -> None:
    assert _downloader(_ok()).fetch(URL, 1000) == b"jpegbytes"


def test_a_link_off_telegrams_cdn_is_never_requested() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x", headers={"content-type": "image/jpeg"})

    downloader = _downloader(httpx.MockTransport(handler))
    assert downloader.fetch("https://evil.test/a.jpg", 1000) is None
    assert downloader.fetch("http://cdn1.telesco.pe/a.jpg", 1000) is None
    assert downloader.fetch("https://127.0.0.1/a.jpg", 1000) is None
    assert calls == []


def test_something_that_is_not_an_image_is_refused() -> None:
    assert _downloader(_ok(b"<html>", "text/html")).fetch(URL, 1000) is None


def test_a_picture_over_the_cap_is_refused() -> None:
    assert _downloader(_ok(b"x" * 101)).fetch(URL, 100) is None
    assert _downloader(_ok(b"x" * 100)).fetch(URL, 100) == b"x" * 100


def test_a_declared_size_over_the_cap_is_refused_without_reading_the_body() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x", headers={"content-type": "image/jpeg", "content-length": "5000"}
        )

    assert _downloader(httpx.MockTransport(handler)).fetch(URL, 1000) is None


def test_an_error_status_and_a_redirect_give_nothing() -> None:
    for status in (404, 403, 500, 302):
        handler = httpx.MockTransport(
            lambda _r, s=status: httpx.Response(
                s, headers={"content-type": "image/jpeg", "location": "https://evil.test/a"}
            )
        )
        assert _downloader(handler).fetch(URL, 1000) is None


def test_a_network_error_gives_nothing() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert _downloader(httpx.MockTransport(handler)).fetch(URL, 1000) is None
