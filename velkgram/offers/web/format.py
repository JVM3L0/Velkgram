"""Display formatting for the offers web views (pt-BR)."""


def brl(cents: int | None) -> str:
    """Format integer cents as "R$ 1.299,90"; None as the unknown-price text."""
    if cents is None:
        return "preço não identificado"
    reais, rest = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{rest:02d}"
