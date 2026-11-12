"""Account web routes: a user's profile and the admin's user management."""

import secrets
import sqlite3
from collections.abc import Awaitable, Callable, Iterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from velkgram.accounts.domain.models import InvalidUser, Role, User, validate_password
from velkgram.accounts.ports.repository import UserRepository
from velkgram.accounts.services.commands import UserCommands

_NOTICES = {
    "telegram": "Id do Telegram salvo",
    "senha": "Senha alterada",
    "teste": "Alerta de teste enviado",
}
_NEEDS_START = frozenset({"UserIsBlockedError", "PeerIdInvalidError", "ValueError", "needs_start"})
_BAD_CHAT = "Informe o seu id do Telegram (só números, veja @userinfobot)"
_MAX_CHAT_ID = 2**63 - 1
_INVALID = object()


def parse_chat_id(raw: str) -> object:
    """Blank clears the id, digits set it, anything else is `_INVALID`."""
    text = raw.strip()
    if not text:
        return None
    if not text.isascii() or not text.isdigit():
        return _INVALID
    value = int(text)
    return value if 0 < value <= _MAX_CHAT_ID else _INVALID


def _test_failure(code: str) -> str:
    if code in _NEEDS_START:
        return "Abra o bot no Telegram e toque em Iniciar, depois tente de novo"
    if code == "disabled":
        return "O envio pelo Telegram não está ativado neste servidor"
    return f"Falha ao enviar o alerta de teste ({code})"


def build_profile_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    current_user: Callable[..., User],
    templates: Jinja2Templates,
    make_commands: Callable[[sqlite3.Connection], UserCommands],
    send_test: Callable[[int], Awaitable[str | None]],
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request, user: User, *, error: str | None = None, ok: str | None = None
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "profile.html",
            {"me": user, "error": error, "notice": _NOTICES.get(ok or "")},
            status_code=422 if error else 200,
        )

    @router.get("")
    def show(
        request: Request, user: Annotated[User, Depends(current_user)], ok: str = ""
    ) -> Response:
        return page(request, user, ok=ok)

    @router.post("/telegram")
    def save_chat(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
        chat_id: str = Form(""),
    ) -> Response:
        chat = parse_chat_id(chat_id)
        if chat is _INVALID:
            return page(request, user, error=_BAD_CHAT)
        assert chat is None or isinstance(chat, int)
        make_commands(conn).set_chat_id(user.id or 0, chat)
        return RedirectResponse("/perfil?ok=telegram", status_code=303)

    @router.post("/senha")
    def change_password(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        user: Annotated[User, Depends(current_user)],
        current: str = Form(""),
        new: str = Form(""),
        repeat: str = Form(""),
    ) -> Response:
        commands = make_commands(conn)
        if commands.authenticate(user.username, current) is None:
            return page(request, user, error="Senha atual incorreta")
        if new != repeat:
            return page(request, user, error="As senhas novas não conferem")
        try:
            commands.set_password(user.id or 0, new)
        except InvalidUser as exc:
            return page(request, user, error=exc.message_pt)
        return RedirectResponse("/perfil?ok=senha", status_code=303)

    @router.post("/teste")
    async def test_alert(
        request: Request, user: Annotated[User, Depends(current_user)]
    ) -> Response:
        if user.telegram_chat_id is None:
            return page(request, user, error=_BAD_CHAT)
        failure = await send_test(user.telegram_chat_id)
        if failure is not None:
            response = page(request, user, error=_test_failure(failure))
            response.status_code = 502
            return response
        return RedirectResponse("/perfil?ok=teste", status_code=303)

    return router


def build_users_router(
    *,
    get_conn: Callable[..., Iterator[sqlite3.Connection]],
    admin_user: Callable[..., User],
    templates: Jinja2Templates,
    make_commands: Callable[[sqlite3.Connection], UserCommands],
    make_repo: Callable[[sqlite3.Connection], UserRepository],
    send_test_many: Callable[[Sequence[int]], Awaitable[dict[int, str | None]]],
) -> APIRouter:
    router = APIRouter()

    def page(
        request: Request,
        conn: sqlite3.Connection,
        *,
        error: str | None = None,
        generated: tuple[str, str] | None = None,
        test_results: list[tuple[str, bool, str]] | None = None,
    ) -> Response:
        return templates.TemplateResponse(
            request,
            "users.html",
            {
                "users": make_repo(conn).list_all(),
                "error": error,
                "generated": generated,
                "test_results": test_results,
            },
            status_code=422 if error else 200,
        )

    def existing(repo: UserRepository, user_id: int) -> User:
        user = repo.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return user

    @router.get("")
    def list_users(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
    ) -> Response:
        return page(request, conn)

    @router.post("/novo")
    def create(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
        username: str = Form(""),
        role: str = Form("user"),
    ) -> Response:
        if role not in {r.value for r in Role}:
            return page(request, conn, error="Perfil inválido")
        password = secrets.token_urlsafe(9)  # shown once; only its hash is stored
        try:
            created = make_commands(conn).create(username, password, Role(role))
        except InvalidUser as exc:
            return page(request, conn, error=exc.message_pt)
        return page(request, conn, generated=(created.username, password))

    @router.post("/teste")
    async def broadcast_test(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
    ) -> Response:
        """A test alert to every enabled user that has a Telegram id; say who was left out."""
        active = [u for u in make_repo(conn).list_all() if u.enabled]
        chats = [u.telegram_chat_id for u in active if u.telegram_chat_id is not None]
        if not chats:
            return page(request, conn, error="Nenhum usuário ativo tem o id do Telegram salvo")
        results = await send_test_many(chats)
        rows: list[tuple[str, bool, str]] = []
        for u in active:
            if u.telegram_chat_id is None:
                rows.append((u.username, False, "sem id do Telegram"))
                continue
            failure = results.get(u.telegram_chat_id, "sem resposta")
            rows.append(
                (u.username, True, "enviado")
                if failure is None
                else (u.username, False, _test_failure(failure))
            )
        return page(request, conn, test_results=rows)

    @router.post("/{user_id}/senha")
    def reset_password(
        request: Request,
        user_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
    ) -> Response:
        user = existing(make_repo(conn), user_id)
        password = secrets.token_urlsafe(9)
        validate_password(password)
        make_commands(conn).set_password(user_id, password)
        return page(request, conn, generated=(user.username, password))

    @router.post("/{user_id}/ativo")
    def set_enabled(
        request: Request,
        user_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
        enabled: str = Form("1"),
    ) -> Response:
        existing(make_repo(conn), user_id)
        try:
            make_commands(conn).set_enabled(user_id, enabled == "1")
        except InvalidUser as exc:
            return page(request, conn, error=exc.message_pt)
        return RedirectResponse("/usuarios", status_code=303)

    @router.post("/{user_id}/telegram")
    def set_chat(
        request: Request,
        user_id: int,
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        _admin: Annotated[User, Depends(admin_user)],
        chat_id: str = Form(""),
    ) -> Response:
        existing(make_repo(conn), user_id)
        chat = parse_chat_id(chat_id)
        if chat is _INVALID:
            return page(request, conn, error=_BAD_CHAT)
        assert chat is None or isinstance(chat, int)
        make_commands(conn).set_chat_id(user_id, chat)
        return RedirectResponse("/usuarios", status_code=303)

    return router
