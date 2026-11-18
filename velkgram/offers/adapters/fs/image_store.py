"""Post picture copies as plain files in a directory of the data volume.

One file per post, `<channel>_<message>.webp`, written to a temporary name and renamed so a reader
(the web process) never sees half a file. The file's mtime is when the copy was stored.
"""

import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from velkgram.offers.domain.image_files import StoredImage

_NAME = re.compile(r"(-?\d+)_(\d+)\.webp")
_TMP_PREFIX = ".tmp-"
_STALE_TMP_S = 3600.0


class FsImageStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _file(self, channel_id: int, message_id: int) -> Path:
        return self._dir / f"{channel_id}_{message_id}.webp"

    def put(self, channel_id: int, message_id: int, data: bytes, now: datetime) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, dir=self._dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.utime(tmp, (now.timestamp(), now.timestamp()))
            os.replace(tmp, self._file(channel_id, message_id))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, channel_id: int, message_id: int) -> bytes | None:
        try:
            return self._file(channel_id, message_id).read_bytes()
        except FileNotFoundError:
            return None

    def has(self, channel_id: int, message_id: int) -> bool:
        return self._file(channel_id, message_id).is_file()

    def delete(self, channel_id: int, message_id: int) -> None:
        self._file(channel_id, message_id).unlink(missing_ok=True)

    def list(self) -> list[StoredImage]:
        if not self._dir.is_dir():
            return []
        found: list[StoredImage] = []
        for entry in self._dir.iterdir():
            match = _NAME.fullmatch(entry.name)
            if match is None:
                self._drop_stale_tmp(entry)
                continue
            try:
                stat = entry.stat()
            except FileNotFoundError:  # deleted between the listing and the stat
                continue
            found.append(
                StoredImage(
                    int(match.group(1)),
                    int(match.group(2)),
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, UTC),
                )
            )
        return found

    @staticmethod
    def _drop_stale_tmp(entry: Path) -> None:
        """A crash between write and rename leaves a temp file that nothing else would remove."""
        if not entry.name.startswith(_TMP_PREFIX):
            return
        try:
            if time.time() - entry.stat().st_mtime > _STALE_TMP_S:
                entry.unlink(missing_ok=True)
        except FileNotFoundError:
            return
