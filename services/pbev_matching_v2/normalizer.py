from __future__ import annotations

import math
import re
import unicodedata
import json
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


_DECIMAL_RE = re.compile(r"(?<!\d)([0-9])\s*[,.]\s*([0-9])(?!\d)")
_VALVE_RE = re.compile(r"\b(6|8|10|12|16|20|24|32|40|48|60)\s*V\b")
_ENGINE_COMPOSITE_RE = re.compile(
    r"\b(TB|TDI|TSI|TFSI|TURBO|BITURBO|GDI|MPI|CRDI|CDI)(6V|8V|10V|12V|16V|20V|24V|32V|40V|48V|60V)\b"
)
_DRIVE_POWER_RE = re.compile(r"\b(XDRIVE|SDRIVE)(\d{2,3}[A-Z]?)\b")
_STYLE_DECIMAL_RE = re.compile(r"(?<=[A-Z])(?=\d+[,.]\d)")
_DECIMAL_SUFFIX_RE = re.compile(r"(?<=\d\.\d)(?=[A-Z])")
_MY_RE = re.compile(r"\bMY\s*[-/]?\s*(\d{2}|20\d{2})\b")

# Canonizações de domínio, não de veículos específicos.
_TOKEN_ALIASES = {
    "AUT": "AUTO",
    "AUTOMATICO": "AUTO",
    "AUTOMATICA": "AUTO",
    "AT": "AUTO",
    "MEC": "MANUAL",
    "MECANICO": "MANUAL",
    "MECANICA": "MANUAL",
    "MT": "MANUAL",
    "TB": "TURBO",
    "BITURBO": "TURBO",
    "HIBRIDA": "HIBRIDO",
    "HYBRID": "HIBRIDO",
    "ELETRICA": "ELETRICO",
    "ELECTRIC": "ELETRICO",
    "TIT": "TITANIUM",
    "TITAN": "TITANIUM",
    "MECAN": "MANUAL",
}

_GENERIC_TOKENS = {
    "DE", "DO", "DA", "DOS", "DAS", "E", "COM", "SEM", "PARA", "THE", "OF",
    "ZERO", "KM", "NOVO", "NOVA", "NEW", "MODELO", "VERSAO", "VEICULO",
    "GASOLINA", "DIESEL", "FLEX", "ETANOL", "ALCOOL", "ELETRICO", "HIBRIDO",
    "COMBUSTAO", "PHEV", "PLUGIN", "PLUG", "IN", "BEV", "HEV", "MHEV",
    "AUTO", "MANUAL", "CVT", "DCT", "DHT", "MTA", "TURBO", "TDI", "TSI", "TFSI",
    "GDI", "MPI", "CRDI", "CDI", "DOHC", "SOHC", "VTEC", "VVT", "VVTIE",
    "AWD", "4WD", "4X4", "4X2", "2WD", "FWD", "RWD", "XDRIVE", "SDRIVE",
    "QUATTRO", "4MATIC", "PORTA", "PORTAS", "CV", "HP", "PS", "KW", "NA",
}

_BODY_TOKENS = {
    "HATCH", "HATCHBACK", "SEDAN", "SEDA", "SED", "SUV", "CROSSOVER", "COUPE",
    "CABRIO", "CABRIOLET", "CONVERSIVEL", "SPIDER", "ROADSTER", "PICKUP", "PICAPE",
    "VAN", "MINIVAN", "WAGON", "PERUA", "SW", "TOURING", "SPORTBACK",
}

# Termos que podem ser importantes comercialmente, mas não devem virar, sozinhos,
# uma trava binária de família.
_SECONDARY_COMMERCIAL_TOKENS = {
    "PRO", "PLUS", "MINI", "LIVE", "YOU", "STYLE", "COMFORT", "SAFETY", "SPORT",
    "TITANIUM", "PREMIUM", "PRESTIGE", "LIMITED", "ULTIMATE", "DARK", "EDITION",
    "M", "S", "SE", "SEL", "GS", "GL", "GT", "ONE", "XRE", "XRX", "XRV",
}


@lru_cache(maxsize=1)
def _external_aliases() -> tuple[tuple[tuple[str, str], ...], dict[str, tuple[str, ...]]]:
    path = Path(__file__).resolve().parents[2] / "data" / "pbev" / "aliases_automotivos_v1.json"
    phrases: list[tuple[str, str]] = []
    tokens: dict[str, tuple[str, ...]] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("phrase_aliases") or []:
            if item.get("pattern") and item.get("replacement") is not None:
                phrases.append((str(item["pattern"]), str(item["replacement"])))
        for token, aliases in (data.get("token_aliases") or {}).items():
            tokens[str(token).upper()] = tuple(str(v).upper() for v in aliases or [])
    except (OSError, ValueError, TypeError):
        pass
    return tuple(phrases), tokens


@dataclass(frozen=True)
class NormalizedText:
    original: str
    normalized: str
    tokens: tuple[str, ...]
    token_set: frozenset[str]
    compact: str
    char_ngrams: frozenset[str]

    def significant_tokens(self) -> frozenset[str]:
        return frozenset(
            token for token in self.token_set
            if token not in _GENERIC_TOKENS
            and not AutomotiveNormalizer.is_year(token)
            and not AutomotiveNormalizer.is_valves(token)
            and not AutomotiveNormalizer.is_displacement(token)
            and not AutomotiveNormalizer.is_gears(token)
            and not AutomotiveNormalizer.is_port_count(token)
        )


class AutomotiveNormalizer:
    """Normalizador automotivo com segmentação reversível de tokens.

    A saída conserva o token comercial original sempre que ele pode ser um nome de
    modelo (HB20S, XC60, E2008, SF90) e acrescenta componentes apenas para padrões
    técnicos de alta confiança (TB12V, xDrive40i, Style1.0, 1.0T).
    """

    @staticmethod
    def strip_accents(value: object) -> str:
        text = str(value or "").strip().upper()
        text = unicodedata.normalize("NFD", text)
        return "".join(c for c in text if unicodedata.category(c) != "Mn")

    @classmethod
    @lru_cache(maxsize=131072)
    def normalize(cls, value: object) -> NormalizedText:
        original = str(value or "")
        text = cls.strip_accents(original)
        if not text:
            return NormalizedText(original, "", tuple(), frozenset(), "", frozenset())

        phrase_aliases, external_token_aliases = _external_aliases()
        for pattern, replacement in phrase_aliases:
            text = re.sub(pattern, replacement, text)

        # Preserva decimais antes de limpar pontuação.
        text = _DECIMAL_RE.sub(r"\1.\2", text)
        text = _ENGINE_COMPOSITE_RE.sub(r"\1 \2", text)
        text = _DRIVE_POWER_RE.sub(r"\1 \2", text)
        text = _STYLE_DECIMAL_RE.sub(" ", text)
        text = _DECIMAL_SUFFIX_RE.sub(" ", text)

        # Frases recorrentes de domínio.
        text = re.sub(r"\bPICK\s*[- ]?\s*UP\b", "PICKUP", text)
        text = re.sub(r"\bPLUG\s*[- ]?\s*IN\b", "PLUGIN", text)
        text = re.sub(r"\bI\s*[- ]?\s*DM\b", "IDM", text)
        text = re.sub(r"\bDM\s*[- ]?\s*I\b", "DMI", text)
        text = re.sub(r"\bTIT\s*\.\s*PLUS\b", "TITANIUM PLUS", text)
        text = re.sub(r"\bTIT\s*\.\b", "TITANIUM", text)

        # Detecta transmissões codificadas antes da limpeza de hífens.
        gear_tokens: list[str] = []
        for prefix, gears in re.findall(r"\b(A|M|DCT|DHT|CVT|AT|MT)\s*[- ]\s*(\d{1,2})\b", text):
            n = int(gears)
            if 1 <= n <= 12:
                gear_tokens.append(f"{n}MARCHAS")
                if prefix == "M" or prefix == "MT":
                    gear_tokens.append("MANUAL")
                else:
                    gear_tokens.append("AUTO")
                if prefix in {"DCT", "DHT", "CVT"}:
                    gear_tokens.append(prefix)

        # Pontuação vira separador, mantendo o ponto decimal.
        text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
        text = re.sub(r"[^A-Z0-9.]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        raw_tokens = text.split()
        tokens: list[str] = []
        has_displacement = any(cls.is_displacement(t) for t in raw_tokens)
        has_valves = any(cls.is_valves(t) for t in raw_tokens)

        for token in raw_tokens:
            canonical = _TOKEN_ALIASES.get(token, token)
            # T isolado é turbo somente em contexto de motor; caso contrário pode
            # ser parte de acabamento/código e é preservado.
            if canonical == "T" and (has_displacement or has_valves):
                canonical = "TURBO"
            tokens.append(canonical)
            tokens.extend(external_token_aliases.get(token, ()))
            if canonical != token:
                tokens.extend(external_token_aliases.get(canonical, ()))

            # Mantém token compacto para similaridade e acrescenta componentes
            # apenas em padrões técnicos/comerciais seguros.
            m = re.fullmatch(r"(XDRIVE|SDRIVE)(\d{2,3}[A-Z]?)", canonical)
            if m:
                tokens.extend(m.groups())
            m = re.fullmatch(r"(TB|TDI|TSI|TFSI|TURBO)(6V|8V|10V|12V|16V|20V|24V|32V|40V|48V|60V)", canonical)
            if m:
                tokens.extend(("TURBO" if m.group(1) in {"TB", "TURBO"} else m.group(1), m.group(2)))

        tokens.extend(gear_tokens)

        # Identificadores comerciais compostos separados pela fonte: XC 60,
        # E 2008, S 06, WEY 07. O token composto é acrescentado, sem remover os
        # originais, para preservar auditoria e melhorar a equivalência.
        composite_prefixes = {"A", "B", "C", "E", "F", "G", "H", "I", "Q", "S", "T", "V", "X", "Z", "XC", "CX", "MX", "RX", "ID", "WEY"}
        extra_composites: list[str] = []
        for left, right in zip(tokens, tokens[1:]):
            # Catálogos alternam livremente CLA 200/CLA200, SERES 3/SERES3,
            # TIGGO 5X/TIGGO5X e SLC 300/SLC300. A composição é adicionada
            # sem apagar os tokens originais. Decimais (STYLE 1.0), válvulas
            # e portas não entram nesta regra, evitando recriar STYLE1/TB12V.
            right_is_model_number = bool(re.fullmatch(r"\d{1,4}[A-Z]?", right)) and not right.endswith(("V", "P"))
            left_is_model_word = (
                left in composite_prefixes
                or (
                    len(left) >= 2
                    and left.isalpha()
                    and left not in _GENERIC_TOKENS
                    and left not in _BODY_TOKENS
                    and left not in _SECONDARY_COMMERCIAL_TOKENS
                )
            )
            if left_is_model_word and right_is_model_number:
                extra_composites.append(f"{left}{right}")
        tokens.extend(extra_composites)

        # Reagrupa válvulas que tenham sido separadas pela origem.
        normalized_joined = " ".join(tokens)
        normalized_joined = _VALVE_RE.sub(lambda m: f"{m.group(1)}V", normalized_joined)
        tokens = normalized_joined.split()

        # Deduplicação estável: repetições da FIPE (modelo + texto_modelo) não
        # devem inflar similaridade.
        dedup: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token and token not in seen:
                seen.add(token)
                dedup.append(token)

        normalized = " ".join(dedup)
        compact = re.sub(r"[^A-Z0-9]", "", normalized)
        ngrams = frozenset(cls.char_ngrams(compact, 3))
        return NormalizedText(original, normalized, tuple(dedup), frozenset(dedup), compact, ngrams)

    @staticmethod
    def char_ngrams(text: str, n: int = 3) -> Iterable[str]:
        if not text:
            return ()
        padded = f"^{text}$"
        if len(padded) <= n:
            return (padded,)
        return tuple(padded[i : i + n] for i in range(len(padded) - n + 1))

    @staticmethod
    def is_displacement(token: str) -> bool:
        return bool(re.fullmatch(r"[0-9]\.[0-9]", token))

    @staticmethod
    def is_valves(token: str) -> bool:
        return bool(re.fullmatch(r"(?:6|8|10|12|16|20|24|32|40|48|60)V", token))

    @staticmethod
    def is_year(token: str) -> bool:
        return bool(re.fullmatch(r"(?:19|20)\d{2}", token))

    @staticmethod
    def is_gears(token: str) -> bool:
        return bool(re.fullmatch(r"(?:[1-9]|1[0-2])MARCHAS", token))

    @staticmethod
    def is_port_count(token: str) -> bool:
        return bool(re.fullmatch(r"[1-9]P", token))

    @staticmethod
    def is_power_token(token: str) -> bool:
        return bool(
            re.fullmatch(r"\d{2,4}(?:CV|HP|PS|KW|EV)", token)
            or re.fullmatch(r"\d{2,3}[ID]", token)
            or re.fullmatch(r"P\d{2,3}", token)
        )

    @staticmethod
    def is_alphanumeric_model_token(token: str) -> bool:
        if AutomotiveNormalizer.is_valves(token) or AutomotiveNormalizer.is_power_token(token):
            return False
        if token in {"4X4", "4X2", "2WD", "4WD"}:
            return False
        return bool(re.search(r"[A-Z]", token) and re.search(r"\d", token) and 2 <= len(token) <= 10)

    @staticmethod
    def is_secondary_commercial(token: str) -> bool:
        return token in _SECONDARY_COMMERCIAL_TOKENS or AutomotiveNormalizer.is_power_token(token)

    @staticmethod
    def is_body(token: str) -> bool:
        return token in _BODY_TOKENS

    @staticmethod
    def is_generic(token: str) -> bool:
        return token in _GENERIC_TOKENS

    @staticmethod
    def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    @staticmethod
    def overlap_coefficient(a: Iterable[str], b: Iterable[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / min(len(sa), len(sb))

    @staticmethod
    def cosine_from_sets(a: Iterable[str], b: Iterable[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / math.sqrt(len(sa) * len(sb))
