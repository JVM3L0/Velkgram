"""Download of a post picture from Telegram's CDN: https only, size-capped, no redirects."""

import httpx

from velkgram.offers.domain.channel_page import is_telegram_cdn_url

_TIMEOUT = 15.0
_HEADERS = {"User-Agent": "Velkgram/1.0 (personal wishlist app)", "Accept": "image/*"}


class HttpxImageDownloader:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS)

    def fetch(self, url: str, max_bytes: int) -> bytes | None:
        if not is_telegram_cdn_url(url):  # the link came out of third-party markup
            return None
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("content-type", "")
                if not content_type.lower().startswith("image/"):
                    return None
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    return None
                body = bytearray()
                for piece in response.iter_bytes():
                    body += piece
                    if len(body) > max_bytes:
                        return None  # stop reading: the rest is never pulled into memory
                return bytes(body)
        except httpx.HTTPError:
            return None
