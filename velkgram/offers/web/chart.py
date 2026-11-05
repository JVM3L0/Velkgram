"""Price chart and sparkline as inline SVG (colors only via theme CSS variables)."""

from collections.abc import Sequence
from html import escape

from velkgram.offers.ports.queries import PricePoint
from velkgram.offers.web.format import brl

_PRIMARY = "var(--primary)"
_OUTLINE = "var(--outline)"
_MUTED = "var(--on-surface-variant)"
_MAX_LINE = "var(--tertiary)"

_LEFT, _RIGHT, _TOP, _BOTTOM = 76, 12, 14, 12
_LABEL_GAP = 13  # minimum vertical distance between y labels, in px


def _open(width: int, height: int, title: str, desc: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
        f'role="img"><title>{escape(title)}</title><desc>{escape(desc)}</desc>'
    )


def _num(v: float) -> str:
    return f"{v:.1f}"


def price_chart_svg(
    points: Sequence[PricePoint], max_price_cents: int, *, width: int = 640, height: int = 240
) -> str:
    if not points:
        return (
            _open(width, height, "Histórico de preços", "Sem preços ainda.")
            + f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'style="fill:{_MUTED}">Sem preços ainda</text></svg>'
        )
    prices = [p.price_cents for p in points]
    lo_raw, hi_raw = min([*prices, max_price_cents]), max([*prices, max_price_cents])
    pad = (hi_raw - lo_raw) * 0.1 or max(hi_raw * 0.1, 1)
    lo, hi = lo_raw - pad, hi_raw + pad
    plot_w, plot_h = width - _LEFT - _RIGHT, height - _TOP - _BOTTOM

    def y(cents: float) -> float:
        return _TOP + (hi - cents) / (hi - lo) * plot_h

    t0, t1 = points[0].posted_at.timestamp(), points[-1].posted_at.timestamp()

    def x(p: PricePoint) -> float:
        if t1 == t0:
            return _LEFT + plot_w / 2
        return _LEFT + (p.posted_at.timestamp() - t0) / (t1 - t0) * plot_w

    first, last = points[0].posted_at, points[-1].posted_at
    desc = (
        f"{len(points)} preços de {first:%d/%m/%Y} a {last:%d/%m/%Y}. "
        f"Menor {brl(min(prices))}, maior {brl(max(prices))}, preço máximo {brl(max_price_cents)}."
    )
    parts = [_open(width, height, "Histórico de preços", desc)]
    parts.append(
        f'<line x1="{_LEFT}" y1="{_TOP}" x2="{_LEFT}" y2="{height - _BOTTOM}" '
        f'style="stroke:{_OUTLINE}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{_LEFT}" y1="{_num(y(max_price_cents))}" x2="{width - _RIGHT}" '
        f'y2="{_num(y(max_price_cents))}" style="stroke:{_MAX_LINE}" stroke-width="2" '
        'stroke-dasharray="6 4"/>'
    )
    # Label the max-price line first so it wins any collision with the data min/max labels.
    placed: list[float] = []
    for cents in (max_price_cents, max(prices), min(prices)):
        yy = y(cents)
        if any(abs(yy - other) < _LABEL_GAP for other in placed):
            continue
        placed.append(yy)
        parts.append(
            f'<text x="{_LEFT - 6}" y="{_num(yy + 4)}" text-anchor="end" font-size="12" '
            f'style="fill:{_MUTED}">{escape(brl(cents))}</text>'
        )
    coords = [(x(p), y(p.price_cents)) for p in points]
    if len(coords) > 1:
        line = " ".join(f"{_num(cx)},{_num(cy)}" for cx, cy in coords)
        parts.append(
            f'<polyline points="{line}" fill="none" style="stroke:{_PRIMARY}" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    parts.extend(
        f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="4" style="fill:{_PRIMARY}"/>'
        for cx, cy in coords
    )
    parts.append("</svg>")
    rows = "".join(
        f"<tr><td>{p.posted_at:%d/%m/%Y}</td><td>{escape(brl(p.price_cents))}</td></tr>"
        for p in points
    )
    parts.append(
        '<table class="sr-only"><caption>Histórico de preços</caption>'
        f"<tr><th>Data</th><th>Preço</th></tr>{rows}</table>"
    )
    return "".join(parts)


def sparkline_svg(values: Sequence[int], *, width: int = 96, height: int = 28) -> str:
    head = _open(width, height, "Tendência de preço", _spark_desc(values))
    if not values:
        return head + "</svg>"
    pad = 3
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = (width - 2 * pad) / (len(values) - 1) if len(values) > 1 else 0

    def pt(i: int, v: int) -> tuple[float, float]:
        cx = pad + i * step if len(values) > 1 else width / 2
        cy = height / 2 if hi == lo else pad + (hi - v) / span * (height - 2 * pad)
        return cx, cy

    coords = [pt(i, v) for i, v in enumerate(values)]
    body = ""
    if len(coords) > 1:
        line = " ".join(f"{_num(cx)},{_num(cy)}" for cx, cy in coords)
        body += (
            f'<polyline points="{line}" fill="none" style="stroke:{_PRIMARY}" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    cx, cy = coords[-1]
    body += f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="2.5" style="fill:{_PRIMARY}"/>'
    return head + body + "</svg>"


def _spark_desc(values: Sequence[int]) -> str:
    if not values:
        return "Sem preços ainda."
    return f"{len(values)} preços recentes, de {brl(values[0])} a {brl(values[-1])}."
