from velkgram.offers.domain.title import STORE_TITLES, split_title, store_title, title_of


def test_title_is_first_line_without_link() -> None:
    text = "🔥 SSD Kingston NV2 2TB por R$ 599\nLink: https://amzn.to/x"
    assert title_of(text, None) == "SSD Kingston NV2 2TB por R$ 599"


def test_blank_and_emoji_only_lines_are_skipped() -> None:
    assert title_of("\n  \n🔥🔥\nFone JBL", None) == "Fone JBL"


def test_long_line_is_cut_on_word_boundary() -> None:
    title = title_of(" ".join(["palavra"] * 40), None)
    assert len(title) <= 140
    assert title == title.rstrip()
    assert title.endswith("palavra")


def test_long_line_without_spaces_is_cut_hard() -> None:
    assert title_of("x" * 300, None) == "x" * 140


def test_emoji_modifiers_and_variation_selectors_are_removed() -> None:
    assert title_of("👍🏽 Fone JBL ✔️", None) == "Fone JBL"


def test_casing_and_accents_are_kept() -> None:
    assert title_of("Fritadeira Elétrica AIRFRYER", None) == "Fritadeira Elétrica AIRFRYER"


def test_title_falls_back_when_text_is_only_emoji_and_links() -> None:
    assert title_of("🔥🔥 https://bit.ly/a", "amazon") == "Amazon"
    assert title_of("🔥", None) == "Oferta sem título"


def test_store_titles() -> None:
    assert STORE_TITLES["kabum"] == "KaBuM!"
    assert len(STORE_TITLES) == 12


def test_split_title_returns_the_title_and_the_rest() -> None:
    assert split_title("🔥🔥🔥\nMonitor X\nDetalhe", None) == ("Monitor X", "Detalhe")


def test_split_title_without_a_qualifying_line_has_no_rest() -> None:
    assert split_title("🔥🔥🔥\n\nhttps://x.com/a", "shopee") == (STORE_TITLES["shopee"], "")


def test_store_title_maps_known_slugs_and_passes_unknown_through() -> None:
    assert store_title("mercadolivre") == "Mercado Livre"
    assert store_title("xyz") == "xyz"
