"""Shared web dependencies: per-request DB connection and the login guards."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from velkgram.accounts import Role, User
from velkgram.accounts.adapters.sqlite.repository import SqliteUserRepository
from velkgram.shared.db import connect

SESSION_KEY = "user_id"


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _to_login(request: Request) -> HTTPException:
    if request.headers.get("HX-Request") == "true":
        # HTMX would swap a redirected login page into the target; navigate instead.
        return HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
    return HTTPException(status_code=303, headers={"Location": "/login"})


def require_user(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> User:
    """The logged-in user, loaded on every request; redirect (303) to /login otherwise.

    A user disabled or removed after logging in loses the session on the next request.
    """
    user_id = request.session.get(SESSION_KEY)
    user = SqliteUserRepository(conn).get(user_id) if isinstance(user_id, int) else None
    if user is None or not user.enabled or not user.password_hash:
        request.session.clear()
        raise _to_login(request)
    request.state.user = user
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    """Like `require_user`, but only for administrators (403 for everyone else)."""
    if user.role is not Role.ADMIN:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return user
