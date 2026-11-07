"""Alerts web routes (read-only history). Built by `build_router`."""

import logging
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from velkgram.alerting import Alert, AlertKind, AlertQueries, AlertStatus, format_brl, telegram_link

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
_STATUS_PT = {
    AlertStatus.sent: "enviado",
    AlertStatus.failed: "falhou",
    AlertStatus.pending: "pendente",
    AlertStatus.expired: "expirado",
}


def _coupon_codes(alert: Alert) -> list[str]:
    """Codes live after the third ':' of the `wcc:<wish>:<store>:<codes>` dedup key."""
    if alert.kind is not AlertKind.coupon:
        return []
    for key in alert.dedup_keys:
        if key.startswith("wcc:"):
            parts = key.split(":", 3)
            return [c for c in parts[3].split(",") if c] if len(parts) == 4 else []
    return []


def _parse_page(raw: str | None) -> int:
    try:
        page = int(raw) if raw is not None else 1
    except ValueError:
        return 1
    return page if page >= 1 else 1


def build_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    templates: Jinja2Templates,
    make_queries: Callable[[sqlite3.Connection], AlertQueries],
    wish_names: Callable[[sqlite3.Connection], dict[int, str]],
    channel_names: Callable[[sqlite3.Connection], dict[int, str]],
    product_links: (
        Callable[[sqlite3.Connection, Sequence[tuple[int, int]]], dict[tuple[int, int], str]] | None
    ) = None,
) -> APIRouter:
    router = APIRouter()

    def offer_pair(alert: Alert) -> tuple[int, int]:
        if (
            alert.kind is AlertKind.coupon
            and alert.offer_channel_id is not None
            and alert.offer_message_id is not None
        ):
            return alert.offer_channel_id, alert.offer_message_id
        return alert.channel_id, alert.message_id

    def lookup_links(
        conn: sqlite3.Connection, alerts: Sequence[Alert]
    ) -> dict[tuple[int, int], str]:
        if product_links is None or not alerts:
            return {}
        try:
            return product_links(conn, [offer_pair(a) for a in alerts])
        except Exception:
            logger.exception("product_links_failed")
            return {}

    def row(
        alert: Alert,
        wishes: dict[int, str],
        channels: dict[int, str],
        links: dict[tuple[int, int], str],
    ) -> dict[str, object]:
        return {
            "status": alert.status.value,
            "status_label": _STATUS_PT[alert.status],
            "dedup_keys": len(alert.dedup_keys),
            "price": None if alert.price_cents is None else format_brl(alert.price_cents),
            "latency_telegram_ms": alert.latency_telegram_ms,
            "latency_internal_ms": alert.latency_internal_ms,
            "wish": wishes.get(alert.wish_id, f"#{alert.wish_id}"),
            "channel": channels.get(alert.channel_id, str(alert.channel_id)),
            "is_coupon": alert.kind is AlertKind.coupon,
            "coupon_codes": _coupon_codes(alert),
            "over_max": alert.over_max,
            "product_href": links.get(offer_pair(alert)),
            "link": telegram_link(alert.channel_id, alert.message_id),
            "created_at": alert.created_at,
        }

    @router.get("")
    def list_alerts(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        page: str | None = None,
    ) -> Response:
        number = _parse_page(page)
        fetched = make_queries(conn).history(PAGE_SIZE + 1, (number - 1) * PAGE_SIZE)
        wishes, channels = wish_names(conn), channel_names(conn)
        shown = fetched[:PAGE_SIZE]
        links = lookup_links(conn, shown)
        return templates.TemplateResponse(
            request,
            "alerts.html",
            {
                "rows": [row(a, wishes, channels, links) for a in shown],
                "page": number,
                "has_next": len(fetched) > PAGE_SIZE,
            },
        )

    return router
