import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

from velkgram.offers import PricePoint, sparkline_svg
from velkgram.offers.web.chart import _CHAR_W, price_chart_responsive, price_chart_svg
from velkgram.offers.web.format import brl

T0 = datetime(2026, 3, 1, tzinfo=UTC)


def _pts(*cents: int) -> list[PricePoint]:
    return [PricePoint(T0 + timedelta(days=i), c) for i, c in enumerate(cents)]


def _svg_only(out: str) -> str:
    return out[: out.index("</svg>") + 6]


def test_chart_has_title_desc_and_points() -> None:
    out = price_chart_svg(_pts(100000, 90000, 95000), 99000)
    root = ET.fromstring(_svg_only(out))
    assert root.get("role") == "img"
    assert root.get("width") == "100%"
    assert root.get("viewBox") == "0 0 800 220"
    assert "{http://www.w3.org/2000/svg}title" in [c.tag for c in root]
    assert "{http://www.w3.org/2000/svg}desc" in [c.tag for c in root]
    assert out.count("<circle") == 2  # only the lowest and the current price get a dot
    assert 'class="chart-step"' in out


def test_chart_draws_dashed_max_price_line() -> None:
    out = price_chart_svg(_pts(100000, 90000), 95000)
    assert re.search(r"<line[^>]*stroke-dasharray", out)


def test_chart_uses_only_css_variables_for_color() -> None:
    for out in (price_chart_svg(_pts(1, 2, 3), 2), price_chart_svg([], 2), sparkline_svg([1, 2])):
        assert "#" not in out
        used = set(re.findall(r"var\((--[a-z-]+)\)", out))
        assert used <= {
            "--primary",
            "--outline",
            "--on-surface-variant",
            "--tertiary",
            "--surface-container-low",
            "--on-surface",
        }


def test_chart_empty_state() -> None:
    out = price_chart_svg([], 50000)
    assert "Sem preços ainda" in out
    assert "chart-step" not in out
    ET.fromstring(out)


def test_chart_formats_brl_labels() -> None:
    out = price_chart_svg(_pts(129990, 99900), 110000)
    assert "R$ 1.299,90" in out
    assert "R$ 999,00" in out
    assert "R$ 1.100,00" in out


def test_sparkline_scales_to_box() -> None:
    out = sparkline_svg([10, 50, 30], width=96, height=28)
    root = ET.fromstring(out)
    assert root.get("viewBox") == "0 0 96 28"
    pts = re.search(r'<polyline[^>]*points="([^"]+)"', out)
    assert pts is not None
    coords = [tuple(map(float, p.split(","))) for p in pts.group(1).split()]
    assert len(coords) == 3
    assert all(0 <= x <= 96 and 0 <= y <= 28 for x, y in coords)
    assert coords[1][1] < coords[2][1] < coords[0][1]  # higher value, higher on screen
    assert coords[0][0] < coords[1][0] < coords[2][0]


def test_sparkline_flat_and_tiny_inputs() -> None:
    assert "<polyline" in sparkline_svg([5, 5, 5])
    ET.fromstring(sparkline_svg([]))
    ET.fromstring(sparkline_svg([7]))


def test_chart_includes_hidden_data_table() -> None:
    out = price_chart_svg(_pts(100000, 90000), 95000)
    table = out[out.index("</svg>") :]
    assert '<table class="sr-only">' in table
    assert "01/03/2026" in table and "R$ 1.000,00" in table
    assert table.count("<tr>") >= 3  # header + 2 rows


def test_chart_single_point() -> None:
    out = price_chart_svg(_pts(100000), 98000)
    assert out.count("<circle") == 1
    assert "chart-step" not in out
    assert re.search(r"<line[^>]*stroke-dasharray", out)
    ET.fromstring(_svg_only(out))


def test_chart_escapes_text() -> None:
    out = price_chart_svg(_pts(100000, 90000), 95000)
    ET.fromstring(f"<div>{out}</div>")  # well-formed: nothing unescaped slipped into text
    assert "&" not in re.sub(r"&(amp|lt|gt|quot|#\d+);", "", out)


def test_brl_formats_thousands_and_unknown() -> None:
    assert brl(129990) == "R$ 1.299,90"
    assert brl(5) == "R$ 0,05"
    assert brl(100000000) == "R$ 1.000.000,00"
    assert brl(None) == "preço não identificado"


def _circle_ys(out: str) -> list[float]:
    path = re.search(r'class="chart-step" d="([^"]+)"', out)
    assert path is not None
    return [float(v) for v in re.findall(r"(?:V|,)([\d.]+)", path.group(1))]


def test_chart_y_range_follows_data_when_max_price_is_far_away() -> None:
    out = price_chart_svg(_pts(116900, 170900, 140000), 8000)
    ys = _circle_ys(out)
    assert max(ys) - min(ys) > 120  # the real offers fill most of the 220 px plot
    assert not re.search(r"<line[^>]*stroke-dasharray", out)
    assert 'class="max-marker"' in out
    assert "R$ 80,00" in out  # still labelled, as a marker at the bottom edge


def test_chart_far_max_above_data_marks_the_top_edge() -> None:
    out = price_chart_svg(_pts(10000, 12000), 900000)
    assert 'class="max-marker"' in out
    assert not re.search(r"<line[^>]*stroke-dasharray", out)
    assert "R$ 9.000,00" in out


def test_chart_keeps_dashed_line_when_max_is_within_a_quarter_of_the_range() -> None:
    out = price_chart_svg(_pts(100000, 120000), 124000)  # 4000 above a 20000 span
    assert re.search(r"<line[^>]*stroke-dasharray", out)
    assert "max-marker" not in out


def test_chart_variants_carry_a_class_and_skip_the_table_on_request() -> None:
    out = price_chart_svg(
        _pts(100000, 90000), 95000, width=340, variant="compact", with_table=False
    )
    assert 'class="chart-svg chart-svg-compact"' in out
    assert 'viewBox="0 0 340 220"' in out
    assert "<table" not in out


def test_chart_labels_first_and_last_date() -> None:
    out = price_chart_svg(_pts(100000, 90000, 95000), 95000)
    assert ">01/03<" in out and ">03/03<" in out


def test_responsive_chart_renders_three_sizes_with_one_table() -> None:
    out = price_chart_responsive(_pts(100000, 90000, 95000), 99000)
    assert out.count("<svg") == 3
    for width in (340, 520, 800):
        assert f'viewBox="0 0 {width} 220"' in out
    assert out.count("<table") == 1


def test_chart_is_a_step_line_with_an_area_below_it() -> None:
    out = price_chart_svg(_pts(100000, 90000, 95000), 99000)
    step = re.search(r'<path class="chart-step" d="([^"]+)"', out)
    assert step is not None
    assert re.fullmatch(r"M[\d.]+,[\d.]+( H[\d.]+ V[\d.]+)+", step.group(1))  # holds, then drops
    area = re.search(r'<path class="chart-area" d="([^"]+)"[^>]*fill-opacity', out)
    assert area is not None and area.group(1).endswith("Z")


def test_chart_labels_lowest_and_current_price() -> None:
    out = price_chart_svg(_pts(100000, 90000, 95000), 99000)
    assert "Menor R$ 900,00" in out and "Atual R$ 950,00" in out
    merged = price_chart_svg(_pts(100000, 95000, 90000), 99000)
    assert "Menor e atual R$ 900,00" in merged
    assert merged.count("<circle") == 1


def test_chart_has_a_faint_average_line_and_labels_the_alert() -> None:
    out = price_chart_svg(_pts(100000, 90000, 95000), 99000)
    assert 'class="chart-avg"' in out
    assert "Seu alerta R$ 990,00" in out
    assert "R$ 950,00" in re.search(r"<desc>(.*?)</desc>", out).group(1)  # type: ignore[union-attr]
    far = price_chart_svg(_pts(116900, 170900, 140000), 8000)
    assert "Seu alerta R$ 80,00" in far
    assert "chart-avg" not in price_chart_svg(_pts(100000), 98000)


_SYNTHETIC = (
    _pts(149000, 163000, 171000, 149000, 158000, 152000),  # lowest at both ends of the run
    _pts(100000, 90000, 95000),
    _pts(129990, 99900, 120000),
    _pts(80000, 90000, 100000, 120000, 149000),  # rising to the right edge
    _pts(149000, 120000, 100000, 90000),  # falling to the right edge
)


def _labels(out: str) -> list[tuple[float, float, str, str]]:
    found = re.findall(
        r'<text x="([\d.]+)" y="([\d.]+)" text-anchor="(\w+)"[^>]*font-weight="600"[^>]*>([^<]+)<',
        out,
    )
    return [(float(x), float(y), a, t) for x, y, a, t in found]


def _box(x: float, y: float, anchor: str, text: str) -> tuple[float, float, float, float]:
    w = len(text) * _CHAR_W
    left = x if anchor == "start" else x - w
    return left, y - 11, left + w, y + 3


def _step_segments(out: str) -> list[tuple[float, float, float, float]]:
    d = re.search(r'class="chart-step" d="([^"]+)"', out).group(1)  # type: ignore[union-attr]
    x, y = map(float, re.match(r"M([\d.]+),([\d.]+)", d).groups())  # type: ignore[union-attr]
    segments = []
    for cmd, value in re.findall(r"([HV])([\d.]+)", d):
        v = float(value)
        if cmd == "H":
            segments.append((min(x, v), y, max(x, v), y))
            x = v
        else:
            segments.append((x, min(y, v), x, max(y, v)))
            y = v
    return segments


def test_chart_labels_stay_inside_the_viewbox() -> None:
    for width in (340, 520, 800):
        for pts in _SYNTHETIC:
            out = price_chart_svg(pts, 110000, width=width)
            labels = _labels(out)
            assert labels
            for x, y, anchor, text in labels:
                left, top, right, bottom = _box(x, y, anchor, text)
                assert left >= 0 and right <= width, (width, text)
                assert top >= 0 and bottom <= 220, (width, text)


def test_chart_labels_do_not_sit_on_the_step_line() -> None:
    # At 340 px the plot is 232 px wide: a ~115 px label has no free spot, only its halo.
    for width in (520, 800):
        for pts in _SYNTHETIC:
            out = price_chart_svg(pts, 110000, width=width)
            for x, y, anchor, text in _labels(out):
                left, top, right, bottom = _box(x, y, anchor, text)
                for sx0, sy0, sx1, sy1 in _step_segments(out):
                    touches = sx0 <= right and sx1 >= left and sy0 <= bottom and sy1 >= top
                    assert not touches, (width, text, (sx0, sy0, sx1, sy1))


def test_chart_draws_a_leader_when_a_label_had_to_move_away_from_its_dot() -> None:
    crowded = price_chart_svg(_SYNTHETIC[0], 110000, width=340)
    assert 'class="chart-leader"' in crowded
    calm = price_chart_svg(_pts(100000, 90000, 95000), 99000)
    assert "chart-leader" not in calm


FALLBACK_CHAR_W = 0.62 * 12  # DejaVu / Segoe digits are wider than Roboto Flex


def _all_text_boxes(out: str) -> list[tuple[float, float, str]]:
    boxes = []
    for attrs, text in re.findall(r"<text ([^>]*)>([^<]+)<", out):
        x = float(re.search(r'x="([\d.]+)"', attrs)[1])  # type: ignore[index]
        end = 'text-anchor="end"' in attrs
        width = len(text) * FALLBACK_CHAR_W
        boxes.append((x - width if end else x, width, text))
    return boxes


def test_four_digit_labels_fit_the_viewbox_with_wide_fallback_fonts() -> None:
    series = (
        _pts(199000, 150000, 202200),  # the highest price is also the newest, at the right edge
        _pts(120000, 202200),
        _pts(202200),
        _pts(1234500, 202200),  # a five-digit-reais axis label
    )
    for width in (340, 520, 800):
        for pts in series:
            boxes = _all_text_boxes(price_chart_svg(pts, 250000, width=width))
            assert boxes
            for left, w, text in boxes:
                assert left >= 0 and left + w <= width, (width, text, left)


def test_a_chart_without_an_alert_line_draws_no_alert_text_or_line() -> None:
    from datetime import UTC, datetime, timedelta

    from velkgram.offers.ports.queries import PricePoint
    from velkgram.offers.web.chart import price_chart_responsive

    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    points = [PricePoint(t0 + timedelta(days=i), 100_000 - i * 1000) for i in range(6)]
    svg = price_chart_responsive(points, None)
    assert "chart-step" in svg and "Menor" in svg
    assert "alerta" not in svg.lower()
    assert "stroke-dasharray" not in svg  # the dashed alert line


def test_chart_prints_dates_in_the_given_zone_not_utc() -> None:
    from zoneinfo import ZoneInfo

    late = [
        PricePoint(datetime(2026, 3, 1, 1, 0, tzinfo=UTC), 100),
        PricePoint(T0 + timedelta(days=2, hours=1), 90),
    ]
    utc = price_chart_svg(late, None)
    local = price_chart_svg(late, None, tz=ZoneInfo("America/Sao_Paulo"))
    assert "01/03/2026" in utc and "28/02/2026" not in utc
    assert "28/02/2026" in local and "02/03/2026" in local
