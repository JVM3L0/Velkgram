"""Same-product matching across stores from offer titles (pure, no network).

A title is reduced to a signature: model codes, capacities, screen size, category, bundle flags.
Two titles from different stores are the same product when they share a model code and nothing
in their signatures contradicts it (another capacity, a kit against a single unit, another
category). Character n-gram similarity and the price ratio rank the candidates.
"""

import math
import re
import unicodedata
from dataclasses import dataclass

# --- normalisation ---------------------------------------------------------------------------

_INCH_MARKS = re.compile(r"(\d)\s*(?:\"|″|”|'')")
_SPACES = re.compile(r"\s+")


def _ascii_upper(text: str) -> str:
    folded = unicodedata.normalize("NFKD", _INCH_MARKS.sub(r"\1 POL", text))
    return folded.encode("ascii", "ignore").decode().upper()


# --- model codes -----------------------------------------------------------------------------

_TOKEN = re.compile(r"(?<![A-Z0-9-])[A-Z0-9][A-Z0-9-]{2,}(?![A-Z0-9-])")
# Numbers with a unit, memory and bus standards, resolutions, panel types: not model codes.
_SPEC = re.compile(
    r"^(?:\d+(?:[.,]\d+)?(?:HZ|GB|TB|MB|KB|MM|CM|MS|V|W|MHZ|GHZ|MP|MAH|POL|K|P|PCS|UN|L|ML|G|KG|M"
    r"|BT|NM|BITS?|MBPS|GBPS|X\d+)"
    r"|DDR\d|GDDR\d|PCIE?\d*|USB\d*-?C?|WIFI\d*E?|WI-FI\d*E?|HDMI\d*|NVME|M\.?2|AM\d|LGA\d+"
    r"|IP\d{2}|RGB|ARGB|IPS|VA|TN|OLED|QLED|UHD|FHD|QHD|WQHD|UWQHD|\dK|5G|4G|3D|HDR\d*|ABNT\d"
    r"|\d+-?(?:BIT|BITS|CORES?|NUCLEOS|THREADS)|\d+HZ|\d+GB|\d+TB)$"
)
_GPU = re.compile(r"\b(RTX|GTX|RX|ARC)\s?(\d{3,4})\s?(TI|XT|XTX|SUPER)?\b")


def _is_code(token: str) -> bool:
    letters = sum(c.isalpha() for c in token)
    digits = sum(c.isdigit() for c in token)
    if letters == 0 or digits == 0 or _SPEC.match(token):
        return False
    return (digits >= 2 and len(token) >= 3) or len(token) >= 5


def model_codes(title: str) -> frozenset[str]:
    text = _ascii_upper(title)
    codes = {t for t in _TOKEN.findall(text) if _is_code(t)}
    for family, number, suffix in _GPU.findall(text):
        codes.add(f"{family}{number}{suffix or ''}")
    return frozenset(codes)


# --- capacities, sizes, bundles, category -----------------------------------------------------

_CAPACITY = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(TB|GB)\b")
_INCHES = re.compile(r"\b(\d{2}(?:[.,]\d)?)\s?(?:POL\b|POLEGADAS?\b|IN\b)")
# Same unit, different value: 20 L against 28 L, 750 W against 850 W, 300 Hz against 280 Hz.
_UNIT_VALUES = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(L|W|HZ|MM|KG|BTUS?|PSI|MAH|MP)\b")
_BUNDLE = re.compile(r"\b(?:KIT|COMBO|PACK|LEVE|BUNDLE)\b|\s\+\s")
_QUANTITY = re.compile(
    r"\b(?:KIT|PACK|LEVE|C/|COM)\s?(\d{1,3})\b|\b(\d{1,3})\s?(?:UN|UNID|UNIDADES|PCS|PECAS)\b"
)
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("monitor", ("MONITOR",)),
    ("notebook", ("NOTEBOOK", "LAPTOP", "MACBOOK")),
    ("gpu", ("PLACA DE VIDEO", "PLACA DE VIDEO", "GPU", "GEFORCE", "RADEON")),
    ("motherboard", ("PLACA MAE", "PLACA-MAE")),
    ("cpu", ("PROCESSADOR", "CPU")),
    ("phone", ("SMARTPHONE", "CELULAR", "IPHONE", "GALAXY")),
    ("tv", ("SMART TV", " TV ", "TELEVISAO")),
    ("keyboard", ("TECLADO",)),
    ("mouse", ("MOUSE",)),
    ("headset", ("HEADSET", "FONE", "HEADPHONE")),
    ("ssd", ("SSD", "HD EXTERNO", "PEN DRIVE", "CARTAO DE MEMORIA")),
    ("ram", ("MEMORIA RAM", "MEMORIA PARA", "MEMORIA DDR")),
    ("cooler", ("COOLER", "WATER COOLER", "VENTOINHA", "FAN ")),
    ("psu", ("FONTE",)),
    ("case", ("GABINETE",)),
    ("console", ("CONSOLE", "PLAYSTATION", "XBOX", "NINTENDO")),
    ("game", ("JOGO",)),
    ("wheel", ("VOLANTE",)),
    ("chair", ("CADEIRA",)),
)


def _numbers(pattern: re.Pattern[str], text: str) -> frozenset[float]:
    return frozenset(float(m.replace(",", ".")) for m in pattern.findall(text))


_BRANDS = (
    "AOC",
    "ASUS",
    "ACER",
    "LENOVO",
    "SAMSUNG",
    "LG",
    "MSI",
    "GIGABYTE",
    "TCL",
    "LOGITECH",
    "CORSAIR",
    "KINGSTON",
    "HUSKY",
    "REDRAGON",
    "AMD",
    "INTEL",
    "NVIDIA",
    "SANDISK",
    "CRUCIAL",
    "SONY",
    "APPLE",
    "XIAOMI",
    "MOTOROLA",
    "JBL",
    "ZOTAC",
    "PALIT",
    "GAINWARD",
    "INNO3D",
    "XFX",
    "ASROCK",
    "POWERCOLOR",
    "SAPPHIRE",
    "PICHAU",
    "MANCER",
    "KALKAN",
    "MACH1",
    "HAVIT",
    "PHILCO",
    "BRITANIA",
    "ELECTROLUX",
    "MIDEA",
    "HISENSE",
    "AIWA",
    "TOSHIBA",
    "PHILIPS",
    "DELL",
    "HP",
    "POSITIVO",
    "VAIO",
    "NINTENDO",
    "HYPERX",
    "XPG",
    "COOLER MASTER",
    "NZXT",
    "DEEPCOOL",
    "ARCTIC",
    "THERMALTAKE",
    "WESTERN DIGITAL",
    "SEAGATE",
    "RAZER",
    "ZIN",
    "WAP",
    "ELG",
    "HIKVISION",
    "INTELBRAS",
    "TP-LINK",
    "BASEUS",
    "ANKER",
)
_BRAND_ALIASES = {"WESTERN DIGITAL": "WD", "PLAYSTATION": "SONY"}


def _brand(text: str) -> str | None:
    padded = f" {text} "
    found = [(padded.find(f" {b} "), b) for b in _BRANDS if f" {b} " in padded]
    if not found:
        return None
    brand = min(found)[1]
    return _BRAND_ALIASES.get(brand, brand)


_BARE_NUMBER = re.compile(r"(?<![A-Z0-9.,-])(\d{4,5})(?![A-Z0-9.,-])")
_YEARS = range(1990, 2036)


@dataclass(frozen=True, slots=True)
class Signature:
    brand: str | None
    codes: frozenset[str]
    numbers: frozenset[str]
    capacities_gb: frozenset[int]
    inches: frozenset[float]
    units: frozenset[tuple[str, float]]
    category: str | None
    bundle: bool
    quantity: int | None
    grams: frozenset[str]


def _grams(text: str) -> frozenset[str]:
    padded = f"  {_SPACES.sub(' ', re.sub(r'[^A-Z0-9]+', ' ', text)).strip()}  "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def signature(title: str) -> Signature:
    text = _ascii_upper(title)
    padded = f" {text} "
    capacities = frozenset(
        int(float(n.replace(",", ".")) * (1024 if unit == "TB" else 1))
        for n, unit in _CAPACITY.findall(text)
    )
    category = next((name for name, words in _CATEGORIES if any(w in padded for w in words)), None)
    qty = next((int(a or b) for a, b in _QUANTITY.findall(text)), None)
    return Signature(
        brand=_brand(re.sub(r"[^A-Z0-9]+", " ", text)),
        codes=model_codes(title),
        numbers=frozenset(n for n in _BARE_NUMBER.findall(text) if int(n) not in _YEARS),
        capacities_gb=capacities,
        inches=_numbers(_INCHES, text),
        units=frozenset(
            (unit.rstrip("S") if unit.startswith("BTU") else unit, float(n.replace(",", ".")))
            for n, unit in _UNIT_VALUES.findall(text)
        ),
        category=category,
        bundle=_BUNDLE.search(padded) is not None,
        quantity=qty,
        grams=_grams(text),
    )


# --- comparing two signatures -----------------------------------------------------------------


def _conflict(a: frozenset[float] | frozenset[int], b: frozenset[float] | frozenset[int]) -> bool:
    """Both name values and neither contains the other: they describe different variants."""
    return bool(a) and bool(b) and not (a <= b or b <= a)


def _related(x: str, y: str) -> bool:
    return x in y or y in x


def code_conflict(a: Signature, b: Signature) -> bool:
    """Each title has a model code the other does not, and the codes are unrelated variants.

    5500 against 5500X3D (one extends the other), i5-13450HX against i7-13645HX, B650M-E against
    B650M-AYW. A code that merely contains the other (25G64 / G64) is the same model.
    """
    only_a, only_b = a.codes - b.codes, b.codes - a.codes
    for x in only_a:
        for y in only_b:
            if (
                x[0].isdigit()
                and y[0].isdigit()
                and x != y
                and (y.startswith(x) or x.startswith(y))
            ):
                return True  # one extends the other: a variant suffix (X3D, TI, XT...)
    for number, other in ((a.numbers - b.numbers, b), (b.numbers - a.numbers, a)):
        if any(c.startswith(n) and c != n for n in number for c in other.codes):
            return True  # 5500 against 5500X3D: the bare number is the base model
    unrelated_a = {x for x in only_a if not any(_related(x, y) for y in b.codes)}
    unrelated_b = {y for y in only_b if not any(_related(y, x) for x in a.codes)}
    return bool(unrelated_a) and bool(unrelated_b)


def compatible(a: Signature, b: Signature) -> bool:
    """False when something proves the two titles are different products."""
    if a.category and b.category and a.category != b.category:
        return False
    if a.brand and b.brand and a.brand != b.brand:
        return False
    if a.bundle != b.bundle:
        return False
    if a.quantity is not None and b.quantity is not None and a.quantity != b.quantity:
        return False
    if _conflict(a.capacities_gb, b.capacities_gb) or _conflict(a.inches, b.inches):
        return False
    for unit in {u for u, _ in a.units} & {u for u, _ in b.units}:
        va = frozenset(v for u, v in a.units if u == unit)
        vb = frozenset(v for u, v in b.units if u == unit)
        if _conflict(va, vb):
            return False
    return not code_conflict(a, b)


def shared_codes(a: Signature, b: Signature) -> frozenset[str]:
    return a.codes & b.codes


def specific_codes(
    a: Signature, b: Signature, frequency: dict[str, int], max_offers: int
) -> frozenset[str]:
    """Shared codes few offers carry: a chip (RTX5060) is on dozens of products, a model is not."""
    return frozenset(c for c in a.codes & b.codes if frequency.get(c, 0) <= max_offers)


def gram_similarity(a: Signature, b: Signature) -> float:
    """Jaccard similarity of character trigrams: tolerant to word order and typos."""
    if not a.grams or not b.grams:
        return 0.0
    return len(a.grams & b.grams) / len(a.grams | b.grams)


def price_similarity(a_cents: int, b_cents: int) -> float:
    """1 within 10% of each other, falling to 0 at a 2x gap."""
    if a_cents <= 0 or b_cents <= 0:
        return 0.0
    ratio = max(a_cents, b_cents) / min(a_cents, b_cents)
    return max(0.0, min(1.0, 1 - (math.log(ratio) - math.log(1.1)) / (math.log(2) - math.log(1.1))))


def combined_score(a: Signature, b: Signature, a_cents: int, b_cents: int) -> float:
    """0 when incompatible; else a blend of the shared code, title and price similarity."""
    if not compatible(a, b):
        return 0.0
    code = 1.0 if shared_codes(a, b) else 0.0
    return 0.5 * code + 0.3 * gram_similarity(a, b) + 0.2 * price_similarity(a_cents, b_cents)


__all__ = [
    "Signature",
    "code_conflict",
    "combined_score",
    "compatible",
    "gram_similarity",
    "model_codes",
    "price_similarity",
    "shared_codes",
    "signature",
    "specific_codes",
]
