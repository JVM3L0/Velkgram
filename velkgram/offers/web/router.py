"""Offers web routes (feed). Built by `build_router`; the app injects its collaborators."""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from velkgram.offers.ports.queries import FeedCursor, FeedFilter, OfferCard, OfferQueries
from velkgram.offers.web.format import (
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
    next_url: str | None = None


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
    return FeedCursor(posted_at, channel_id, message_id)


def _cursor_text(c: FeedCursor) -> str:
    return f"{c.posted_at.isoformat()}|{c.channel_id}|{c.message_id}"


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
    # `get_wish` and `request_retro` serve the product pages added in the next task.
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
        )

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
