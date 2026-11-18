"""Fakes for the post-image cache ports."""

from datetime import datetime

from velkgram.offers.domain.image_files import StoredImage


class InMemoryImageStore:
    def __init__(self) -> None:
        self._files: dict[tuple[int, int], tuple[bytes, datetime]] = {}

    def put(self, channel_id: int, message_id: int, data: bytes, now: datetime) -> None:
        self._files[(channel_id, message_id)] = (data, now)

    def get(self, channel_id: int, message_id: int) -> bytes | None:
        entry = self._files.get((channel_id, message_id))
        return entry[0] if entry else None

    def has(self, channel_id: int, message_id: int) -> bool:
        return (channel_id, message_id) in self._files

    def delete(self, channel_id: int, message_id: int) -> None:
        self._files.pop((channel_id, message_id), None)

    def list(self) -> list[StoredImage]:
        return [StoredImage(c, m, len(d), at) for (c, m), (d, at) in self._files.items()]


class FakeImageDownloader:
    """Serves `bodies` by URL; a URL not in it, or in `failing`, gives None or raises."""

    def __init__(self, bodies: dict[str, bytes] | None = None) -> None:
        self.bodies = bodies or {}
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def fetch(self, url: str, max_bytes: int) -> bytes | None:
        self.calls.append(url)
        if url in self.failing:
            raise RuntimeError("network down")
        body = self.bodies.get(url)
        return body if body is not None and len(body) <= max_bytes else None


class FakeThumbnailer:
    """Turns `raw` into `thumb:raw`; refuses what starts with `bad`."""

    def __init__(self) -> None:
        self.calls = 0

    def thumbnail(self, data: bytes) -> bytes | None:
        self.calls += 1
        return None if data.startswith(b"bad") else b"thumb:" + data
