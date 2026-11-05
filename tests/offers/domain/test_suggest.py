from velkgram.offers.domain.suggest import suggest_terms


def test_digit_words_first_then_others() -> None:
    title = "SSD Kingston NV2 2TB por R$ 599,90 com frete grátis"
    assert suggest_terms(title) == ("nv2", "2tb", "ssd", "kingston")


def test_cap_is_five_terms() -> None:
    assert len(suggest_terms("alfa beta gama delta epsilon zeta eta")) == 5


def test_percentage_only_gives_nothing() -> None:
    assert suggest_terms("50% OFF") == ()


def test_bare_integers_are_kept_but_prices_are_not() -> None:
    assert suggest_terms("Ryzen 5 5600 por 589!!") == ("5", "5600", "ryzen")
