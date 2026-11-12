from velkgram.wishlist import Wish, match_view


def test_match_view_carries_the_owner() -> None:
    view = match_view(Wish(5, "GPU", ("rtx",), (), 100000, True, user_id=3))
    assert view is not None and (view.id, view.user_id) == (5, 3)


def test_match_view_defaults_to_the_admin() -> None:
    view = match_view(Wish(5, "GPU", ("rtx",), (), 100000, True))
    assert view is not None and view.user_id == 1
