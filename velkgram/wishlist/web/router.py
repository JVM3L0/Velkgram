"""Wishlist web routes. Built by `build_router`; the app injects its collaborators."""

import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from velkgram.wishlist import InvalidWish, Wish, WishCommands, WishRepository

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
    templates: Jinja2Templates,
    make_repo: Callable[[sqlite3.Connection], WishRepository],
) -> APIRouter:
    router = APIRouter()

    def commands(conn: sqlite3.Connection) -> tuple[WishRepository, WishCommands]:
        repo = make_repo(conn)
        return repo, WishCommands(repo)

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
        request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        repo, _ = commands(conn)
        return templates.TemplateResponse(request, "wishes.html", {"wishes": repo.list_all()})

    @router.get("/new")
    def new_form(request: Request) -> Response:
        empty = {"name": "", "required_terms": "", "excluded_terms": "", "max_price": ""}
        return form_response(request, wish_id=None, values=empty)

    @router.post("/new")
    def create(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
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
            cmds.create(name, _lines(required_terms), _lines(excluded_terms), cents)
        except InvalidWish as exc:
            return form_response(request, wish_id=None, values=values, error=exc.message_pt)
        return RedirectResponse("/wishes", status_code=303)

    @router.get("/{wish_id}/edit")
    def edit_form(
        request: Request, wish_id: int, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        repo, _ = commands(conn)
        wish = repo.get(wish_id)
        if wish is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        return form_response(request, wish_id=wish_id, values=wish_values(wish))

    @router.post("/{wish_id}/edit")
    def edit(
        request: Request,
        wish_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        name: str = Form(""),
        required_terms: str = Form(""),
        excluded_terms: str = Form(""),
        max_price: str = Form(""),
    ) -> Response:
        repo, cmds = commands(conn)
        current = repo.get(wish_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
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
        request: Request, wish_id: int, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        repo, cmds = commands(conn)
        current = repo.get(wish_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Desejo não encontrado")
        cmds.toggle(wish_id, not current.enabled)
        updated = repo.get(wish_id)
        return templates.TemplateResponse(request, "_wish_row.html", {"wish": updated})

    @router.post("/{wish_id}/delete")
    def delete(wish_id: int, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> Response:
        _, cmds = commands(conn)
        cmds.delete(wish_id)
        return RedirectResponse("/wishes", status_code=303)

    return router
