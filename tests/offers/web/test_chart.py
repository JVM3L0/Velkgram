import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

from velkgram.offers import PricePoint, sparkline_svg
from velkgram.offers.web.chart import price_chart_svg
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
    assert root.get("viewBox") == "0 0 640 240"
    assert "{http://www.w3.org/2000/svg}title" in [c.tag for c in root]
    assert "{http://www.w3.org/2000/svg}desc" in [c.tag for c in root]
    assert out.count("<circle") == 3
    assert "<polyline" in out


def test_chart_draws_dashed_max_price_line() -> None:
    out = price_chart_svg(_pts(100000, 90000), 95000)
    assert re.search(r"<line[^>]*stroke-dasharray", out)


def test_chart_uses_only_css_variables_for_color() -> None:
    for out in (price_chart_svg(_pts(1, 2, 3), 2), price_chart_svg([], 2), sparkline_svg([1, 2])):
        assert "#" not in out
        used = set(re.findall(r"var\((--[a-z-]+)\)", out))
        assert used <= {"--primary", "--outline", "--on-surface-variant", "--tertiary"}


def test_chart_empty_state() -> None:
    out = price_chart_svg([], 50000)
    assert "Sem preços ainda" in out
    assert "<polyline" not in out
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
    out = price_chart_svg(_pts(100000), 90000)
    assert out.count("<circle") == 1
    assert "<polyline" not in out
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
