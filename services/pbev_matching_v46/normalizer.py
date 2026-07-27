from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Iterable

from .models import TechnicalEvidence, TextViews


# Aliases puramente lexicais/técnicos. O token original é sempre preservado.
TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "AUT": ("AUTOMATICO",),
    "AUTO": ("AUTOMATICO",),
    "AT": ("AUTOMATICO",),
    "MEC": ("MANUAL",),
    "MT": ("MANUAL",),
    "TB": ("TURBO",),
    "TDI": ("TURBO", "DIESEL"),
    "TIT": ("TITANIUM",),
    "TITPLUS": ("TITANIUM", "PLUS"),
    "ULTIM": ("ULTIMATE",),
    "ULT": ("ULTIMATE",),
    "ULTD": ("ULTIMATE", "DARK"),
    "ULTRA": ("ULTIMATE",),
    "SPI": ("SPIDER",),
    "ED": ("EDITION",),
    "PREM": ("PREMIUM",),
    "INTP": ("INTENSE", "PLUS"),
    "INT": ("INTENSE",),
    "HEV": ("HIBRIDO",),
    "PHEV": ("HIBRIDO", "PLUGIN"),
    "CVT": ("AUTOMATICO",),
    "DCT": ("AUTOMATICO",),
    "DHT": ("AUTOMATICO",),
    "INSC": ("INSCRIPTION",),
    "INSCRIPT": ("INSCRIPTION",),
    "MOMENT": ("MOMENTUM",),
    "RDESIGN": ("R", "DESIGN"),
}

PHRASE_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTIT\s*PLUS\b"), "TITANIUM PLUS"),
    (re.compile(r"\bTIT\b"), "TITANIUM"),
    (re.compile(r"\bC\s*PLUS\b"), "COMFORT PLUS"),
    (re.compile(r"\bC\s*STYLE\b"), "COMFORT STYLE"),
    (re.compile(r"\bULTIM\s*DARK\b"), "ULTIMATE DARK"),
    (re.compile(r"\bULT\s*DARK\b"), "ULTIMATE DARK"),
    (re.compile(r"\bULTRA\s*DARK\b"), "ULTIMATE DARK"),
    (re.compile(r"\bDARK\s*ED\b"), "DARK EDITION"),
    (re.compile(r"\bPICK\s*UP\b"), "PICKUP"),
)

GENERIC_TOKENS = {
    "DE", "DA", "DO", "DAS", "DOS", "E", "COM", "SEM", "PARA", "NOVO", "NOVA", "NEW",
    "ZERO", "KM", "MODELO", "VERSAO", "PORTA", "PORTAS", "P", "CV", "HP", "PS", "KW",
    "FLEX", "GASOLINA", "DIESEL", "ETANOL", "ALCOOL", "ELETRICO", "ELETRICA", "HIBRIDO",
    "HIBRIDA", "HYBRID", "AUT", "AUTO", "AUTOMATICO", "AUTOMATICA", "MANUAL", "MEC", "MECANICO",
    "MECANICA", "AT", "MT", "TURBO", "TB", "TDI", "TSI", "TFSI", "GDI", "MPI", "DOHC", "SOHC",
    "VALV", "VALVULAS", "MY", "NA",
}

MODEL_NOISE_TOKENS = GENERIC_TOKENS | {
    "HATCH", "HATCHBACK", "SEDAN", "SEDA", "COUPE", "CONVERSIVEL", "CABRIO", "SPIDER", "ROADSTER",
    "SUV", "SW", "WAGON", "TOURING", "PICAPE", "PICKUP", "CD", "CS", "CE", "DIESEL", "GASOLINA",
    "AWD", "FWD", "RWD", "4X4", "4X2", "AUTOMATICO", "MANUAL", "CVT", "DCT", "DHT", "AT", "MT",
}

# Descritores que podem fazer parte da família comercial e, por isso, não são ruído.
FAMILY_DESCRIPTORS = {"CROSS", "PLUS", "PRO", "MINI", "MAX"}

BODY_MAP = {
    "HATCH": "HATCH", "HATCHBACK": "HATCH", "SEDAN": "SEDAN", "SEDA": "SEDAN",
    "COUPE": "COUPE", "SPIDER": "SPIDER", "ROADSTER": "ROADSTER", "CABRIO": "CONVERSIVEL",
    "CONVERSIVEL": "CONVERSIVEL", "PICKUP": "PICKUP", "PICAPE": "PICKUP", "SW": "WAGON",
    "WAGON": "WAGON", "TOURING": "WAGON", "VAN": "VAN", "MINIVAN": "MINIVAN", "CROSS": "CROSS",
}

DRIVE_MAP = {
    "AWD": "AWD", "4X4": "AWD", "4WD": "AWD", "XDRIVE": "AWD", "QUATTRO": "AWD", "4MATIC": "AWD",
    "RWD": "RWD", "FWD": "FWD", "4X2": "4X2", "SDRIVE": "2WD",
}


def strip_accents(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _clean_text(value: Any) -> str:
    text = strip_accents(value)
    if not text:
        return ""
    # Preserva decimais e designações hifenizadas antes da limpeza geral.
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    text = re.sub(r"[/|]+", " ", text)
    text = re.sub(r"(?<=[A-Z])\.(?=[A-Z])", " ", text)
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    text = re.sub(r"[^A-Z0-9.\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _segment(text: str) -> str:
    if not text:
        return ""
    t = text
    # Colagens técnicas recorrentes, sem destruir o token original (compact/atoms o preservam).
    t = re.sub(r"\b(XDRIVE|SDRIVE)(\d{2,3}[A-Z]?)\b", r"\1 \2", t)
    t = re.sub(r"\b([A-Z]{1,5})(\d{1,2}V)\b", r"\1 \2", t)  # TB12V / TDI16V
    t = re.sub(r"\b([A-Z]{2,20})(\d\.\d)\b", r"\1 \2", t)  # STYLE1.0
    t = re.sub(r"\b(\d\.\d)([A-Z]{1,4})\b", r"\1 \2", t)  # 1.0T
    t = re.sub(r"\b(T)(\d)\b", r"\1\2", t)                 # preserva T8/T5
    t = re.sub(r"\b([A-Z]{1,3})\s*[-]\s*(\d{1,4}[A-Z]?)\b", r"\1 \2", t)
    t = t.replace("-", " ")
    return re.sub(r"\s+", " ", t).strip()


def _apply_phrase_aliases(segmented: str) -> str:
    text = segmented
    for pattern, replacement in PHRASE_ALIASES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def _base_tokens(segmented: str) -> list[str]:
    return [t for t in segmented.split() if t and t != "."]


def _atoms(original_clean: str, segmented: str, tokens: Iterable[str]) -> set[str]:
    atoms = set(tokens)
    compact = re.sub(r"[^A-Z0-9]", "", original_clean)
    if compact:
        atoms.add(compact)

    # Compostos adjacentes são evidências adicionais, não substitutos.
    seq = list(tokens)
    for size in (2, 3):
        for i in range(0, max(0, len(seq) - size + 1)):
            joined = "".join(seq[i:i + size])
            if 2 <= len(joined) <= 18:
                atoms.add(joined)

    # Identificadores comerciais recorrentes.
    for m in re.finditer(r"\b(?:X|S|C|E|I|Q|T|G|A|B|F|Z|CX|XC|RX|HB)\s*\d{1,4}[A-Z]?\b", segmented):
        atoms.add(re.sub(r"\s+", "", m.group(0)))
    for m in re.finditer(r"\b(?:XDRIVE|SDRIVE)\s*\d{2,3}[A-Z]?\b", segmented):
        atoms.add(re.sub(r"\s+", "", m.group(0)))
    for m in re.finditer(r"\b(?:SF|WEY|ORA)\s*\d{2,4}\b", segmented):
        atoms.add(re.sub(r"\s+", "", m.group(0)))
    return {a for a in atoms if a}


def char_ngrams(text: str, n: int = 3) -> frozenset[str]:
    compact = re.sub(r"[^A-Z0-9]", "", text)
    if len(compact) < n:
        return frozenset({compact} if compact else set())
    return frozenset(compact[i:i+n] for i in range(len(compact)-n+1))


def build_text_views(value: Any) -> TextViews:
    original = str(value or "")
    cleaned = _clean_text(original)
    segmented = _apply_phrase_aliases(_segment(cleaned))
    base = _base_tokens(segmented)
    expanded = list(base)
    for index, token in enumerate(base):
        expanded.extend(TOKEN_ALIASES.get(token, ()))
        if token == "T" and index > 0 and re.fullmatch(r"\d\.\d", base[index - 1]):
            expanded.append("TURBO")
    tokens = frozenset(expanded)
    atoms = frozenset(_atoms(cleaned, segmented, expanded))
    canonical = " ".join(expanded)
    compact = re.sub(r"[^A-Z0-9]", "", canonical)
    return TextViews(
        original=original,
        canonical=canonical,
        segmented=segmented,
        compact=compact,
        tokens=tokens,
        atoms=atoms,
        char_ngrams=char_ngrams(canonical),
    )


def _parse_year(value: Any) -> int | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    if not m:
        return None
    year = int(m.group(1))
    return year if 2010 <= year <= 2035 else None


def extract_technical_evidence(
    views: TextViews,
    *,
    year: int | None = None,
    zero_km: bool = False,
    propulsion: str | None = None,
    fuel: str | None = None,
    infer_natural: bool = False,
) -> TechnicalEvidence:
    text = views.segmented
    displacements = {float(x) for x in re.findall(r"(?<!\d)([0-9]\.[0-9])(?!\d)", text)}
    valves = {int(x) for x in re.findall(r"\b(\d{1,2})\s*V\b", text)}
    cylinders = {int(x) for x in re.findall(r"\bV\s*(6|8|10|12)\b", text)}

    turbo = None
    if re.search(r"\b(TURBO|TB|TDI|TSI|TFSI|BITURBO|BI\s*TURBO)\b|\b\d\.\d\s+T\b", text):
        turbo = True
    elif "ASPIRADO" in views.tokens or "NATURAL" in views.tokens or (infer_natural and displacements and valves):
        turbo = False

    transmission_family = None
    transmission_subtype = None
    if re.search(r"\b(MANUAL|MEC|MT)\b|\bM\s*\d\b", text):
        transmission_family, transmission_subtype = "MANUAL", "MANUAL"
    if re.search(r"\b(CVT)\b", text):
        transmission_family, transmission_subtype = "AUTO", "CVT"
    elif re.search(r"\b(DCT)\b", text):
        transmission_family, transmission_subtype = "AUTO", "DCT"
    elif re.search(r"\b(DHT)\b", text):
        transmission_family, transmission_subtype = "AUTO", "DHT"
    elif re.search(r"\b(AUTOMATICO|AUT|AUTO|AT)\b|\bA\s*\d\b", text):
        transmission_family, transmission_subtype = "AUTO", "AUTO"

    gears = None
    m_gear = re.search(r"\b(?:A|M|CVT|DCT|DHT)\s*(\d)\b", text)
    if m_gear:
        gears = int(m_gear.group(1))

    drives = {normalized for token, normalized in DRIVE_MAP.items() if token in views.tokens}
    bodies = {normalized for token, normalized in BODY_MAP.items() if token in views.tokens}
    model_years: set[int] = set()
    for century, yy in re.findall(r"\bMY\s*(20)?(\d{2})\b", text):
        value = int(yy)
        model_years.add(2000 + value if not century else int(f"{century}{yy}"))

    return TechnicalEvidence(
        displacements=frozenset(displacements),
        valves=frozenset(valves),
        cylinders=frozenset(cylinders),
        turbo=turbo,
        transmission_family=transmission_family,
        transmission_subtype=transmission_subtype,
        gears=gears,
        drives=frozenset(drives),
        bodies=frozenset(bodies),
        propulsion=propulsion,
        fuel=fuel,
        year=year or _parse_year(text),
        zero_km=zero_km,
        model_years=frozenset(model_years),
    )


def model_core_tokens(views: TextViews) -> frozenset[str]:
    result = set()
    for token in views.tokens:
        if token in FAMILY_DESCRIPTORS:
            result.add(token)
            continue
        if token in MODEL_NOISE_TOKENS:
            continue
        if re.fullmatch(r"\d\.\d", token) or re.fullmatch(r"\d{1,2}V", token):
            continue
        if re.fullmatch(r"\d{4}", token) or re.fullmatch(r"\d+P", token):
            continue
        if token.isdigit() and len(token) <= 2:
            continue
        result.add(token)
    return frozenset(result)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def overlap_coefficient(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def token_f1(a: Iterable[str], b: Iterable[str], weights: dict[str, float] | None = None) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    weights = weights or {}
    def w(token: str) -> float:
        return max(0.2, float(weights.get(token, 1.0)))
    shared = sum(w(t) for t in sa & sb)
    precision = shared / sum(w(t) for t in sb)
    recall = shared / sum(w(t) for t in sa)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def sequence_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def compute_idf(documents: Iterable[Iterable[str]]) -> dict[str, float]:
    docs = [set(d) for d in documents]
    count = Counter(token for doc in docs for token in doc)
    total = max(1, len(docs))
    return {token: math.log((total + 1) / (df + 1)) + 1.0 for token, df in count.items()}
