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
        return path == "/"
    return path == href or path.startswith(href + "/")


def nav_items(path: str) -> list[NavItem]:
    """The five destinations; Feed is current only on `/`, the others by path segment."""
    return [NavItem(h, label, icon, _is_current(h, path)) for h, label, icon in _DESTINATIONS]
