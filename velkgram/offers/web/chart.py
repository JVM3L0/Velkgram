"""Price chart and sparkline as inline SVG (colors only via theme CSS variables)."""

from collections.abc import Sequence
from datetime import datetime
from html import escape

from velkgram.offers.ports.queries import PricePoint
from velkgram.offers.web.format import brl

_PRIMARY = "var(--primary)"
_OUTLINE = "var(--outline)"
_MUTED = "var(--on-surface-variant)"
_MAX_LINE = "var(--tertiary)"
_ON_SURFACE = "var(--on-surface)"
_HALO = "var(--surface-container-low)"  # the chart frame colour: a halo keeps labels legible

_LEFT, _RIGHT, _TOP, _BOTTOM = 78, 12, 14, 28
_LABEL_GAP = 14  # minimum vertical distance between y labels, in px
_MAX_LINE_REACH = 0.25  # the max-price line joins the y-range only within this share of the span
_CHAR_W = 6.8  # average glyph width of the 12 px label font, for collision checks
_HEIGHT = 220  # fixed: text keeps its pixel size because the viewBox is rendered at ~1:1


def _open(width: int, height: int, title: str, desc: str, cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
        f'role="img"{attr}><title>{escape(title)}</title><desc>{escape(desc)}</desc>'
    )


def _num(v: float) -> str:
    return f"{v:.1f}"


def _text_box(x: float, y: float, text: str, anchor: str) -> tuple[float, float, float, float]:
    width = len(text) * _CHAR_W
    left = x if anchor == "start" else x - width
    return left, y - 11, left + width, y + 3


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _place(
    text: str,
    spots: Sequence[tuple[float, float, str]],
    taken: list[tuple[float, float, float, float]],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, str]:
    """The first spot whose text box fits inside `bounds` without touching `taken`."""
    for x, y, anchor in spots:
        box = _text_box(x, y, text, anchor)
        inside = box[0] >= bounds[0] and box[2] <= bounds[2] and box[1] >= bounds[1]
        if inside and box[3] <= bounds[3] and not any(_overlaps(box, t) for t in taken):
            taken.append(box)
            return x, y, anchor
    x, y, anchor = spots[0]
    taken.append(_text_box(x, y, text, anchor))
    return x, y, anchor


def _label(x: float, y: float, anchor: str, text: str) -> str:
    return (
        f'<text x="{_num(x)}" y="{_num(y)}" text-anchor="{anchor}" font-size="12" '
        f'font-weight="600" paint-order="stroke" stroke-width="4" stroke-linejoin="round" '
        f'style="fill:{_ON_SURFACE};stroke:{_HALO}">{escape(text)}</text>'
    )


def _dot(cx: float, cy: float, title: str) -> str:
    return (
        f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="5" stroke-width="2" '
        f'style="fill:{_PRIMARY};stroke:{_HALO}"><title>{escape(title)}</title></circle>'
    )


def _step_path(coords: Sequence[tuple[float, float]]) -> str:
    """Each price holds until the next observation: horizontal run, then a vertical step."""
    head = f"M{_num(coords[0][0])},{_num(coords[0][1])}"
    return head + "".join(f" H{_num(cx)} V{_num(cy)}" for cx, cy in coords[1:])


def price_chart_svg(
    points: Sequence[PricePoint],
    max_price_cents: int,
    *,
    width: int = 800,
    height: int = _HEIGHT,
    variant: str = "wide",
    with_table: bool = True,
) -> str:
    cls = f"chart-svg chart-svg-{variant}"
    if not points:
        return (
            _open(width, height, "Histórico de preços", "Sem preços ainda.", cls)
            + f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'style="fill:{_MUTED}">Sem preços ainda</text></svg>'
        )
    prices = [p.price_cents for p in points]
    data_lo, data_hi = min(prices), max(prices)
    average = round(sum(prices) / len(prices))
    current = prices[-1]
    span = (data_hi - data_lo) or max(data_hi * 0.1, 1)
    max_in_range = (
        data_lo - span * _MAX_LINE_REACH <= max_price_cents <= data_hi + span * _MAX_LINE_REACH
    )
    lo_raw = min(data_lo, max_price_cents) if max_in_range else data_lo
    hi_raw = max(data_hi, max_price_cents) if max_in_range else data_hi
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
        f"Menor {brl(data_lo)}, maior {brl(data_hi)}, atual {brl(current)}, "
        f"média {brl(average)}, seu alerta {brl(max_price_cents)}."
    )
    parts = [_open(width, height, "Histórico de preços", desc, cls)]
    axis_y = height - _BOTTOM
    right = width - _RIGHT
    parts.append(
        f'<line x1="{_LEFT}" y1="{_TOP}" x2="{_LEFT}" y2="{axis_y}" '
        f'style="stroke:{_OUTLINE}" stroke-width="1"/>'
        f'<line x1="{_LEFT}" y1="{axis_y}" x2="{right}" y2="{axis_y}" '
        f'style="stroke:{_OUTLINE}" stroke-width="1"/>'
    )
    placed_y: list[float] = []
    for cents in (data_hi, data_lo):
        yy = y(cents)
        if any(abs(yy - other) < _LABEL_GAP for other in placed_y):
            continue
        placed_y.append(yy)
        parts.append(
            f'<text x="{_LEFT - 6}" y="{_num(yy + 4)}" text-anchor="end" font-size="12" '
            f'style="fill:{_MUTED}">{escape(brl(cents))}</text>'
        )
    parts.append(_date_labels(first, last, width, axis_y))

    coords = [(x(p), y(p.price_cents)) for p in points]
    if len(coords) > 1:
        step = _step_path(coords)
        base = f"{_num(coords[0][0])},{_num(axis_y)}"
        parts.append(
            f'<path class="chart-area" d="M{base} L{_num(coords[0][0])},{_num(coords[0][1])}'
            f'{step[step.index(" ") :]} V{_num(axis_y)} Z" fill-opacity="0.14" '
            f'style="fill:{_PRIMARY}"/>'
        )
        if average != data_lo or average != data_hi:
            parts.append(
                f'<line class="chart-avg" x1="{_LEFT}" y1="{_num(y(average))}" x2="{right}" '
                f'y2="{_num(y(average))}" style="stroke:{_OUTLINE}" stroke-width="1" '
                'stroke-opacity="0.7"/>'
            )
    # Draw order: average, alert line, step line, dots, labels.
    alert_y = y(max_price_cents)
    if max_in_range:
        parts.append(
            f'<line x1="{_LEFT}" y1="{_num(alert_y)}" x2="{right}" y2="{_num(alert_y)}" '
            f'style="stroke:{_MAX_LINE}" stroke-width="2" stroke-dasharray="6 4"/>'
        )
    if len(coords) > 1:
        parts.append(
            f'<path class="chart-step" d="{_step_path(coords)}" fill="none" '
            f'style="stroke:{_PRIMARY}" stroke-width="2" stroke-linejoin="round" '
            'stroke-linecap="round"/>'
        )
    low_i = min(range(len(prices)), key=lambda i: (prices[i], -i))
    cur_i = len(prices) - 1
    merged = prices[low_i] == current
    bounds = (float(_LEFT), float(_TOP - 4), float(right), float(axis_y))
    taken: list[tuple[float, float, float, float]] = []
    labels: list[str] = []
    dots = [(cur_i, "Menor e atual" if merged else "Atual")]
    if not merged:
        dots.append((low_i, "Menor"))
    for i, word in dots:
        cx, cy = coords[i]
        taken.append((cx - 6, cy - 6, cx + 6, cy + 6))
        parts.append(_dot(cx, cy, f"{word} {brl(prices[i])}"))
    for i, word in dots:
        cx, cy = coords[i]
        text = f"{word} {brl(prices[i])}"
        edge = min(cx + 4, right)  # a label right of the plot would be cut off
        above = [(cx - 4, cy - 10, "start"), (edge, cy - 10, "end")]
        below = [(cx - 4, cy + 18, "start"), (edge, cy + 18, "end")]
        spots = below + above if i == low_i and not merged else above + below
        lx, ly, anchor = _place(text, spots, taken, bounds)
        labels.append(_label(lx, ly, anchor, text))
    alert_text = f"Seu alerta {brl(max_price_cents)}"
    if max_in_range:
        spots = [
            (right - 4, alert_y - 6, "end"),
            (_LEFT + 6, alert_y - 6, "start"),
            (right - 4, alert_y + 16, "end"),
            (_LEFT + 6, alert_y + 16, "start"),
        ]
        lx, ly, anchor = _place(alert_text, spots, taken, bounds)
        labels.append(_label(lx, ly, anchor, alert_text))
    else:
        parts.append(_max_marker(max_price_cents, above=max_price_cents > data_hi, width=width))
    parts.extend(labels)
    parts.append("</svg>")
    if with_table:
        rows = "".join(
            f"<tr><td>{p.posted_at:%d/%m/%Y}</td><td>{escape(brl(p.price_cents))}</td></tr>"
            for p in points
        )
        parts.append(
            '<table class="sr-only"><caption>Histórico de preços</caption>'
            f"<tr><th>Data</th><th>Preço</th></tr>{rows}</table>"
        )
    return "".join(parts)


def price_chart_responsive(points: Sequence[PricePoint], max_price_cents: int) -> str:
    """Compact, medium and wide charts; CSS shows one, so text stays ~12 px at every viewport."""
    sizes = (("compact", 340), ("medium", 520), ("wide", 800))
    return "".join(
        price_chart_svg(points, max_price_cents, width=w, variant=name, with_table=name == "wide")
        for name, w in sizes
    )


def _max_marker(max_price_cents: int, *, above: bool, width: int) -> str:
    """The max price lies far outside the data: a labelled arrow at the top or bottom edge."""
    right = width - _RIGHT
    if above:
        tip, base, text_y, arrow = _TOP, _TOP + 8, _TOP + 20, "↑"
    else:
        edge = _HEIGHT - _BOTTOM
        tip, base, text_y, arrow = edge, edge - 8, edge - 14, "↓"
    return (
        f'<path class="max-marker" d="M{right - 8},{base} L{right},{base} L{right - 4},{tip} Z" '
        f'style="fill:{_MAX_LINE}"/>'
        f'<text x="{right - 12}" y="{text_y}" text-anchor="end" font-size="12" '
        f'style="fill:{_MUTED}">Seu alerta {escape(brl(max_price_cents))} {arrow}</text>'
    )


def _date_labels(first: datetime, last: datetime, width: int, axis_y: int) -> str:
    base_y = axis_y + 16
    out = (
        f'<text x="{_LEFT}" y="{base_y}" font-size="12" style="fill:{_MUTED}">{first:%d/%m}</text>'
    )
    if (first.year, first.month, first.day) != (last.year, last.month, last.day):
        out += (
            f'<text x="{width - _RIGHT}" y="{base_y}" text-anchor="end" font-size="12" '
            f'style="fill:{_MUTED}">{last:%d/%m}</text>'
        )
    return out


def sparkline_svg(values: Sequence[int], *, width: int = 96, height: int = 28) -> str:
    head = _open(width, height, "Tendência de preço", _spark_desc(values))
    if not values:
        return head + "</svg>"
    pad = 5
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
