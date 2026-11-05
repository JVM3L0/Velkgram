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


def test_within_over_max_ceiling_is_one_and_a_half_times_the_max() -> None:
    from velkgram.shared.deals import within_over_max

    assert within_over_max(225000, 150000)
    assert not within_over_max(225001, 150000)
    assert not within_over_max(150000, 150000)
