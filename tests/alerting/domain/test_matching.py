from velkgram.alerting.domain.matching import matches_terms
from velkgram.alerting.domain.models import WishView


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
