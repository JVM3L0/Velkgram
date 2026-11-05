from datetime import UTC, datetime, timedelta

import pytest

from velkgram.ingestion.web.banner import ago, collector_banner

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
STALE = timedelta(seconds=90)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (5, "há 5 s"),
        (59, "há 59 s"),
        (60, "há 1 min"),
        (3599, "há 59 min"),
        (3600, "há 1 h"),
        (86399, "há 23 h"),
        (86400, "há 1 d"),
        (-3, "agora"),
    ],
)
def test_ago_uses_the_largest_unit(seconds: int, text: str) -> None:
    assert ago(timedelta(seconds=seconds)) == text


def _banner(state: str, age_s: int) -> tuple[str, str]:
    b = collector_banner(state, NOW - timedelta(seconds=age_s), NOW, STALE)  # type: ignore[arg-type]
    return b.kind, b.title


def test_banner_is_green_when_the_collector_is_working() -> None:
    assert _banner("connected", 30) == ("ok", "Coletor funcionando")


def test_banner_is_amber_with_minutes_when_the_signal_is_stale() -> None:
    assert _banner("connected", 5 * 60) == ("warning", "Sem sinal há 5 min")
    assert _banner("connected", 91) == ("warning", "Sem sinal há 1 min")


def test_banner_is_red_for_a_fatal_session_even_with_a_fresh_signal() -> None:
    assert _banner("fatal", 2) == ("error", "Sessão inválida")


def test_banner_is_amber_while_reconnecting() -> None:
    assert _banner("reconnecting", 10) == ("warning", "Reconectando ao Telegram")


def test_banner_when_the_collector_never_ran() -> None:
    b = collector_banner(None, None, NOW, STALE)
    assert (b.kind, b.title) == ("error", "Coletor nunca rodou")
