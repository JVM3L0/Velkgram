"""Which locally kept post images to delete (pure)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class StoredImage:
    channel_id: int
    message_id: int
    size: int  # bytes on disk
    stored_at: datetime


def images_to_delete(
    images: Sequence[StoredImage], max_bytes: int, older_than: datetime
) -> list[StoredImage]:
    """Every image stored before `older_than`, then the oldest of the rest until the total fits.

    The order is by age, so the pictures of the newest posts are the last to go.
    """
    ordered = sorted(images, key=lambda i: (i.stored_at, i.channel_id, i.message_id))
    expired = [i for i in ordered if i.stored_at < older_than]
    kept = [i for i in ordered if i.stored_at >= older_than]
    total = sum(i.size for i in kept)
    over: list[StoredImage] = []
    for image in kept:
        if total <= max_bytes:
            break
        over.append(image)
        total -= image.size
    return [*expired, *over]
