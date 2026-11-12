"""Post images from the public web view of a Telegram channel (t.me/s/<name>), pure."""

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit

_POST = re.compile(r'data-post="[^"/]+/(\d+)"')
_PHOTO = re.compile(
    r"""class="[^"]*(?:photo_wrap|link_preview_image|link_preview_right_image)[^"]*"[^>]*"""
    r"""background-image:url\('([^']+)'\)"""
)
_CDN_SUFFIX = ".telesco.pe"


@dataclass(frozen=True, slots=True)
class PostImage:
    message_id: int
    url: str


def _trusted(url: str) -> bool:
    """Only Telegram's own CDN over https: the page is third-party markup."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and host.endswith(_CDN_SUFFIX)


def parse_channel_page(html: str) -> list[PostImage]:
    """The first photo of each post on the page, in page order; posts without one are skipped."""
    posts = list(_POST.finditer(html))
    found: list[PostImage] = []
    for i, post in enumerate(posts):
        end = posts[i + 1].start() if i + 1 < len(posts) else len(html)
        photo = _PHOTO.search(html, post.end(), end)
        if photo is None:
            continue
        url = unescape(photo.group(1))
        if _trusted(url):
            found.append(PostImage(int(post.group(1)), url))
    return found
