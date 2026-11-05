"""The collector health banner and relative times for the status page (pure)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from velkgram.ingestion.domain.models import ConnectionState
from velkgram.shared.timeago import ago

BannerKind = Literal["ok", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Banner:
    kind: BannerKind
    icon: str
    title: str
    detail: str


def collector_banner(
    state: ConnectionState | None,
    last_seen: datetime | None,
    now: datetime,
    stale_after: timedelta,
) -> Banner:
    if state is None or last_seen is None:
        return Banner(
            "error",
            "error",
            "Coletor nunca rodou",
            "Inicie o coletor para começar a receber ofertas.",
        )
    age = now - last_seen
    if state == "fatal":
        return Banner(
            "error",
            "error",
            "Sessão inválida",
            "Gere uma nova sessão do Telegram e reinicie o coletor para voltar a receber ofertas.",
        )
    if age > stale_after:
        return Banner(
            "warning",
            "warning",
            f"Sem sinal {ago(age)}",
            f"O coletor não envia sinal há mais de {int(stale_after.total_seconds())} segundos. "
            "Confira se ele está rodando.",
        )
    if state == "reconnecting":
        return Banner(
            "warning",
            "sync_problem",
            "Reconectando ao Telegram",
            "O coletor perdeu a conexão e está tentando voltar sozinho.",
        )
    return Banner("ok", "check_circle", "Coletor funcionando", f"Último sinal {ago(age)}.")
