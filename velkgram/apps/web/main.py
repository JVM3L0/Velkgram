"""Web app factory: `uvicorn --factory velkgram.apps.web.main:create_app`."""

import hashlib
import os
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from starlette.middleware.sessions import SessionMiddleware

import velkgram.alerting.web as alerting_web
import velkgram.channels.web as channels_web
import velkgram.ingestion.web as ingestion_web
import velkgram.offers.web as offers_web
import velkgram.wishlist.web as wishlist_web
from velkgram.alerting.adapters.sqlite.queries import SqliteAlertQueries
from velkgram.alerting.web.router import build_router as build_alerts_router
from velkgram.apps.web.auth import verify_password
from velkgram.apps.web.deps import SESSION_KEY, SESSION_USER, get_conn, require_user
from velkgram.apps.web.nav import nav_items
from velkgram.apps.web.theme import (
    THEME_COOKIE,
    THEME_MAX_AGE,
    THEME_MODES,
    safe_next,
    theme_classes,
)
from velkgram.apps.web.throttle import LoginThrottle
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.channels.web.router import build_router as build_channels_router
from velkgram.ingestion.adapters.sqlite.queries import SqliteIngestionQueries
from velkgram.ingestion.web.router import build_router as build_status_router
from velkgram.offers import sparkline_svg
from velkgram.offers.adapters.sqlite.queries import SqliteOfferQueries
from velkgram.offers.adapters.sqlite.repository import SqliteOfferRepository
from velkgram.offers.web.format import linkify
from velkgram.offers.web.router import WishInfo
from velkgram.offers.web.router import build_router as build_offers_router
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.config import Settings, load_settings
from velkgram.shared.db import bump_version, transaction
from velkgram.shared.ports import Clock
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository
from velkgram.wishlist.web.router import build_router as build_wishlist_router
from velkgram.wishlist.web.view import WishCardStats, format_brl, is_below_alert

_APP_TEMPLATES = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_MODULE_TEMPLATE_DIRS = (
    Path(wishlist_web.__file__).parent / "templates",
    Path(channels_web.__file__).parent / "templates",
    Path(alerting_web.__file__).parent / "templates",
    Path(ingestion_web.__file__).parent / "templates",
    Path(offers_web.__file__).parent / "templates",
)


_RECENT_FAILURES = 10


def _build_templates() -> Jinja2Templates:
    loaders = [FileSystemLoader(d) for d in (_APP_TEMPLATES, *_MODULE_TEMPLATE_DIRS)]
    env = Environment(loader=ChoiceLoader(loaders), autoescape=True)
    env.globals["theme_classes"] = theme_classes
    env.globals["nav_items"] = nav_items
    env.globals["theme_modes"] = THEME_MODES
    # Content hash in the URL: a new stylesheet is never served from a stale browser cache.
    env.globals["css_version"] = hashlib.sha256(
        (_STATIC_DIR / "velkgram.css").read_bytes()
    ).hexdigest()[:12]
    env.globals["js_version"] = hashlib.sha256(
        (_STATIC_DIR / "velkgram.js").read_bytes()
    ).hexdigest()[:12]
    env.filters["brl"] = format_brl
    env.filters["linkify"] = linkify
    env.globals["below_alert"] = is_below_alert
    return Jinja2Templates(env=env)


def _wish_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {w.id: w.name for w in SqliteWishRepository(conn).list_all() if w.id is not None}


def _channel_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {
        c.telegram_id: c.name or c.ref
        for c in SqliteChannelRepository(conn).list_all()
        if c.telegram_id is not None
    }


def _wish_info(conn: sqlite3.Connection, wish_id: int) -> WishInfo | None:
    w = SqliteWishRepository(conn).get(wish_id)
    if w is None or w.id is None:
        return None
    return WishInfo(
        id=w.id,
        name=w.name,
        required_terms=w.required_terms,
        excluded_terms=w.excluded_terms,
        max_price_cents=w.max_price_cents,
        enabled=w.enabled,
    )


def _request_retro(conn: sqlite3.Connection, wish_id: int) -> None:
    """Drop the wish's retro run so the collector reruns it; two sequential transactions."""
    SqliteOfferRepository(conn).delete_retro_run(wish_id)
    with transaction(conn):
        bump_version(conn, "wishlist")


def _wish_card_stats(
    conn: sqlite3.Connection, wish_ids: Sequence[int]
) -> Mapping[int, WishCardStats]:
    return {
        wid: WishCardStats(
            last_price_cents=s.last_cents,
            match_count=s.match_count,
            sparkline_svg=sparkline_svg(s.recent_prices) if s.recent_prices else "",
            previous_price_cents=s.recent_prices[-2] if len(s.recent_prices) > 1 else None,
        )
        for wid, s in SqliteOfferQueries(conn).summaries(wish_ids).items()
    }


def _last_messages(conn: sqlite3.Connection, channel_ids: Sequence[int]) -> Mapping[int, datetime]:
    return SqliteIngestionQueries(conn).last_message_at(channel_ids)


def _wish_deleted(conn: sqlite3.Connection, wish_id: int) -> None:
    SqliteOfferRepository(conn).delete_wish_data(wish_id)


def _active_channels(conn: sqlite3.Connection) -> list[tuple[int, str, int, datetime]]:
    return [
        (c.telegram_id, c.name or c.ref, c.silent_after_hours, c.created_at)
        for c in SqliteChannelRepository(conn).list_enabled_active()
        if c.telegram_id is not None
    ]


def _recent_failures(conn: sqlite3.Connection) -> list[tuple[str, str, datetime]]:
    names = _wish_names(conn)
    return [
        (names.get(a.wish_id, f"#{a.wish_id}"), a.status.value, a.created_at)
        for a in SqliteAlertQueries(conn).recent_failures(_RECENT_FAILURES)
    ]


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or load_settings(os.environ)
    if not settings.web_secret_key:
        raise ValueError("WEB_SECRET_KEY is required to run the web app")
    if not settings.web_password_hash:
        raise ValueError("WEB_PASSWORD_HASH is required to run the web app")
    password_hash = settings.web_password_hash

    app = FastAPI(title="Velkgram", docs_url=None, redoc_url=None, openapi_url=None)
    # same_site="strict" is the CSRF protection for POST forms: the browser never
    # sends the session cookie on cross-site requests.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_secret_key,
        same_site="strict",
        https_only=False,
    )
    templates = _build_templates()
    app.state.settings = settings
    app.state.templates = templates
    clock = clock or SystemClock()
    app.state.clock = clock
    throttle = LoginThrottle(clock)
    app.state.login_throttle = throttle

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Response:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    def login(request: Request, password: str = Form("")) -> Response:
        outcome = throttle.attempt(lambda: verify_password(password_hash, password))
        if outcome == "locked":
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Muitas tentativas. Tente novamente em alguns minutos."},
                status_code=429,
            )
        if outcome == "fail":
            return templates.TemplateResponse(
                request, "login.html", {"error": "Senha incorreta"}, status_code=401
            )
        request.session[SESSION_KEY] = SESSION_USER
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.post("/theme", dependencies=[Depends(require_user)])
    def set_theme(mode: str = Form(""), next: str = Form("/")) -> Response:
        if mode not in THEME_MODES:
            raise HTTPException(status_code=400, detail="Tema inválido")
        response = RedirectResponse(safe_next(next), status_code=303)
        response.set_cookie(
            THEME_COOKIE,
            mode,
            max_age=THEME_MAX_AGE,
            path="/",
            samesite="lax",
            httponly=True,
        )
        return response

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    app.include_router(
        build_wishlist_router(
            get_conn=get_conn,
            templates=templates,
            make_repo=SqliteWishRepository,
            summaries=_wish_card_stats,
            on_deleted=_wish_deleted,
        ),
        prefix="/wishes",
        dependencies=[Depends(require_user)],
    )
    app.include_router(
        build_channels_router(
            get_conn=get_conn,
            templates=templates,
            make_repo=SqliteChannelRepository,
            clock=clock,
            last_messages=_last_messages,
        ),
        prefix="/channels",
        dependencies=[Depends(require_user)],
    )
    app.include_router(
        build_alerts_router(
            get_conn=get_conn,
            templates=templates,
            make_queries=SqliteAlertQueries,
            wish_names=_wish_names,
            channel_names=_channel_names,
        ),
        prefix="/alerts",
        dependencies=[Depends(require_user)],
    )
    app.include_router(
        build_status_router(
            get_conn=get_conn,
            templates=templates,
            make_queries=SqliteIngestionQueries,
            channels=_active_channels,
            recent_failures=_recent_failures,
            clock=clock,
        ),
        prefix="/status",
        dependencies=[Depends(require_user)],
    )
    # Included after the wishlist router so `/wishes/new` wins over `/wishes/{id}`.
    app.include_router(
        build_offers_router(
            get_conn=get_conn,
            templates=templates,
            make_queries=SqliteOfferQueries,
            channel_names=_channel_names,
            get_wish=_wish_info,
            request_retro=_request_retro,
            clock=clock,
            tz=settings.app_timezone,
            retention_days=settings.retention_days,
        ),
        dependencies=[Depends(require_user)],
    )
    return app
