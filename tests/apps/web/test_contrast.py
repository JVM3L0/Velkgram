"""WCAG AA contrast of every theme pair in velkgram.css, for every flavour (NFR5)."""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).parents[3] / "velkgram" / "apps" / "web" / "static" / "velkgram.css"
THEMES = ("light", "dark")
TOKENS = "body:not(.themed)"
ROLES = ("primary", "secondary", "tertiary", "error")
SURFACES = ("surface", "surface-container-lowest", "surface-container-low", "surface-container")
LOUD_SURFACES = ("surface-container-high", "surface-container-highest")
_PAIR = re.compile(
    r"(--[\w-]+)\s*:\s*light-dark\(\s*(#[0-9a-fA-F]{6})\s*,\s*(#[0-9a-fA-F]{6})\s*\)\s*;"
)


def _rules() -> list[tuple[str, str]]:
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(), flags=re.S)
    return [
        (" ".join(sel.split()), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)
    ]


def _theme(name: str) -> dict[str, str]:
    """Every colour token of one theme, from the single `body` block of light-dark() pairs."""
    for selector, body in _rules():
        if selector == TOKENS and _PAIR.search(body):
            index = THEMES.index(name)
            return {k.removeprefix("--"): m[index] for k, *m in _tokens(body)}
    raise AssertionError("no body block of light-dark() tokens in velkgram.css")


def _tokens(body: str) -> list[tuple[str, str, str]]:
    return [(name, light, dark) for name, light, dark in _PAIR.findall(body)]


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _pairs() -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    for role in ROLES:
        pairs.append((f"on-{role}", role, 4.5))
        pairs.append((f"on-{role}-container", f"{role}-container", 4.5))
    for fg in ("on-surface", "on-surface-variant"):
        pairs += [(fg, bg, 4.5) for bg in SURFACES]
    pairs += [("on-surface", bg, 4.5) for bg in LOUD_SURFACES]
    # The teal "Abrir" link and price text sit on cards and containers.
    pairs += [("primary", bg, 4.5) for bg in SURFACES[:3]]  # cards use surface..low
    pairs += [(role, "surface", 4.5) for role in ("primary", "success", "warning")]
    pairs.append(
        ("amber", "surface", 4.5)
    )  # the stale-collector banner icon (3:1 needed on its tint)
    pairs.append(("outline", "surface", 3.0))
    return pairs


@pytest.mark.parametrize("theme", THEMES)
def test_contrast_of_every_pair_passes_wcag_aa(theme: str) -> None:
    colours = _theme(theme)
    failures = []
    for fg, bg, threshold in _pairs():
        ratio = contrast(colours[fg], colours[bg])
        if ratio < threshold:
            failures.append(f"{theme}: {fg} {colours[fg]} on {bg} {colours[bg]} = {ratio:.2f}")
    assert not failures, "\n".join(failures)


def test_the_two_themes_define_exactly_the_same_tokens() -> None:
    assert set(_theme("light")) == set(_theme("dark"))
    assert set(_theme("light")) >= {"primary", "surface", "on-surface", "outline", "error"}


def test_system_mode_follows_the_device_and_the_classes_force_a_theme() -> None:
    rules = dict(_rules())
    assert "color-scheme: light dark" in rules[TOKENS]
    assert "color-scheme: light" in rules["body.light"]
    assert "color-scheme: dark" in rules["body.dark"]
