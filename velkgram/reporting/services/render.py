"""Plain-text rendering of a usage report."""

from velkgram.reporting.services.metrics import Report, ReportRow

_HEADERS = (
    "day",
    "channel",
    "msgs",
    "priced%",
    "alerts",
    "fail",
    "suppressed",
    "p50_ms",
    "p95_ms",
    "tok_all",
    "tok_dedup",
    "usd_all",
    "usd_dedup",
)


def _num(value: float | None, digits: int = 0) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _cells(r: ReportRow) -> list[str]:
    ratio = "-" if r.priced_ratio is None else f"{r.priced_ratio * 100:.0f}%"
    sup = ",".join(f"{k}={v}" for k, v in sorted(r.suppressions.items())) or "-"
    return [
        r.day.isoformat(),
        "TOTAL" if r.channel_id is None else str(r.channel_id),
        str(r.messages),
        ratio,
        str(r.alerts),
        str(r.failures),
        sup,
        _num(r.latency_p50_ms),
        _num(r.latency_p95_ms),
        str(r.tokens_all),
        str(r.tokens_after_dedup),
        _num(r.cost_all_usd, 4),
        _num(r.cost_after_dedup_usd, 4),
    ]


def render_report(r: Report) -> str:
    totals = {t.day: t for t in r.day_totals}
    table: list[list[str]] = []
    for day in sorted(totals):
        table.extend(_cells(row) for row in r.rows if row.day == day)
        table.append(_cells(totals[day]))
    widths = [max([len(h), *(len(line[i]) for line in table)]) for i, h in enumerate(_HEADERS)]

    def fmt(line: list[str] | tuple[str, ...]) -> str:
        return "  ".join(
            c.rjust(w) if i > 1 else c.ljust(w)
            for i, (c, w) in enumerate(zip(line, widths, strict=True))
        ).rstrip()

    header = f"# {r.since} .. {r.until} (UTC) - p50_ms/p95_ms = latency_telegram_ms"
    return "\n".join([header, fmt(_HEADERS), *(fmt(line) for line in table)]) + "\n"
