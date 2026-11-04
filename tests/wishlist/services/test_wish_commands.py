import pytest

from tests.fakes.repositories import InMemoryWishRepository
from velkgram.wishlist import InvalidWish, WishCommands


def test_create_validates_and_persists() -> None:
    repo = InMemoryWishRepository()
    wish = WishCommands(repo).create("SSD", ("ssd|nvme",), (), 30000)
    assert wish.id is not None
    assert repo.get(wish.id) == wish
    assert repo.version == 1


def test_create_invalid_does_not_touch_repo() -> None:
    repo = InMemoryWishRepository()
    with pytest.raises(InvalidWish):
        WishCommands(repo).create("SSD", (), (), 30000)
    assert repo.list_all() == []
    assert repo.version == 0


def test_toggle_and_delete() -> None:
    repo = InMemoryWishRepository()
    cmds = WishCommands(repo)
    wish = cmds.create("SSD", ("ssd",), (), 30000)
    assert wish.id is not None
    cmds.toggle(wish.id, False)
    assert repo.list_enabled() == []
    cmds.delete(wish.id)
    assert repo.get(wish.id) is None


def test_update_validates() -> None:
    repo = InMemoryWishRepository()
    cmds = WishCommands(repo)
    wish = cmds.create("SSD", ("ssd",), (), 30000)
    with pytest.raises(InvalidWish):
        cmds.update(type(wish)(wish.id, "SSD", ("ssd",), (), 0, True))
    assert repo.get(wish.id or 0) == wish  # type: ignore[arg-type]


def test_toggle_unknown_wish() -> None:
    with pytest.raises(InvalidWish):
        WishCommands(InMemoryWishRepository()).toggle(99, True)
