"""Public web view of a Telegram channel (t.me/s/<name>), fetched politely and read-only."""

import re

import httpx

_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
_TIMEOUT = 15.0
_HEADERS = {
    "User-Agent": "Velkgram/1.0 (personal wishlist app)",
    "Accept": "text/html",
    "Accept-Language": "pt-BR",
}


class HttpxChannelPages:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS)

    def fetch(self, username: str) -> str | None:
        if not _USERNAME.fullmatch(username):
            return None  # the name goes into the URL path: never build one from anything odd
        try:
            response = self._client.get(f"https://t.me/s/{username}", headers=_HEADERS)
        except httpx.HTTPError:
            return None
        return response.text if response.status_code == 200 else None
