"""URL helpers shared by the link rules and the web views (pure)."""

from urllib.parse import urlsplit


def strip_query(url: str) -> str:
    """The URL without its query string and fragment (affiliate tokens live there)."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _scheme(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:  # e.g. "http://[::1": a garbled link must not break callers
        return ""


def is_safe_url(url: str | None) -> bool:
    """True only for http and https (never javascript:, tg:, data:)."""
    return _scheme(url) in ("http", "https")


def is_safe_https_url(url: str | None) -> bool:
    return _scheme(url) == "https"


def host_of(url: str) -> str:
    """Lowercase host of `url`, or "" when there is none."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""
