"""Channels web routes. Built by `build_router`; the app injects its collaborators."""

import sqlite3
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from velkgram.channels import ChannelCommands, ChannelRepository, InvalidChannel
from velkgram.shared.ports import Clock

_NOT_FOUND = "Canal não encontrado"


def build_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    templates: Jinja2Templates,
    make_repo: Callable[[sqlite3.Connection], ChannelRepository],
    clock: Clock,
) -> APIRouter:
    router = APIRouter()

    def commands(conn: sqlite3.Connection) -> tuple[ChannelRepository, ChannelCommands]:
        repo = make_repo(conn)
        return repo, ChannelCommands(repo, clock)

    def page(
        request: Request, repo: ChannelRepository, *, error: str | None = None, ref: str = ""
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "channels.html",
            {"channels": repo.list_all(), "error": error, "ref": ref},
            status_code=422 if error else 200,
        )

    @router.get("")
    def list_channels(
        request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        repo, _ = commands(conn)
        return page(request, repo)

    @router.post("")
    def add(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        ref: str = Form(""),
    ) -> Response:
        repo, cmds = commands(conn)
        try:
            cmds.add(ref)
        except InvalidChannel as exc:
            return page(request, repo, error=exc.message_pt, ref=ref)
        return RedirectResponse("/channels", status_code=303)

    @router.post("/{channel_id}/toggle")
    def toggle(
        request: Request, channel_id: int, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
    ) -> Response:
        repo, cmds = commands(conn)
        current = repo.get(channel_id)
        if current is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        cmds.toggle(channel_id, not current.enabled)
        return templates.TemplateResponse(
            request, "_channel_row.html", {"channel": repo.get(channel_id)}
        )

    @router.post("/{channel_id}/delete")
    def delete(channel_id: int, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> Response:
        _, cmds = commands(conn)
        cmds.remove(channel_id)
        return RedirectResponse("/channels", status_code=303)

    return router
