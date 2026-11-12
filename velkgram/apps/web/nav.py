"""Navigation destinations shown in the bottom bar and the rail."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    href: str
    label: str
    icon: str
    current: bool


_DESTINATIONS = (
    ("/", "Feed", "home"),
    ("/wishes", "Desejos", "favorite"),
    ("/alerts", "Alertas", "notifications"),
    ("/channels", "Canais", "campaign"),
    ("/status", "Status", "monitor_heart"),
)


def _is_current(href: str, path: str) -> bool:
    if href == "/":
        return path == "/" or path == "/cupons" or path.startswith("/cupons/")
    return path == href or path.startswith(href + "/")


_ADMIN_ONLY = frozenset({"/channels", "/status"})


def nav_items(path: str, admin: bool = True) -> list[NavItem]:
    """The destinations; Feed also covers `/cupons`, the others match by path segment.

    Channels and Status are for administrators only.
    """
    return [
        NavItem(h, label, icon, _is_current(h, path))
        for h, label, icon in _DESTINATIONS
        if admin or h not in _ADMIN_ONLY
    ]
