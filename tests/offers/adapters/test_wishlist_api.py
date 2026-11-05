from tests.fakes.repositories import InMemoryWishRepository
from velkgram.offers.adapters.wishlist_api import WishlistApiWishReader
from velkgram.wishlist import Wish


def _reader() -> tuple[WishlistApiWishReader, int, int]:
    repo = InMemoryWishRepository()
    on = repo.add(Wish(None, "SSD", ("ssd|nvme", "2tb"), ("usado",), 30000, True))
    off = repo.add(Wish(None, "RAM", ("ddr5",), (), 20000, False))
    assert on.id is not None and off.id is not None
    return WishlistApiWishReader(repo), on.id, off.id


def test_enabled_returns_only_enabled_views() -> None:
    reader, on, _ = _reader()
    views = reader.enabled()
    assert [v.id for v in views] == [on]
    assert views[0].required == (("ssd", "nvme"), ("2tb",))
    assert views[0].excluded == ("usado",)
    assert views[0].max_price_cents == 30000


def test_all_includes_disabled() -> None:
    reader, on, off = _reader()
    assert [v.id for v in reader.all()] == [on, off]
