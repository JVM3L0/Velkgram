"""Offers web routes (feed). Built by `build_router`; the app injects its collaborators."""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from velkgram.offers.domain.coupon import best_tier, coupon_title
from velkgram.offers.domain.insight import PriceVerdict, price_insight
from velkgram.offers.domain.models import (
    CouponTier,
    MatchSource,
    OfferKind,
    ProductStats,
    RetroStatus,
)
from velkgram.offers.ports.queries import (
    CouponFilter,
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
    brl_short,
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
_COUPONS_TYPE = "cupons"  # the retired `tipo` filter value, redirected to the coupons tab
_ACTIVE_HOURS = 24


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
class TierRow:
    """One coupon tier: its condition line and the codes the post ties to it."""

    text: str
    codes: tuple[str, ...]


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
    source: str | None = None
    historic: bool = False
    is_coupon: bool = False
    coupons: tuple[str, ...] = ()
    discount: str = ""
    terms: tuple[str, ...] = ()
    redeem_href: str | None = None
    cart_href: str | None = None
    text: str | None = None
    tier_rows: tuple[TierRow, ...] = ()
    loose_codes: tuple[str, ...] = ()
    anchor: str = ""
    store_key: str | None = None
    store_coupons: int = 0


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


def _cursor_of(card: OfferCard) -> FeedCursor:
    return FeedCursor(card.posted_at, card.channel_id, card.message_id)


_RENDER_MARGIN_SECONDS = 60


def _render_cursor(now: datetime) -> FeedCursor:
    """Sorts after every row posted up to a minute before `now`: an empty list counts what arrives.

    `posted_at` is the Telegram message date (whole seconds, earlier than ingestion), so a bare
    render time would miss an offer posted around it. The list is empty: no double count.
    """
    margin = timedelta(seconds=_RENDER_MARGIN_SECONDS)
    return FeedCursor((now - margin).replace(microsecond=0), SQLITE_MAX_INT, SQLITE_MAX_INT)


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
    price: str | None
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
        price=None if stats.last_cents is None else brl(stats.last_cents),
        verdict=verdict,
        average=None if insight.average_cents is None else brl(insight.average_cents),
    )


def _coupon_terms(card: OfferCard) -> tuple[str, ...]:
    terms: list[str] = []
    if card.coupon_min_cents is not None:
        terms.append(f"em compras a partir de {brl_short(card.coupon_min_cents)}")
    if card.coupon_scope:
        terms.append(f"em {card.coupon_scope}")
    return tuple(terms)


def _headline(card: OfferCard) -> str:
    if len(card.coupon_tiers) > 1:
        best = best_tier(card.coupon_tiers)
        if best is not None:
            return f"Até {best.discount}"
    return card.coupon_discount or "Cupom"


def _tier_text(tier: CouponTier) -> str:
    text = tier.discount
    if tier.min_cents is not None:
        text += f" em {brl_short(tier.min_cents)}"
    if tier.cap_cents is not None:
        text += f" · até {brl_short(tier.cap_cents)} OFF"
    return text


def _tier_rows(card: OfferCard) -> tuple[TierRow, ...]:
    if len(card.coupon_tiers) < 2:
        return ()
    return tuple(TierRow(_tier_text(t), t.codes) for t in card.coupon_tiers)


def _loose_codes(card: OfferCard) -> tuple[str, ...]:
    """Codes of a multi-tier card that no tier line carries (all of them for single tiers)."""
    if len(card.coupon_tiers) < 2:
        return card.coupons
    tied = {c for t in card.coupon_tiers for c in t.codes}
    return tuple(c for c in card.coupons if c not in tied)


def _redirect_to_coupons(
    q: str, stores: list[str] | None, ativos: list[str] | None
) -> RedirectResponse:
    """The old `/?tipo=cupons` filter now lives on the coupons tab; keep stores, search, ativos."""
    params = [("loja", s) for s in (stores or []) if s]
    if q.strip():
        params.append(("q", q.strip()))
    if ativos:
        params.append(("ativos", ativos[-1]))
    return RedirectResponse(
        "/cupons" + ("?" + urlencode(params) if params else ""), status_code=303
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

    def card_view(
        card: OfferCard,
        now: datetime,
        names: dict[int, str],
        store_counts: dict[str, int] | None = None,
    ) -> CardView:
        is_coupon = card.kind is OfferKind.coupon
        return CardView(
            title=coupon_title(card.title) if card.kind is OfferKind.coupon else card.title,
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
            is_coupon=is_coupon,
            store_key=card.store,
            store_coupons=(store_counts or {}).get(card.store or "", 0) if not is_coupon else 0,
            coupons=card.coupons,
            discount=_headline(card),
            terms=_coupon_terms(card) if len(card.coupon_tiers) < 2 else (),
            tier_rows=_tier_rows(card),
            loose_codes=_loose_codes(card),
            anchor=f"cupom-{card.channel_id}-{card.message_id}",
            redeem_href=safe_href(card.redeem_link),
            cart_href=safe_href(card.cart_link),
            text=card.text,
        )

    def wish_or_404(conn: sqlite3.Connection, raw_id: str) -> WishInfo:
        wish_id = _int_or_none(raw_id)
        wish = get_wish(conn, wish_id) if wish_id and 0 < wish_id <= SQLITE_MAX_INT else None
        if wish is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        return wish

    def match_view(
        m: MatchCard, now: datetime, names: dict[int, str], counts: dict[str, int]
    ) -> CardView:
        return replace(
            card_view(m.card, now, names, counts),
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
        counts = queries.coupon_counts(now, _ACTIVE_HOURS)
        context = chart_context(wish, history, range_key)
        context.update(
            {
                "rows": _match_rows(
                    wish.id, history.matches, history.next_cursor, now, names, counts
                ),
                "next_url": _matches_next(wish.id, history.next_cursor),
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
        counts: dict[str, int],
    ) -> list[CardView]:
        return [match_view(m, now, names, counts) for m in matches]

    def _matches_next(wish_id: int, next_cursor: FeedCursor | None) -> str | None:
        if next_cursor is None:
            return None
        return f"/wishes/{wish_id}/matches?" + urlencode({"cursor": _cursor_text(next_cursor)})

    @router.get("/wishes/{wish_id}/matches", response_class=HTMLResponse)
    def product_matches(
        request: Request,
        wish_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        cursor: str = "",
    ) -> Response:
        wish = wish_or_404(conn, wish_id)
        parsed = _parse_cursor(cursor)
        queries = make_queries(conn)
        now = clock.now()
        matches, next_cursor = queries.matches_page(wish.id, parsed, _PAGE_SIZE)
        names = channel_names(conn)
        counts = queries.coupon_counts(now, _ACTIVE_HOURS)
        rows = _match_rows(wish.id, matches, next_cursor, now, names, counts)
        return templates.TemplateResponse(
            request,
            "_product_matches.html",
            {
                "rows": rows,
                "first_page": parsed is None,
                "next_url": _matches_next(wish.id, next_cursor),
            },
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

    def feed_filter(
        names: dict[int, str],
        q: str,
        min_raw: str,
        max_raw: str,
        store: list[str] | None,
        priced: str,
        channel: str,
    ) -> tuple[FeedFilter, str]:
        channel_id = _int_or_none(channel)
        if channel_id not in names:
            channel_id = None
        query = q.strip()
        return (
            FeedFilter(
                q=query or None,
                min_cents=parse_price_cents(min_raw),
                max_cents=parse_price_cents(max_raw),
                stores=tuple(dict.fromkeys(s for s in (store or []) if s)),
                priced_only=priced == "1",
                channel_id=channel_id,
            ),
            query,
        )

    def feed_params(flt: FeedFilter, view: str) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        if flt.q:
            params.append(("q", flt.q))
        if flt.min_cents is not None:
            params.append(("min", format_price(flt.min_cents)))
        if flt.max_cents is not None:
            params.append(("max", format_price(flt.max_cents)))
        params.extend(("store", s) for s in flt.stores)
        if flt.priced_only:
            params.append(("priced", "1"))
        if flt.channel_id is not None:
            params.append(("channel", str(flt.channel_id)))
        params.append(("view", view))
        return params

    def coupon_filter(
        queries: OfferQueries,
        now: datetime,
        q: str,
        loja: list[str] | None,
        ativos: list[str] | None,
    ) -> tuple[CouponFilter, str, bool]:
        stores = queries.coupon_stores()
        query = q.strip()
        selected = tuple(dict.fromkeys(s for s in (loja or []) if s))
        # The switch posts a hidden "0" before its checkbox "1": the last value wins.
        only_active = not ativos or ativos[-1] != "0"
        flt = CouponFilter(
            q=query or None,
            stores=selected,
            since=now - timedelta(hours=_ACTIVE_HOURS) if only_active else None,
            q_stores=tuple(
                s for s in stores if query and query.casefold() in STORE_NAMES.get(s, s).casefold()
            ),
        )
        return flt, query, only_active

    def coupon_params(flt: CouponFilter, query: str, only_active: bool) -> list[tuple[str, str]]:
        params = [("q", query)] if query else []
        params.extend(("loja", s) for s in flt.stores)
        params.append(("ativos", "1" if only_active else "0"))
        return params

    def pill_response(request: Request, count: int, noun: tuple[str, str], url: str) -> Response:
        if count <= 0:
            return Response(status_code=204)
        label = f"1 {noun[0]}" if count == 1 else f"{count} {noun[1]}"
        return templates.TemplateResponse(
            request, "_live_pill.html", {"count": count, "label": label, "reload_url": url}
        )

    @router.get("/novidades", response_class=HTMLResponse)
    def feed_news(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        since: str = "",
        q: str = "",
        min_raw: Annotated[str, Query(alias="min")] = "",
        max_raw: Annotated[str, Query(alias="max")] = "",
        store: Annotated[list[str] | None, Query()] = None,
        priced: str = "",
        channel: str = "",
        view: str = "cards",
    ) -> Response:
        after = _parse_cursor(since)
        if after is None:
            return Response(status_code=204)
        flt, _ = feed_filter(channel_names(conn), q, min_raw, max_raw, store, priced, channel)
        view = view if view in _VIEWS else "cards"
        count = make_queries(conn).count_feed_after(flt, after)
        url = "/?" + urlencode(feed_params(flt, view))
        return pill_response(request, count, ("nova oferta", "novas ofertas"), url)

    @router.get("/cupons/novidades", response_class=HTMLResponse)
    def coupons_news(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        since: str = "",
        q: str = "",
        loja: Annotated[list[str] | None, Query()] = None,
        ativos: Annotated[list[str] | None, Query()] = None,
    ) -> Response:
        after = _parse_cursor(since)
        if after is None:
            return Response(status_code=204)
        queries = make_queries(conn)
        flt, query, only_active = coupon_filter(queries, clock.now(), q, loja, ativos)
        count = queries.count_coupons_after(flt, after)
        url = "/cupons?" + urlencode(coupon_params(flt, query, only_active))
        return pill_response(request, count, ("novo cupom", "novos cupons"), url)

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
        tipo: str = "",
        ativos: Annotated[list[str] | None, Query()] = None,
    ) -> Response:
        if tipo == _COUPONS_TYPE:
            return _redirect_to_coupons(q, store, ativos)
        names = channel_names(conn)
        flt, query = feed_filter(names, q, min_raw, max_raw, store, priced, channel)
        view = view if view in _VIEWS else "cards"
        queries = make_queries(conn)
        page = queries.feed(flt, _parse_cursor(cursor), _PAGE_SIZE)
        now = clock.now()
        counts = queries.coupon_counts(now, _ACTIVE_HOURS)
        rows = [card_view(c, now, names, counts) for c in page.cards]
        next_url: str | None = None
        if rows and page.next_cursor is not None:
            params = feed_params(flt, view)
            params.append(("cursor", _cursor_text(page.next_cursor)))
            next_url = "/?" + urlencode(params)
        # `since` is the newest rendered row. Rows backfilled with an older posted_at are not
        # announced: they simply show up in chronological place on the next load.
        since = _cursor_text(_cursor_of(page.cards[0]) if page.cards else _render_cursor(now))
        live_url = "/novidades?" + urlencode([*feed_params(flt, view), ("since", since)])
        is_fragment = request.headers.get("HX-Request") == "true" and bool(cursor)
        context: dict[str, object] = {"rows": rows, "next_url": next_url}
        if is_fragment:
            return templates.TemplateResponse(request, "_feed_page.html", context)
        context.update(
            {
                "q": query,
                "min_value": min_raw.strip(),
                "max_value": max_raw.strip(),
                "selected_stores": flt.stores,
                "store_options": [(s, STORE_NAMES.get(s, s)) for s in queries.stores_seen()],
                "priced_only": flt.priced_only,
                "channel_id": flt.channel_id,
                "channels": sorted(names.items(), key=lambda kv: kv[1].casefold()),
                "view": view,
                "retention_days": retention_days,
                "live_url": live_url,
            }
        )
        return templates.TemplateResponse(request, "feed.html", context)

    @router.get("/cupons", response_class=HTMLResponse)
    def coupons_page(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        q: str = "",
        loja: Annotated[list[str] | None, Query()] = None,
        ativos: Annotated[list[str] | None, Query()] = None,
        cursor: str = "",
    ) -> Response:
        queries = make_queries(conn)
        now = clock.now()
        stores = queries.coupon_stores()
        flt, query, only_active = coupon_filter(queries, now, q, loja, ativos)
        selected = flt.stores
        page = queries.coupons(flt, _parse_cursor(cursor), _PAGE_SIZE)
        names = channel_names(conn)
        rows = [card_view(c, now, names) for c in page.cards]
        next_url: str | None = None
        if rows and page.next_cursor is not None:
            params = coupon_params(flt, query, only_active)
            params.append(("cursor", _cursor_text(page.next_cursor)))
            next_url = "/cupons?" + urlencode(params)
        # `since` is the newest rendered row. Rows backfilled with an older posted_at are not
        # announced: they simply show up in chronological place on the next load.
        since = _cursor_text(_cursor_of(page.cards[0]) if page.cards else _render_cursor(now))
        live_url = "/cupons/novidades?" + urlencode(
            [*coupon_params(flt, query, only_active), ("since", since)]
        )
        if request.headers.get("HX-Request") == "true" and cursor:
            return templates.TemplateResponse(
                request, "_coupons_page.html", {"rows": rows, "next_url": next_url}
            )
        return templates.TemplateResponse(
            request,
            "cupons.html",
            {
                "rows": rows,
                "next_url": next_url,
                "q": query,
                "selected_stores": selected,
                "only_active": only_active,
                "store_options": [
                    (s, STORE_NAMES.get(s, s))
                    for s in (*stores, *(x for x in selected if x not in stores))
                ],
                "has_filters": bool(query or selected),
                "live_url": live_url,
            },
        )

    return router
