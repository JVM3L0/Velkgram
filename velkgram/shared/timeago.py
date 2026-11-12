"""Relative time in pt-BR for web pages (pure)."""

from datetime import timedelta

# The number and its unit never split across lines ("há 23 / h").
_NB = "\u00a0"


def ago(delta: timedelta) -> str:
    """ "há 5 s", "há 3 min", "há 2 h", "há 4 d"; "agora" for a clock-skewed future time."""
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "agora"
    if seconds < 60:
        return f"há {seconds}{_NB}s"
    if seconds < 3600:
        return f"há {seconds // 60}{_NB}min"
    if seconds < 86400:
        return f"há {seconds // 3600}{_NB}h"
    return f"há {seconds // 86400}{_NB}d"
