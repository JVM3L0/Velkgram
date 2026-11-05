"""Status web route (collector heartbeat, channel activity, recent failures)."""

import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from velkgram.ingestion import ConnectionState, IngestionQueries
from velkgram.ingestion.web.banner import ago, collector_banner
from velkgram.shared.ports import Clock

HEARTBEAT_STALE_AFTER = timedelta(seconds=90)
_STATE_PT: dict[ConnectionState, str] = {
    "connected": "conectado",
    "reconnecting": "reconectando",
    "fatal": "erro fatal",
}


def build_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    templates: Jinja2Templates,
    make_queries: Callable[[sqlite3.Connection], IngestionQueries],
    channels: Callable[[sqlite3.Connection], list[tuple[int, str, int, datetime]]],
    recent_failures: Callable[[sqlite3.Connection], list[tuple[str, str, datetime]]],
    clock: Clock,
) -> APIRouter:
    router = APIRouter()

    @router.get("")
    def status(
        request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        now = clock.now()
        queries = make_queries(conn)
        beat = queries.heartbeat()
        heartbeat = None
        banner = collector_banner(
            beat.connection_state if beat else None,
            beat.last_seen if beat else None,
            now,
            HEARTBEAT_STALE_AFTER,
        )
        if beat is not None:
            heartbeat = {
                "last_seen_ago": ago(now - beat.last_seen),
                "state": _STATE_PT[beat.connection_state],
                "reason": beat.fatal_reason,
                "last_seen": beat.last_seen,
                "stale": now - beat.last_seen > HEARTBEAT_STALE_AFTER,
                "messages_seen": beat.messages_seen,
                "alerts_sent": beat.alerts_sent,
            }
        active = channels(conn)
        last = queries.last_message_at([telegram_id for telegram_id, _, _, _ in active])
        rows = []
        for telegram_id, name, silent_after_hours, created_at in active:
            last_message = last.get(telegram_id)
            reference = last_message or created_at
            rows.append(
                {
                    "name": name,
                    "last_message_at": last_message,
                    "last_message_ago": ago(now - last_message) if last_message else None,
                    "silent": now - reference > timedelta(hours=silent_after_hours),
                    "silent_after_hours": silent_after_hours,
                }
            )
        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "banner": banner,
                "heartbeat": heartbeat,
                "channels": rows,
                "failures": recent_failures(conn),
                "stale_after_seconds": int(HEARTBEAT_STALE_AFTER.total_seconds()),
            },
        )

    return router
