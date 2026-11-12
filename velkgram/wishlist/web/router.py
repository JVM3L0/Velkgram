"""Wishlist web routes. Built by `build_router`; the app injects its collaborators."""

import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from velkgram.accounts import User
from velkgram.wishlist import InvalidWish, Wish, WishCommands, WishRepository
from velkgram.wishlist.web.view import WishCardStats

_PRICE_RE = re.compile(r"^(\d+|\d{1,3}(\.\d{3})+)(,\d{1,2})?$")
_INVALID_PRICE = "Preço inválido"


def parse_price_cents(raw: str) -> int | None:
    """pt-BR decimal (`599,90`, `1.299,90`, `599`) to cents; None when malformed."""
    text = raw.strip()
    if not _PRICE_RE.match(text):
        return None
    whole, _, frac = text.replace(".", "").partition(",")
    return int(whole) * 100 + int(frac.ljust(2, "0") or "0")


def format_price(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def _lines(raw: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in raw.splitlines() if line.strip())


def build_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    current_user: Callable[..., User],
    templates: Jinja2Templates,
    make_repo: Callable[[sqlite3.Connection], WishRepository],
    summaries: Callable[
        [sqlite3.Connection, Sequence[int]], Mapping[int, WishCardStats]
    ] = lambda _c, _ids: {},
    on_deleted: Callable[[sqlite3.Connection, int], None] = lambda _c, _id: None,
) -> APIRouter:
    router = APIRouter()

    def card_context(conn: sqlite3.Connection, wishes: Sequence[Wish]) -> list[dict[str, object]]:
        ids = [w.id for w in wishes if w.id is not None]
        stats = summaries(conn, ids)
        return [{"wish": w, "stats": stats.get(w.id) if w.id is not None else None} for w in wishes]

    def commands(conn: sqlite3.Connection) -> tuple[WishRepository, WishCommands]:
        repo = make_repo(conn)
        return repo, WishCommands(repo)

    def owned(repo: WishRepository, wish_id: int, user: User) -> Wish:
        """The user's own wish; someone else's looks exactly like one that does not exist."""
        wish = repo.get(wish_id)
        if wish is None or wish.user_id != user.id:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        return wish

    def form_response(
        request: Request,
        *,
        wish_id: int | None,
        values: dict[str, str],
        error: str | None = None,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "wish_form.html",
            {"wish_id": wish_id, "values": values, "error": error},
            status_code=422 if error else 200,
        )

    def wish_values(w: Wish) -> dict[str, str]:
        return {
            "name": w.name,
            "required_terms": "\n".join(w.required_terms),
            "excluded_terms": "\n".join(w.excluded_terms),
            "max_price": format_price(w.max_price_cents),
        }

    @router.get("")
    def list_wishes(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
    ) -> Response:
        repo, _ = commands(conn)
        return templates.TemplateResponse(
            request, "wishes.html", {"cards": card_context(conn, repo.list_for_user(user.id or 0))}
        )

    @router.get("/new")
    def new_form(
        request: Request,
        name: str = "",
        required: Annotated[list[str] | None, Query()] = None,
        excluded: Annotated[list[str] | None, Query()] = None,
        max_price: str = "",
    ) -> Response:
        """Pre-fills the form from the query string; nothing is saved until the POST."""
        values = {
            "name": name.strip(),
            "required_terms": "\n".join(t.strip() for t in required or () if t.strip()),
            "excluded_terms": "\n".join(t.strip() for t in excluded or () if t.strip()),
            "max_price": max_price.strip() if parse_price_cents(max_price) is not None else "",
        }
        return form_response(request, wish_id=None, values=values)

    @router.post("/new")
    def create(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
        name: str = Form(""),
        required_terms: str = Form(""),
        excluded_terms: str = Form(""),
        max_price: str = Form(""),
    ) -> Response:
        values = {
            "name": name,
            "required_terms": required_terms,
            "excluded_terms": excluded_terms,
            "max_price": max_price,
        }
        cents = parse_price_cents(max_price)
        if cents is None:
            return form_response(request, wish_id=None, values=values, error=_INVALID_PRICE)
        _, cmds = commands(conn)
        try:
            cmds.create(
                name, _lines(required_terms), _lines(excluded_terms), cents, user_id=user.id or 0
            )
        except InvalidWish as exc:
            return form_response(request, wish_id=None, values=values, error=exc.message_pt)
        return RedirectResponse("/wishes", status_code=303)

    @router.get("/{wish_id}/edit")
    def edit_form(
        request: Request,
        wish_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
    ) -> Response:
        repo, _ = commands(conn)
        wish = owned(repo, wish_id, user)
        return form_response(request, wish_id=wish_id, values=wish_values(wish))

    @router.post("/{wish_id}/edit")
    def edit(
        request: Request,
        wish_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
        name: str = Form(""),
        required_terms: str = Form(""),
        excluded_terms: str = Form(""),
        max_price: str = Form(""),
    ) -> Response:
        repo, cmds = commands(conn)
        current = owned(repo, wish_id, user)
        values = {
            "name": name,
            "required_terms": required_terms,
            "excluded_terms": excluded_terms,
            "max_price": max_price,
        }
        cents = parse_price_cents(max_price)
        if cents is None:
            return form_response(request, wish_id=wish_id, values=values, error=_INVALID_PRICE)
        updated = replace(
            current,
            name=name.strip(),
            required_terms=_lines(required_terms),
            excluded_terms=_lines(excluded_terms),
            max_price_cents=cents,
        )
        try:
            cmds.update(updated)
        except InvalidWish as exc:
            return form_response(request, wish_id=wish_id, values=values, error=exc.message_pt)
        return RedirectResponse("/wishes", status_code=303)

    @router.post("/{wish_id}/toggle")
    def toggle(
        request: Request,
        wish_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
    ) -> Response:
        repo, cmds = commands(conn)
        current = owned(repo, wish_id, user)
        cmds.toggle(wish_id, not current.enabled)
        updated = repo.get(wish_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        (card,) = card_context(conn, [updated])
        return templates.TemplateResponse(request, "_wish_row.html", card)

    @router.post("/{wish_id}/delete")
    def delete(
        wish_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
    ) -> Response:
        repo, cmds = commands(conn)
        owned(repo, wish_id, user)
        cmds.delete(wish_id)
        on_deleted(conn, wish_id)
        return RedirectResponse("/wishes", status_code=303)

    return router
