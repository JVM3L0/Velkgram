from velkgram.shared.text import normalize_text


def test_normalize() -> None:
    raw = "🔥 SSD Kingston 2TB — Promoção! https://amzn.to/x"
    assert normalize_text(raw) == "ssd kingston 2tb promocao!"


def test_normalize_removes_tme_links() -> None:
    assert normalize_text("Oferta t.me/canal/123 agora") == "oferta agora"
