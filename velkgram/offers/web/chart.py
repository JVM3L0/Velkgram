"""Price chart and sparkline as inline SVG (colors only via theme CSS variables)."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo
from html import escape
from itertools import pairwise

from velkgram.offers.ports.queries import PricePoint
from velkgram.offers.web.format import brl

_PRIMARY = "var(--primary)"
_OUTLINE = "var(--outline)"
_MUTED = "var(--on-surface-variant)"
_MAX_LINE = "var(--tertiary)"
_ON_SURFACE = "var(--on-surface)"
_HALO = "var(--surface-container-low)"  # the chart frame colour: a halo keeps labels legible

_LEFT, _RIGHT, _TOP, _BOTTOM = 96, 12, 14, 28
_LABEL_GAP = 14  # minimum vertical distance between y labels, in px
_MAX_LINE_REACH = 0.25  # the max-price line joins the y-range only within this share of the span
_CHAR_W = 7.44  # 0.62 em of the 12 px label: DejaVu/Segoe fallbacks are wider than Roboto Flex
Box = tuple[float, float, float, float]
Spot = tuple[float, float, str]
_HEIGHT = 220  # fixed: text keeps its pixel size because the viewBox is rendered at ~1:1


def _open(width: int, height: int, title: str, desc: str, cls: str = "", extra: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
        f'role="img"{attr}{extra}><title>{escape(title)}</title><desc>{escape(desc)}</desc>'
    )


def _num(v: float) -> str:
    return f"{v:.1f}"


def _text_box(x: float, y: float, text: str, anchor: str) -> Box:
    width = len(text) * _CHAR_W
    left = x if anchor == "start" else x - width
    return left, y - 11, left + width, y + 3


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _fits(box: Box, bounds: Box) -> bool:
    return (
        box[0] >= bounds[0] and box[2] <= bounds[2] and box[1] >= bounds[1] and box[3] <= bounds[3]
    )


def _clean_spot(text: str, spots: Sequence[Spot], taken: list[Box], bounds: Box) -> Spot | None:
    """The first spot whose text box fits inside `bounds` without touching `taken`."""
    for spot in spots:
        box = _text_box(spot[0], spot[1], text, spot[2])
        if _fits(box, bounds) and not any(_overlaps(box, t) for t in taken):
            taken.append(box)
            return spot
    return None


def _place(text: str, spots: Sequence[Spot], taken: list[Box], bounds: Box) -> Spot:
    """A clean spot, else the least-overlapping one inside the plot (the halo keeps it legible)."""
    clean = _clean_spot(text, spots, taken, bounds)
    if clean is not None:
        return clean
    inside = [
        (sum(_overlaps(_text_box(x, y, text, a), t) for t in taken), (x, y, a))
        for x, y, a in spots
        if _fits(_text_box(x, y, text, a), bounds)
    ]
    spot = min(inside, key=lambda item: item[0])[1] if inside else _clamped(spots[0], text, bounds)
    taken.append(_text_box(spot[0], spot[1], text, spot[2]))
    return spot


def _clamped(
    spot: tuple[float, float, str], text: str, bounds: tuple[float, float, float, float]
) -> tuple[float, float, str]:
    x, y, anchor = spot
    width = len(text) * _CHAR_W
    low, high = (
        (bounds[0], bounds[2] - width) if anchor == "start" else (bounds[0] + width, bounds[2])
    )
    return min(max(x, low), high), min(max(y, bounds[1] + 11), bounds[3] - 3), anchor


def _leader(cx: float, cy: float, box: Box) -> str:
    """A hairline from a dot to its label when the label had to move away from it."""
    near_x = min(max(cx, box[0]), box[2])
    near_y = min(max(cy, box[1]), box[3])
    if abs(near_x - cx) < 14 and abs(near_y - cy) < 22:
        return ""
    return (
        f'<line class="chart-leader" x1="{_num(cx)}" y1="{_num(cy)}" x2="{_num(near_x)}" '
        f'y2="{_num(near_y)}" style="stroke:{_OUTLINE}" stroke-width="1"/>'
    )


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


def _step_obstacles(
    coords: Sequence[tuple[float, float]],
) -> list[tuple[float, float, float, float]]:
    """Thin boxes along each horizontal run and vertical step of the line."""
    boxes: list[tuple[float, float, float, float]] = []
    for (x0, y0), (x1, y1) in pairwise(coords):
        boxes.append((x0 - 2, y0 - 2, x1 + 2, y0 + 2))
        boxes.append((x1 - 2, min(y0, y1) - 2, x1 + 2, max(y0, y1) + 2))
    return boxes


def _step_path(coords: Sequence[tuple[float, float]]) -> str:
    """Each price holds until the next observation: horizontal run, then a vertical step."""
    head = f"M{_num(coords[0][0])},{_num(coords[0][1])}"
    return head + "".join(f" H{_num(cx)} V{_num(cy)}" for cx, cy in coords[1:])


def price_chart_svg(
    points: Sequence[PricePoint],
    max_price_cents: int | None,
    *,
    width: int = 800,
    height: int = _HEIGHT,
    variant: str = "wide",
    with_table: bool = True,
    tz: tzinfo = UTC,
) -> str:
    # Every date the chart prints is in the viewer's zone, not UTC.
    points = [PricePoint(p.posted_at.astimezone(tz), p.price_cents) for p in points]
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
    max_in_range = max_price_cents is not None and (
        data_lo - span * _MAX_LINE_REACH <= max_price_cents <= data_hi + span * _MAX_LINE_REACH
    )
    lo_raw = min(data_lo, max_price_cents) if max_in_range and max_price_cents else data_lo
    hi_raw = max(data_hi, max_price_cents) if max_in_range and max_price_cents else data_hi
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
        f"média {brl(average)}"
        + (f", seu alerta {brl(max_price_cents)}." if max_price_cents is not None else ".")
    )
    # velkgram.js reads these for the tooltip: [x, y, "date", "price"] per point (viewBox units).
    days = {p.posted_at.date() for p in points}
    stamp = "%d/%m/%Y %H:%M" if len(days) < len(points) else "%d/%m/%Y"
    tips = json.dumps(
        [
            [
                round(x(p), 1),
                round(y(p.price_cents), 1),
                f"{p.posted_at:{stamp}}",
                brl(p.price_cents),
            ]
            for p in points
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    parts = [
        _open(width, height, "Histórico de preços", desc, cls, f' data-points="{escape(tips)}"')
    ]
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
    alert_y = y(max_price_cents) if max_price_cents is not None else 0.0
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
    # Labels must not sit on the step line or the alert line, so those are obstacles too.
    taken = _step_obstacles(coords)
    if max_in_range:
        taken.append((float(_LEFT), alert_y - 2, float(right), alert_y + 2))
    if len(coords) > 1:
        taken.append((float(_LEFT), y(average) - 1.5, float(right), y(average) + 1.5))
    labels: list[str] = []
    leaders: list[str] = []
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
        # Start-anchored text begins right of the dot and end-anchored text stops left of it,
        # so neither lies on the vertical step that reaches the dot.
        sides = ((cx + 8, "start"), (cx - 8, "end"))
        prefer_below = i == low_i and not merged
        # Nearest free row first; the dot's own tooltip names it when the label sits further off.
        offsets = sorted(
            [*range(-10, -130, -16), *range(18, 120, 16)],
            key=lambda dy: (abs(dy), (dy > 0) != prefer_below),
        )
        spots = [(x, cy + dy, a) for dy in offsets for x, a in sides]
        lx, ly, anchor = _place(text, spots, taken, bounds)
        leaders.append(_leader(cx, cy, _text_box(lx, ly, text, anchor)))
        labels.append(_label(lx, ly, anchor, text))
    if max_price_cents is None:
        pass
    elif max_in_range:
        # The full "Seu alerta R$ x" when it fits cleanly, else just "Seu alerta" (the page
        # header states the value), else the full text over the line with its halo.
        full = f"Seu alerta {brl(max_price_cents)}"
        dys = sorted([*range(-6, -80, -16), *range(16, 80, 16)], key=lambda dy: (abs(dy), dy > 0))
        chosen: tuple[str, tuple[float, float, str]] | None = None
        for text in (full, "Seu alerta"):
            xs = [(right - 4, "end"), (_LEFT + 6, "start")]
            xs += [
                (float(sx), "start")
                for sx in range(_LEFT + 18, int(right - len(text) * _CHAR_W), 12)
            ]
            spots = [(sx, alert_y + dy, anchor) for dy in dys for sx, anchor in xs]
            spot = _clean_spot(text, spots, taken, bounds)
            if spot is not None:
                chosen = (text, spot)
                break
        if chosen is None:
            spots = [(right - 4, alert_y - 6, "end"), (_LEFT + 6, alert_y - 6, "start")]
            chosen = (full, _place(full, spots, taken, bounds))
        labels.append(_label(chosen[1][0], chosen[1][1], chosen[1][2], chosen[0]))
    else:
        parts.append(_max_marker(max_price_cents, above=max_price_cents > data_hi, width=width))
    parts.extend(leaders)
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


def price_chart_responsive(
    points: Sequence[PricePoint], max_price_cents: int | None, tz: tzinfo = UTC
) -> str:
    """Compact, medium and wide charts; CSS shows one, so text stays ~12 px at every viewport."""
    sizes = (("compact", 340), ("medium", 520), ("wide", 800))
    return "".join(
        price_chart_svg(
            points, max_price_cents, width=w, variant=name, with_table=name == "wide", tz=tz
        )
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
