from tests.reporting.test_metrics import D1, D2, FakeAlerts, FakeMsgs, price
from velkgram.reporting.services.metrics import build_report
from velkgram.reporting.services.render import render_report


def test_render_contains_totals() -> None:
    msgs = FakeMsgs([(D1, 2, 1, "R$ 1"), (D1, 1, 2, "oi"), (D2, 1, 3, "oi")])
    out = render_report(build_report(msgs, FakeAlerts(), price, D1, D2, 1.0))
    lines = out.splitlines()
    assert "latency_telegram_ms" in lines[0]
    assert sum("TOTAL" in line for line in lines) == 2
    assert "2026-11-01" in out and "2026-11-02" in out
    d1_rows = [ln for ln in lines if ln.startswith("2026-11-01")]
    assert d1_rows[0].split()[1] == "1" and d1_rows[1].split()[1] == "2"
    assert d1_rows[2].split()[1] == "TOTAL"
