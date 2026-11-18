"""Shrinks a post picture to a small WebP with Pillow.

`Image.thumbnail` asks a JPEG decoder for a reduced size, so a large photo is never decoded in
full: the memory cost is the thumbnail's, not the original's.
"""

import io

from PIL import Image

THUMB_PX = 320
QUALITY = 72
MAX_PIXELS = 25_000_000  # refuse a decompression bomb before decoding anything


class PillowThumbnailer:
    def thumbnail(self, data: bytes) -> bytes | None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_PIXELS:
                    return None
                image.thumbnail((THUMB_PX, THUMB_PX))
                has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
                small = image.convert("RGBA" if has_alpha else "RGB")
                out = io.BytesIO()
                small.save(out, "WEBP", quality=QUALITY, method=4)
                return out.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
