"""Theme modes, the `theme` cookie value to `<body>` classes, and safe redirect targets."""

THEME_MODES = ("system", "latte", "frappe", "macchiato", "mocha", "gruvbox-dark", "gruvbox-light")
THEME_COOKIE = "theme"
THEME_MAX_AGE = 31536000  # one year

_DARK_FLAVOURS = ("frappe", "macchiato", "mocha", "gruvbox-dark")


def theme_classes(mode: str | None) -> str:
    """`<body>` classes for a theme cookie value. System and unknown values add none."""
    if mode in ("latte", "gruvbox-light"):
        return f"{mode} light"
    if mode in _DARK_FLAVOURS:
        return f"{mode} dark"
    return ""


def safe_next(target: str | None) -> str:
    """Return `target` when it is a same-site path, else `/` (no open redirect)."""
    if not target or not target.startswith("/"):
        return "/"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in target):
        return "/"
    if len(target) > 1 and target[1] in "/\\":
        return "/"
    if target[1:4].lower() in ("%5c", "%2f"):
        return "/"
    return target
