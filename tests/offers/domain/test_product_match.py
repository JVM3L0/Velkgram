import json
from pathlib import Path

import pytest

from velkgram.offers.domain.product_match import (
    code_conflict,
    compatible,
    gram_similarity,
    model_codes,
    price_similarity,
    signature,
    specific_codes,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "product_match_pairs.json"


def _sig(title: str):  # type: ignore[no-untyped-def]
    return signature(title)


# --- model codes -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "code"),
    [
        ('Monitor Gamer Curvo Aoc Gaming U34g4c 34" Wqhd 180Hz', "U34G4C"),
        ("Processador Amd Ryzen 7 5700x, 3,4 GHz", "5700X"),
        ("Placa de Vídeo Gigabyte RTX 5060 Eagle Max OC", "RTX5060"),
        ("Placa de Vídeo RX 9070 XT Challenger", "RX9070XT"),
        ('Smart Tv Tcl 55" 55C6k Qd-Mini Led', "55C6K"),
    ],
)
def test_model_codes_are_found(title: str, code: str) -> None:
    assert code in model_codes(title)


@pytest.mark.parametrize(
    "title",
    [
        "Monitor 180Hz 0.5ms IPS 27 pol",
        "SSD NVMe PCIe 4.0 M.2 2280 1TB",
        "Placa DDR5 AM5 128-bit HDMI 2.1",
        "Câmera IP66 4K",
    ],
)
def test_specifications_are_not_model_codes(title: str) -> None:
    assert model_codes(title) == frozenset()


# --- vetoes ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Placa de Vídeo Gainward RTX 5060 Ghost",
            "Placa de Vídeo Zotac Gaming RTX 5060 Twin Edge",
        ),  # brand
        (
            "Celular Samsung Galaxy A57 128Gb",
            "Samsung Combo Galaxy A57 (256Gb) + Galaxy Buds",
        ),  # capacity, bundle
        ("Micro-ondas Philco 20L PMO24B", "Micro-ondas Philco 28L PMO30B"),  # unit value
        ("Processador Ryzen 5 5500", "Processador Ryzen 5 5500X3D"),  # one code extends the other
        ("Notebook Lenovo LOQ 15IRX9 i5-13450HX", "Notebook Lenovo LOQ 15IRX9 i7-13645HX"),  # CPUs
        ("Monitor Gamer AOC 27 300Hz", "Monitor Gamer AOC 27 280Hz"),  # refresh rate
        ("Kit Upgrade Ryzen 7 5700X + Placa Mãe A520M", "Ryzen 7 5700x"),  # kit against a unit
        ("Monitor Gamer LG 24 pol", "Monitor Gamer LG 32 pol"),  # screen size
    ],
)
def test_titles_that_contradict_each_other_are_incompatible(a: str, b: str) -> None:
    assert not compatible(_sig(a), _sig(b))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Monitor Gamer TCL Mini LED 25 300Hz HDR 600",
            "Monitor Mini Led Tcl 25G64 25 Full Hd G64 1ms",
        ),
        (
            "Water Cooler Kalkan Aura Digital 360 Argb 360mm",
            "Water cooler Digital Kalkan 360mm 3x Fans",
        ),
        ("SSD Kingston NV3 1TB", "Ssd Nvme Kingston Nv3 1Tb 6000Mb/S"),
        ("Caixa de Som JBL Boombox 4 210W", "Caixa de Som Jbl Boombox 4 Portátil 210W Bivolt"),
    ],
)
def test_the_same_product_worded_differently_is_compatible(a: str, b: str) -> None:
    assert compatible(_sig(a), _sig(b))


def test_a_code_that_contains_the_other_is_the_same_model_not_a_conflict() -> None:
    assert not code_conflict(_sig("Monitor Tcl 25G64"), _sig("Monitor Tcl G64"))


# --- scores ----------------------------------------------------------------------------------


def test_gram_similarity_ignores_word_order_and_case() -> None:
    same = gram_similarity(_sig("Fone Gamer Havit H2002d"), _sig("havit h2002d fone gamer"))
    different = gram_similarity(_sig("Fone Gamer Havit H2002d"), _sig("Notebook Lenovo Ideapad"))
    assert same > 0.7 > different


def test_price_similarity_is_one_close_by_and_zero_far_apart() -> None:
    assert price_similarity(100_00, 105_00) == 1.0
    assert price_similarity(100_00, 250_00) == 0.0
    assert 0 < price_similarity(100_00, 150_00) < 1
    assert price_similarity(0, 100_00) == 0.0


# --- measured against hand-labelled pairs ------------------------------------------------------


def _outcomes(predict):  # type: ignore[no-untyped-def]
    data = json.loads(FIXTURE.read_text())
    freq = data["code_frequency"]
    tp = fp = fn = 0
    for p in data["pairs"]:
        a, b = _sig(p["a"]["title"]), _sig(p["b"]["title"])
        guess = predict(a, b, freq)
        tp += guess and p["same"]
        fp += guess and not p["same"]
        fn += (not guess) and p["same"]
    return tp, fp, fn


def test_a_rare_shared_code_with_vetoes_is_precise_enough_to_show_as_the_same_product() -> None:
    """On 97 hand-labelled pairs: 14 right, 0 wrong (precision 1.0, recall about 0.48)."""
    tp, fp, fn = _outcomes(lambda a, b, f: compatible(a, b) and bool(specific_codes(a, b, f, 20)))
    assert fp == 0
    assert tp >= 14
    assert tp / (tp + fn) >= 0.45


def test_trigram_similarity_with_vetoes_finds_more_but_is_only_a_hint() -> None:
    """Same pairs: about 0.74 precision and 0.79 recall, so useful as 'similar', not as 'same'."""
    tp, fp, fn = _outcomes(lambda a, b, f: compatible(a, b) and gram_similarity(a, b) >= 0.45)
    assert tp / (tp + fn) >= 0.75
    assert tp / (tp + fp) >= 0.68
