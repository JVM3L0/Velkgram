"""Theme modes, the `theme` cookie value to `<body>` classes, and safe redirect targets."""

THEME_MODES = ("system", "dark", "light")
THEME_COOKIE = "theme"
THEME_MAX_AGE = 31536000  # one year

# Cookie values from the retired themes map to the nearest of the two that remain.
_LEGACY = {
    "mocha": "dark",
    "macchiato": "dark",
    "frappe": "dark",
    "gruvbox-dark": "dark",
    "latte": "light",
    "gruvbox-light": "light",
}


def theme_classes(mode: str | None) -> str:
    """`<body>` class for a theme cookie value. System and unknown values add none."""
    mode = _LEGACY.get(mode or "", mode)
    return mode if mode in ("dark", "light") else ""


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
