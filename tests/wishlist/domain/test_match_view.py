from velkgram.shared.deals import WishView
from velkgram.wishlist import Wish, match_view


def test_match_view_normalizes_groups_and_drops_empty() -> None:
    wish = Wish(1, "SSD", ("SSD", "2TB|2 tb", "|"), ("Usado",), 60000, True)
    assert match_view(wish) == WishView(1, "SSD", (("ssd",), ("2tb", "2 tb")), ("usado",), 60000)


def test_match_view_is_none_without_id() -> None:
    assert match_view(Wish(None, "SSD", ("ssd",), (), 60000, True)) is None
