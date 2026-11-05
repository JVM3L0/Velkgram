"""WCAG AA contrast of every theme pair in velkgram.css, for all four flavours (NFR5)."""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).parents[3] / "velkgram" / "apps" / "web" / "static" / "velkgram.css"
FLAVOURS = ("latte", "frappe", "macchiato", "mocha")
ROLES = ("primary", "secondary", "tertiary", "error")
SURFACES = ("surface", "surface-container-lowest", "surface-container-low", "surface-container")
LOUD_SURFACES = ("surface-container-high", "surface-container-highest")
_NOT_OTHERS = ":not(.frappe):not(.macchiato):not(.mocha)"


def _rules() -> list[tuple[str, dict[str, str]]]:
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(), flags=re.S)
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        variables = dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", body))
        rules.append((" ".join(selector.split()), variables))
    return rules


def _flavour(name: str) -> dict[str, str]:
    for selector, variables in _rules():
        if f"body.{name}" in [s.strip() for s in selector.split(",")]:
            return {k.removeprefix("--"): v for k, v in variables.items()}
    raise AssertionError(f"no body.{name} block in velkgram.css")


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
    pairs += [(role, "surface", 4.5) for role in ("primary", "success", "warning")]
    pairs.append(("outline", "surface", 3.0))
    return pairs


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_contrast_of_every_pair_passes_wcag_aa(flavour: str) -> None:
    colours = _flavour(flavour)
    failures = []
    for fg, bg, threshold in _pairs():
        ratio = contrast(colours[fg], colours[bg])
        if ratio < threshold:
            failures.append(f"{flavour}: {fg} {colours[fg]} on {bg} {colours[bg]} = {ratio:.2f}")
    assert not failures, "\n".join(failures)


def test_system_mode_uses_latte_by_default_and_mocha_in_dark_scheme() -> None:
    rules = _rules()
    latte = _flavour("latte")
    mocha = _flavour("mocha")
    default = [v for s, v in rules if s.endswith(f"body{_NOT_OTHERS}") and "body.latte" in s]
    assert default
    assert {k.removeprefix("--"): c for k, c in default[0].items()} == latte
    dark = [v for s, v in rules if s == f"body:not(.latte){_NOT_OTHERS}"]
    assert dark
    assert {k.removeprefix("--"): c for k, c in dark[0].items()} == mocha
    assert "prefers-color-scheme: dark" in CSS.read_text()
