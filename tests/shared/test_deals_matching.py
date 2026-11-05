from velkgram.shared.deals import WishView, matches, matches_terms


def _wish(required: tuple[tuple[str, ...], ...], excluded: tuple[str, ...] = ()) -> WishView:
    return WishView(id=1, name="SSD", required=required, excluded=excluded, max_price_cents=60000)


def test_required_alternatives_any_matches() -> None:
    wish = _wish((("ssd", "nvme"), ("2tb", "2 tb")))
    assert matches_terms(wish, "kingston nvme 2 tb barato")
    assert not matches_terms(wish, "kingston nvme 1tb")


def test_word_boundary() -> None:
    wish = _wish((("ssd",),))
    assert not matches_terms(wish, "kit de ssds baratos")
    assert matches_terms(wish, "ssd barato")


def test_excluded_blocks() -> None:
    wish = _wish((("ssd",),), ("usado",))
    assert not matches_terms(wish, "ssd usado")
    assert matches_terms(wish, "ssd novo")


def test_matches_rejects_price_above_max() -> None:
    assert not matches(_wish((("ssd",),)), "ssd 2tb", 60001)


def test_matches_accepts_unknown_price() -> None:
    assert matches(_wish((("ssd",),)), "ssd 2tb", None)
