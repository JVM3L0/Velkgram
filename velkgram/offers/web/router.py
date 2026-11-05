"""Offers web routes (feed). Built by `build_router`; the app injects its collaborators."""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from velkgram.offers.domain.insight import PriceVerdict, price_insight
from velkgram.offers.domain.models import MatchSource, ProductStats, RetroStatus
from velkgram.offers.ports.queries import (
    FeedCursor,
    FeedFilter,
    MatchCard,
    OfferCard,
    OfferQueries,
    PricePoint,
    ProductHistory,
)
from velkgram.offers.web.chart import price_chart_responsive
from velkgram.offers.web.format import (
    SQLITE_MAX_INT,
    STORE_NAMES,
    brl,
    follow_url,
    format_price,
    parse_price_cents,
    relative_time,
    safe_href,
)
from velkgram.shared.ports import Clock

_VIEWS = ("cards", "list")
_PAGE_SIZE = 30
_RANGES: dict[str, int | None] = {"30": 30, "90": 90, "all": None}
_DEFAULT_RANGE = "90"
_RANGE_LABELS = (("30", "30 dias"), ("90", "90 dias"), ("all", "Tudo"))
_SOURCE_LABELS = {MatchSource.live: "ao vivo", MatchSource.retro: "histórico"}
_DASH = "—"


@dataclass(frozen=True, slots=True)
class WishInfo:
    """The wish fields the offers pages need, injected so offers never imports wishlist."""

    id: int
    name: str
    required_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    max_price_cents: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class CardView:
    """One feed card, preformatted for the template."""

    title: str
    price: str
    priced: bool
    store: str | None
    channel: str | None
    posted_iso: str
    posted_text: str
    href: str | None
    follow: str
    sold_out: bool
    deleted: bool
    reposts: int
    comparable: bool = True
    next_url: str | None = None
    source: str | None = None
    historic: bool = False


def _parse_cursor(raw: str) -> FeedCursor | None:
    parts = raw.split("|")
    if len(parts) != 3:
        return None
    try:
        posted_at = datetime.fromisoformat(parts[0])
        channel_id, message_id = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if posted_at.tzinfo is None:
        return None
    if not all(abs(v) <= SQLITE_MAX_INT for v in (channel_id, message_id)):
        return None
    return FeedCursor(posted_at, channel_id, message_id)


def _cursor_text(c: FeedCursor) -> str:
    return f"{c.posted_at.isoformat()}|{c.channel_id}|{c.message_id}"


@dataclass(frozen=True, slots=True)
class StatsView:
    """The secondary product stats, preformatted ("—" when there is nothing to show)."""

    lowest: str
    count: str


@dataclass(frozen=True, slots=True)
class InsightView:
    """The price banner: current price against the average of the selected range."""

    kind: str
    icon: str
    price: str
    verdict: str
    average: str | None


_VERDICTS = {
    PriceVerdict.below: ("below", "trending_down", "abaixo da média"),
    PriceVerdict.average: ("average", "trending_flat", "na média"),
    PriceVerdict.above: ("above", "trending_up", "acima da média"),
    PriceVerdict.unknown: ("unknown", "info", "Poucos dados para comparar"),
}


def _stats_view(stats: ProductStats) -> StatsView:
    return StatsView(
        lowest=_DASH if stats.lowest_cents is None else brl(stats.lowest_cents),
        count=str(stats.match_count) if stats.match_count else _DASH,
    )


def _insight_view(stats: ProductStats, points: tuple[PricePoint, ...]) -> InsightView:
    insight = price_insight(stats.last_cents, [p.price_cents for p in points])
    kind, icon, verdict = _VERDICTS[insight.verdict]
    return InsightView(
        kind=kind,
        icon=icon,
        price=_DASH if stats.last_cents is None else brl(stats.last_cents),
        verdict=verdict,
        average=None if insight.average_cents is None else brl(insight.average_cents),
    )


def _int_or_none(raw: str) -> int | None:
    try:
        return int(raw)
    except ValueError:
        return None


def build_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    templates: Jinja2Templates,
    make_queries: Callable[[sqlite3.Connection], OfferQueries],
    channel_names: Callable[[sqlite3.Connection], dict[int, str]],
    get_wish: Callable[[sqlite3.Connection, int], WishInfo | None],
    request_retro: Callable[[sqlite3.Connection, int], None],
    clock: Clock,
    tz: ZoneInfo,
    retention_days: int,
) -> APIRouter:
    router = APIRouter()

    def card_view(card: OfferCard, now: datetime, names: dict[int, str]) -> CardView:
        return CardView(
            title=card.title,
            price=brl(card.price_cents),
            priced=card.price_cents is not None,
            store=STORE_NAMES.get(card.store, card.store) if card.store else None,
            channel=names.get(card.channel_id),
            posted_iso=card.posted_at.isoformat(),
            posted_text=relative_time(card.posted_at, now, tz),
            href=safe_href(card.main_link),
            follow=follow_url(card),
            sold_out=card.sold_out,
            deleted=card.deleted,
            reposts=card.repost_count,
            comparable=card.comparable,
        )

    def wish_or_404(conn: sqlite3.Connection, raw_id: str) -> WishInfo:
        wish_id = _int_or_none(raw_id)
        wish = get_wish(conn, wish_id) if wish_id and 0 < wish_id <= SQLITE_MAX_INT else None
        if wish is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        return wish

    def match_view(m: MatchCard, now: datetime, names: dict[int, str]) -> CardView:
        return replace(
            card_view(m.card, now, names),
            source=_SOURCE_LABELS[m.source],
            historic=m.source is MatchSource.retro,
        )

    def retro_response(
        request: Request, wish_id: int, status: RetroStatus | None, *, poll: bool
    ) -> Response:
        response = templates.TemplateResponse(
            request, "_retro_status.html", {"wish_id": wish_id, "status": status}
        )
        if poll and status is RetroStatus.done:
            response.headers["HX-Trigger"] = "retro-done"
        return response

    def chart_context(wish: WishInfo, history: ProductHistory, range_key: str) -> dict[str, object]:
        return {
            "wish": wish,
            "stats": _stats_view(history.stats),
            "insight": _insight_view(history.stats, history.points),
            "chart_svg": Markup(price_chart_responsive(history.points, wish.max_price_cents)),
            "range_key": range_key,
            "ranges": _RANGE_LABELS,
        }

    @router.get("/wishes/{wish_id}", response_class=HTMLResponse)
    def product(
        request: Request,
        wish_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        range_raw: Annotated[str, Query(alias="range")] = _DEFAULT_RANGE,
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        range_key = range_raw if range_raw in _RANGES else _DEFAULT_RANGE
        queries = make_queries(conn)
        now = clock.now()
        history = queries.product(wish.id, now, _RANGES[range_key], None, _PAGE_SIZE)
        names = channel_names(conn)
        context = chart_context(wish, history, range_key)
        context.update(
            {
                "rows": _match_rows(wish.id, history.matches, history.next_cursor, now, names),
                "first_page": True,
                "status": history.retro.status if history.retro else None,
                "wish_id": wish.id,
                "max_price": brl(wish.max_price_cents),
            }
        )
        return templates.TemplateResponse(request, "product.html", context)

    def _match_rows(
        wish_id: int,
        matches: tuple[MatchCard, ...],
        next_cursor: FeedCursor | None,
        now: datetime,
        names: dict[int, str],
    ) -> list[CardView]:
        rows = [match_view(m, now, names) for m in matches]
        if rows and next_cursor is not None:
            url = f"/wishes/{wish_id}/matches?" + urlencode({"cursor": _cursor_text(next_cursor)})
            rows[-1] = replace(rows[-1], next_url=url)
        return rows

    @router.get("/wishes/{wish_id}/matches", response_class=HTMLResponse)
    def product_matches(
        request: Request,
        wish_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        cursor: str = "",
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        parsed = _parse_cursor(cursor)
        history = make_queries(conn).product(wish.id, clock.now(), None, parsed, _PAGE_SIZE)
        now = clock.now()
        names = channel_names(conn)
        rows = _match_rows(wish.id, history.matches, history.next_cursor, now, names)
        return templates.TemplateResponse(
            request, "_product_matches.html", {"rows": rows, "first_page": parsed is None}
        )

    @router.get("/wishes/{wish_id}/chart", response_class=HTMLResponse)
    def product_chart(
        request: Request,
        wish_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        range_raw: Annotated[str, Query(alias="range")] = _DEFAULT_RANGE,
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        range_key = range_raw if range_raw in _RANGES else _DEFAULT_RANGE
        history = make_queries(conn).product(wish.id, clock.now(), _RANGES[range_key], None, 1)
        context = chart_context(wish, history, range_key)
        return templates.TemplateResponse(request, "_product_chart.html", context)

    @router.get("/wishes/{wish_id}/history", response_class=HTMLResponse)
    def product_history(
        request: Request, wish_id: str, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        run = make_queries(conn).product(wish.id, clock.now(), None, None, 1).retro
        poll = request.headers.get("HX-Request") == "true"
        return retro_response(request, wish.id, run.status if run else None, poll=poll)

    @router.post("/wishes/{wish_id}/history/retry", response_class=HTMLResponse)
    def product_retry(
        request: Request, wish_id: str, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        request_retro(conn, wish.id)
        return retro_response(request, wish.id, RetroStatus.running, poll=False)

    @router.get("/", response_class=HTMLResponse)
    def feed(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        q: str = "",
        min_raw: Annotated[str, Query(alias="min")] = "",
        max_raw: Annotated[str, Query(alias="max")] = "",
        store: Annotated[list[str] | None, Query()] = None,
        priced: str = "",
        channel: str = "",
        cursor: str = "",
        view: str = "cards",
    ) -> Response:
        names = channel_names(conn)
        channel_id = _int_or_none(channel)
        if channel_id not in names:
            channel_id = None
        stores = tuple(dict.fromkeys(s for s in (store or []) if s))
        query = q.strip()
        min_cents = parse_price_cents(min_raw)
        max_cents = parse_price_cents(max_raw)
        flt = FeedFilter(
            q=query or None,
            min_cents=min_cents,
            max_cents=max_cents,
            stores=stores,
            priced_only=priced == "1",
            channel_id=channel_id,
        )
        view = view if view in _VIEWS else "cards"
        queries = make_queries(conn)
        page = queries.feed(flt, _parse_cursor(cursor), _PAGE_SIZE)
        now = clock.now()
        rows = [card_view(c, now, names) for c in page.cards]
        if rows and page.next_cursor is not None:
            params: list[tuple[str, str]] = []
            if flt.q:
                params.append(("q", flt.q))
            if min_cents is not None:
                params.append(("min", format_price(min_cents)))
            if max_cents is not None:
                params.append(("max", format_price(max_cents)))
            params.extend(("store", s) for s in stores)
            if flt.priced_only:
                params.append(("priced", "1"))
            if channel_id is not None:
                params.append(("channel", str(channel_id)))
            params.append(("view", view))
            params.append(("cursor", _cursor_text(page.next_cursor)))
            rows[-1] = replace(rows[-1], next_url="/?" + urlencode(params))
        is_fragment = request.headers.get("HX-Request") == "true" and bool(cursor)
        context: dict[str, object] = {"rows": rows}
        if is_fragment:
            return templates.TemplateResponse(request, "_feed_page.html", context)
        context.update(
            {
                "q": query,
                "min_value": min_raw.strip(),
                "max_value": max_raw.strip(),
                "selected_stores": stores,
                "store_options": [(s, STORE_NAMES.get(s, s)) for s in queries.stores_seen()],
                "priced_only": flt.priced_only,
                "channel_id": channel_id,
                "channels": sorted(names.items(), key=lambda kv: kv[1].casefold()),
                "view": view,
                "retention_days": retention_days,
            }
        )
        return templates.TemplateResponse(request, "feed.html", context)

    return router
