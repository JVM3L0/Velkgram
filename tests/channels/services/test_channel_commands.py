from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.repositories import InMemoryChannelRepository
from velkgram.channels import ChannelCommands, ChannelStatus, InvalidChannel

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _setup() -> tuple[InMemoryChannelRepository, ChannelCommands]:
    repo = InMemoryChannelRepository()
    return repo, ChannelCommands(repo, FakeClock(NOW))


def test_add_starts_pending() -> None:
    repo, cmds = _setup()
    channel = cmds.add("https://t.me/promotech")
    assert channel.id is not None
    assert channel.ref == "@promotech"
    assert channel.status is ChannelStatus.PENDING
    assert channel.telegram_id is None
    assert channel.name is None
    assert channel.error is None
    assert channel.enabled is True
    assert channel.silent_after_hours == 12
    assert channel.created_at == NOW
    assert repo.get(channel.id) == channel
    assert repo.list_pending() == [channel]


def test_add_invalid_ref_does_not_touch_repo() -> None:
    repo, cmds = _setup()
    with pytest.raises(InvalidChannel):
        cmds.add("-1001234")
    assert repo.list_all() == []
    assert repo.version == 0


def test_duplicate_ref_rejected() -> None:
    repo, cmds = _setup()
    cmds.add("@promotech")
    with pytest.raises(InvalidChannel) as exc:
        cmds.add("https://t.me/promotech", silent_after_hours=6)
    assert exc.value.message_pt == "Canal já cadastrado"
    assert len(repo.list_all()) == 1


def test_activate_sets_id_and_name() -> None:
    repo, cmds = _setup()
    channel = cmds.add("@promotech", silent_after_hours=6)
    assert channel.id is not None
    cmds.activate(channel.id, -1001234, "Promo Tech")
    assert repo.get(channel.id) == replace(
        channel, telegram_id=-1001234, name="Promo Tech", status=ChannelStatus.ACTIVE, error=None
    )
    assert repo.list_pending() == []


def test_fail_sets_error() -> None:
    repo, cmds = _setup()
    channel = cmds.add("@promotech")
    assert channel.id is not None
    cmds.fail(channel.id, "Não é um canal")
    stored = repo.get(channel.id)
    assert stored is not None
    assert stored.status is ChannelStatus.ERROR
    assert stored.error == "Não é um canal"
    assert repo.list_pending() == []


def test_activate_clears_previous_error() -> None:
    repo, cmds = _setup()
    channel = cmds.add("@promotech")
    assert channel.id is not None
    cmds.fail(channel.id, "x")
    cmds.activate(channel.id, -1005, "T")
    stored = repo.get(channel.id)
    assert stored is not None
    assert stored.error is None
    assert stored.status is ChannelStatus.ACTIVE


def test_toggle_and_remove() -> None:
    repo, cmds = _setup()
    channel = cmds.add("@promotech")
    assert channel.id is not None
    cmds.toggle(channel.id, False)
    stored = repo.get(channel.id)
    assert stored is not None
    assert stored.enabled is False
    cmds.remove(channel.id)
    assert repo.get(channel.id) is None


@pytest.mark.parametrize("op", ["toggle", "activate", "fail"])
def test_unknown_channel(op: str) -> None:
    _, cmds = _setup()
    with pytest.raises(InvalidChannel) as exc:
        if op == "toggle":
            cmds.toggle(99, True)
        elif op == "activate":
            cmds.activate(99, -1001, "x")
        else:
            cmds.fail(99, "x")
    assert exc.value.message_pt == "Canal não encontrado"
