"""Shared web dependencies: per-request DB connection and the login guard."""

import sqlite3
from collections.abc import Iterator

from fastapi import HTTPException, Request

from velkgram.shared.db import connect

SESSION_KEY = "user"
SESSION_USER = "owner"


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def require_user(request: Request) -> None:
    """Router dependency: redirect (303) to /login when there is no session."""
    if request.session.get(SESSION_KEY) != SESSION_USER:
        if request.headers.get("HX-Request") == "true":
            # HTMX would swap a redirected login page into the target; navigate instead.
            raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
        raise HTTPException(status_code=303, headers={"Location": "/login"})
