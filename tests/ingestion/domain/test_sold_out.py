import pytest

from velkgram.ingestion import detect_sold_out


@pytest.mark.parametrize(
    "text",
    [
        "ESGOTADO!!",
        "Promoção esgotou rápido",
        "Acabou o estoque",
        "Oferta encerrada",
        "promoção ENCERRADO",
        "Produto indisponível",
        "indisponivel no momento",
    ],
)
def test_detects_sold_out(text: str) -> None:
    assert detect_sold_out(text)


@pytest.mark.parametrize("text", ["SSD 1TB por R$ 300", "", "corre que está acabando"])
def test_ignores_available(text: str) -> None:
    assert not detect_sold_out(text)
