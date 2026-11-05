"""Web app factory: `uvicorn --factory velkgram.apps.web.main:create_app`."""

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from starlette.middleware.sessions import SessionMiddleware

import velkgram.channels.web as channels_web
import velkgram.wishlist.web as wishlist_web
from velkgram.apps.web.auth import verify_password
from velkgram.apps.web.deps import SESSION_KEY, SESSION_USER, get_conn, require_user
from velkgram.apps.web.throttle import LoginThrottle
from velkgram.channels.adapters.sqlite.repository import SqliteChannelRepository
from velkgram.channels.web.router import build_router as build_channels_router
from velkgram.shared.adapters.clock_system import SystemClock
from velkgram.shared.config import Settings, load_settings
from velkgram.shared.ports import Clock
from velkgram.wishlist.adapters.sqlite.repository import SqliteWishRepository
from velkgram.wishlist.web.router import build_router as build_wishlist_router

_APP_TEMPLATES = Path(__file__).parent / "templates"
_MODULE_TEMPLATE_DIRS = (
    Path(wishlist_web.__file__).parent / "templates",
    Path(channels_web.__file__).parent / "templates",
)


def _build_templates() -> Jinja2Templates:
    loaders = [FileSystemLoader(d) for d in (_APP_TEMPLATES, *_MODULE_TEMPLATE_DIRS)]
    env = Environment(loader=ChoiceLoader(loaders), autoescape=True)
    return Jinja2Templates(env=env)


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
        return RedirectResponse("/wishes", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", dependencies=[Depends(require_user)])
    def index() -> Response:
        return RedirectResponse("/wishes", status_code=303)

    app.include_router(
        build_wishlist_router(
            get_conn=get_conn, templates=templates, make_repo=SqliteWishRepository
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
        ),
        prefix="/channels",
        dependencies=[Depends(require_user)],
    )
    return app
