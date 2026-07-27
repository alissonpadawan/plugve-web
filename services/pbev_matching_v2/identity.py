from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .normalizer import AutomotiveNormalizer, NormalizedText


_TRIM_HINTS = {
    "COMFORT", "SAFETY", "STYLE", "TITANIUM", "PLUS", "PRO", "MINI", "LIVE", "YOU",
    "FEEL", "SHINE", "PREMIUM", "PRESTIGE", "LIMITED", "PLATINUM", "ULTIMATE",
    "DARK", "EDITION", "M", "SPORT", "MSPORT", "N", "LINE", "NLINE", "ONE", "GT",
    "GS", "GL", "SE", "SEL", "XLS", "XRE", "XRX", "XRV", "INTENSE", "ICONIC",
    "LONGITUDE", "TRAILHAWK", "RANCH", "TREMOR", "WILDTRAK", "HSE", "DYNAMIC",
    "STERRATO", "SVJ", "ROADSTER", "SPIDER", "ULTRA", "MOMENT", "MOMENTUM", "FIRST", "ED", "EDITION", "INSCRIPTION", "ADVANCE",
}

_DESCRIPTOR_TOKENS = {"PRO", "PLUS", "MINI", "CROSS"}
_BODY_CANONICAL = {
    "HATCH": "HATCH", "HATCHBACK": "HATCH", "SEDAN": "SEDAN", "SEDA": "SEDAN", "SED": "SEDAN",
    "SUV": "SUV", "CROSSOVER": "SUV", "COUPE": "COUPE", "CABRIO": "CONVERSIVEL",
    "CABRIOLET": "CONVERSIVEL", "CONVERSIVEL": "CONVERSIVEL", "SPIDER": "CONVERSIVEL",
    "ROADSTER": "CONVERSIVEL", "PICKUP": "PICKUP", "PICAPE": "PICKUP", "VAN": "VAN",
    "MINIVAN": "VAN", "WAGON": "WAGON", "PERUA": "WAGON", "SW": "WAGON", "TOURING": "WAGON",
    "SPORTBACK": "SPORTBACK",
}


@dataclass(frozen=True)
class TechnicalIdentity:
    source: str
    original: str
    normalized: NormalizedText
    brand: str
    model_normalized: NormalizedText
    version_normalized: NormalizedText
    engine_normalized: NormalizedText
    model_tokens: frozenset[str]
    model_core_tokens: frozenset[str]
    model_alnum_anchors: frozenset[str]
    descriptors: frozenset[str]
    trim_tokens: frozenset[str]
    semantic_tokens: frozenset[str]
    commercial_power: frozenset[str]
    displacements: frozenset[float]
    valves: frozenset[int]
    turbo: bool | None
    transmission: str | None
    transmission_subtype: str | None
    gears: int | None
    drive: str | None
    body: str | None
    fuel: str | None
    propulsion: str | None
    year: int | None
    model_year: int | None
    zero_km: bool = False
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    def audit_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "texto_normalizado": self.normalized.normalized,
            "modelo_normalizado": self.model_normalized.normalized,
            "versao_normalizada": self.version_normalized.normalized,
            "tokens": sorted(self.semantic_tokens),
            "tokens_familia": sorted(self.model_core_tokens),
            "tokens_fortes_modelo": sorted(self.model_alnum_anchors),
            "acabamentos": sorted(self.trim_tokens),
            "designacoes_comerciais": sorted(self.commercial_power),
            "cilindrada": ", ".join(f"{v:.1f}" for v in sorted(self.displacements)) or "",
            "valvulas": ", ".join(f"{v}V" for v in sorted(self.valves)) or "",
            "turbo": self.turbo,
            "transmissao": self.transmission or "",
            "subtipo_transmissao": self.transmission_subtype or "",
            "marchas": self.gears,
            "tracao": self.drive or "",
            "carroceria": self.body or "",
            "combustivel": self.fuel or "",
            "propulsao": self.propulsion or "",
            "ano": self.year,
            "my": self.model_year,
            "zero_km": self.zero_km,
        }


def _brand_key(value: Any) -> str:
    text = AutomotiveNormalizer.normalize(value).normalized
    if not text:
        return ""
    if "CHEVROLET" in text or text in {"GM", "G M", "GM CHEVROLET"}:
        return "CHEVROLET"
    if "VOLKSWAGEN" in text or text in {"VW", "VOLKS", "VOLKS WAGEN"}:
        return "VOLKSWAGEN"
    if "MERCEDES" in text or "BENZ" in text or text in {"MB", "M BENZ"}:
        return "MERCEDES BENZ"
    if "GREAT WALL" in text or text == "GWM":
        return "GWM"
    if "LAND ROVER" in text or text == "LR":
        return "LAND ROVER"
    if "CAOA" in text and "HYUNDAI" in text:
        return "HYUNDAI"
    if "CHERY" in text:
        return "CHERY"
    return text


def _parse_year(value: Any) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    if not match:
        return None
    year = int(match.group(1))
    return year if 2010 <= year <= 2035 else None


def _parse_model_year(*values: Any) -> int | None:
    text = " ".join(str(v or "") for v in values).upper()
    match = re.search(r"\bMY\s*[-/]?\s*(20\d{2}|\d{2})\b", text)
    if match:
        v = int(match.group(1))
        return v if v >= 2000 else 2000 + v
    match = re.search(r"\b(?:19|20)\d{2}\s*/\s*((?:19|20)?\d{2})\b", text)
    if match:
        v = int(match.group(1))
        return v if v >= 2000 else 2000 + v
    return None


def _parse_displacements(*texts: str) -> frozenset[float]:
    raw = " ".join(texts).replace(",", ".")
    values: set[float] = set()
    for match in re.findall(r"(?<!\d)([0-6]\.[0-9])(?!\d)", raw):
        try:
            value = float(match)
        except ValueError:
            continue
        if 0.6 <= value <= 6.9:
            values.add(round(value, 1))
    return frozenset(values)


def _parse_valves(norm: NormalizedText) -> frozenset[int]:
    values: set[int] = set()
    for token in norm.tokens:
        match = re.fullmatch(r"(6|8|10|12|16|20|24|32|40|48|60)V", token)
        if match:
            values.add(int(match.group(1)))
    return frozenset(values)


def _parse_turbo(norm: NormalizedText) -> bool | None:
    tokens = norm.token_set
    if tokens & {"TURBO", "TDI", "TSI", "TFSI", "CRDI", "CDI", "BITURBO"}:
        return True
    if tokens & {"ASPIRADO", "ASPIRADA", "NATURALMENTE"}:
        return False
    # Sufixo T após cilindrada já é convertido pelo normalizador.
    return None


def _parse_transmission(norm: NormalizedText) -> tuple[str | None, str | None, int | None]:
    tokens = norm.token_set
    subtype: str | None = None
    if "CVT" in tokens:
        subtype = "CVT"
    elif "DCT" in tokens:
        subtype = "DCT"
    elif "DHT" in tokens:
        subtype = "DHT"
    elif "MTA" in tokens:
        subtype = "MTA"
    transmission: str | None = None
    if subtype or "AUTO" in tokens:
        transmission = "AUTO"
    elif "MANUAL" in tokens:
        transmission = "MANUAL"
    gears = None
    for token in tokens:
        m = re.fullmatch(r"(\d{1,2})MARCHAS", token)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 12:
                gears = n
                break
    return transmission, subtype, gears


def _parse_drive(norm: NormalizedText) -> str | None:
    tokens = norm.token_set
    if tokens & {"AWD", "4WD", "4X4", "XDRIVE", "QUATTRO", "4MATIC"}:
        return "AWD"
    if "RWD" in tokens:
        return "RWD"
    if "FWD" in tokens:
        return "FWD"
    if tokens & {"4X2", "2WD"}:
        return "2WD"
    return None


def _parse_body(norm: NormalizedText) -> str | None:
    found = [_BODY_CANONICAL[token] for token in norm.tokens if token in _BODY_CANONICAL]
    if not found:
        return None
    # Termos mais específicos vencem SUV genérico.
    for preferred in ("CONVERSIVEL", "PICKUP", "VAN", "WAGON", "SPORTBACK", "COUPE", "SEDAN", "HATCH", "SUV"):
        if preferred in found:
            return preferred
    return found[0]


def _parse_fuel(*values: Any) -> str | None:
    text = AutomotiveNormalizer.normalize(" ".join(str(v or "") for v in values)).normalized
    tokens = set(text.split())
    if tokens & {"ELETRICO", "BEV", "EV"}:
        return "ELETRICO"
    if "DIESEL" in tokens or "D" == text:
        return "DIESEL"
    if tokens & {"FLEX", "ETANOL", "ALCOOL"} or text == "F":
        return "FLEX"
    if "GASOLINA" in tokens or text == "G":
        return "GASOLINA"
    if tokens & {"HIBRIDO", "PHEV", "PLUGIN", "HEV", "MHEV"}:
        return "HIBRIDO"
    return None


def _parse_propulsion(*values: Any) -> str | None:
    text = AutomotiveNormalizer.normalize(" ".join(str(v or "") for v in values)).normalized
    tokens = set(text.split())
    if tokens & {"PHEV", "PLUGIN", "IDM", "DMI"} or "PLUG IN" in text:
        return "PHEV"
    if tokens & {"BEV", "ELETRICO", "EV"}:
        return "BEV"
    if "MHEV" in tokens:
        return "MHEV"
    if tokens & {"HEV", "HIBRIDO"}:
        return "HEV"
    if tokens & {"COMBUSTAO", "GASOLINA", "FLEX", "DIESEL"}:
        return "ICE"
    return None


def _semantic_tokens(norm: NormalizedText, brand: str) -> frozenset[str]:
    brand_tokens = AutomotiveNormalizer.normalize(brand).token_set
    result: set[str] = set()
    for token in norm.tokens:
        if token in brand_tokens or AutomotiveNormalizer.is_generic(token):
            continue
        if AutomotiveNormalizer.is_year(token) or AutomotiveNormalizer.is_displacement(token):
            continue
        if AutomotiveNormalizer.is_valves(token) or AutomotiveNormalizer.is_gears(token):
            continue
        if AutomotiveNormalizer.is_port_count(token):
            continue
        result.add(token)
    return frozenset(result)


def _model_core_tokens(model_norm: NormalizedText, brand: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    brand_tokens = AutomotiveNormalizer.normalize(brand).token_set
    model_tokens: set[str] = set()
    descriptors: set[str] = set()
    alnum: set[str] = set()
    source_tokens = list(model_norm.tokens)
    first_meaningful = next((t for t in source_tokens if t not in brand_tokens and not AutomotiveNormalizer.is_generic(t)), None)
    for token in source_tokens:
        if token in brand_tokens or AutomotiveNormalizer.is_generic(token) or AutomotiveNormalizer.is_body(token):
            continue
        if AutomotiveNormalizer.is_displacement(token) or AutomotiveNormalizer.is_valves(token):
            continue
        if AutomotiveNormalizer.is_gears(token) or AutomotiveNormalizer.is_port_count(token):
            continue
        if token.isdigit():
            # Modelos numéricos puros (Jaecoo 7) são válidos; números técnicos
            # soltos (XC 40 T-5, potência, marchas) não viram família.
            if token != first_meaningful or len(token) > 2:
                continue
        if token in _TRIM_HINTS and token not in _DESCRIPTOR_TOKENS:
            continue
        if AutomotiveNormalizer.is_power_token(token):
            continue
        if token in _DESCRIPTOR_TOKENS:
            descriptors.add(token)
        model_tokens.add(token)
        if AutomotiveNormalizer.is_alphanumeric_model_token(token):
            alnum.add(token)
    return frozenset(model_tokens), frozenset(alnum), frozenset(descriptors)


def _trim_tokens(version_norm: NormalizedText, model_norm: NormalizedText) -> frozenset[str]:
    result: set[str] = set()
    for token in tuple(version_norm.tokens) + tuple(model_norm.tokens):
        if AutomotiveNormalizer.is_power_token(token):
            continue
        if token in _TRIM_HINTS or AutomotiveNormalizer.is_secondary_commercial(token):
            result.add(token)
    return frozenset(result)


def _commercial_power(norm: NormalizedText) -> frozenset[str]:
    return frozenset(token for token in norm.tokens if AutomotiveNormalizer.is_power_token(token) or token.isdigit() and 100 <= int(token) <= 999)


def _query_model_segment(model_text: str) -> str:
    # Mantém tudo até o primeiro fato técnico forte. Isso não fixa a família; apenas
    # cria uma visão lexical de maior peso para o nome comercial.
    norm = AutomotiveNormalizer.normalize(model_text)
    kept: list[str] = []
    for token in norm.tokens:
        if AutomotiveNormalizer.is_displacement(token) or AutomotiveNormalizer.is_valves(token):
            break
        if token in {"FLEX", "GASOLINA", "DIESEL", "ELETRICO", "HIBRIDO", "AUTO", "MANUAL", "CVT", "DCT", "DHT"}:
            break
        kept.append(token)
    return " ".join(kept) or model_text


def build_query_identity(consulta: dict[str, Any]) -> TechnicalIdentity:
    brand = _brand_key(consulta.get("marca"))
    model_text = " ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo")).strip()
    full_text = " ".join(
        str(consulta.get(k) or "")
        for k in ("marca", "modelo", "texto_modelo", "texto_ano", "combustivel", "tipo_veiculo")
    )
    model_segment = _query_model_segment(str(consulta.get("modelo") or model_text))
    full_norm = AutomotiveNormalizer.normalize(full_text)
    model_norm = AutomotiveNormalizer.normalize(model_segment)
    version_norm = AutomotiveNormalizer.normalize(str(consulta.get("modelo") or ""))
    engine_norm = AutomotiveNormalizer.normalize(model_text)
    model_core, alnum, descriptors = _model_core_tokens(model_norm, brand)
    semantic = _semantic_tokens(full_norm, brand)
    transmission, subtype, gears = _parse_transmission(full_norm)
    zero_km = any(
        "32000" in str(consulta.get(k) or "")
        for k in ("ano", "ano_codigo", "codigo_ano", "texto_ano")
    ) or "ZERO" in full_norm.token_set
    year = (
        _parse_year(consulta.get("ano_modelo"))
        or (_parse_year(consulta.get("ano")) if "32000" not in str(consulta.get("ano") or "") else None)
        or _parse_year(consulta.get("texto_ano"))
    )
    prefix = str(consulta.get("prefixo") or "").lower()
    propulsion = _parse_propulsion(model_text, consulta.get("combustivel"), consulta.get("tipo_veiculo"))
    # O lado da Simular tem precedência para separar HEV de PHEV/BEV.
    if prefix == "ve":
        if propulsion != "BEV":
            propulsion = "PHEV"
    elif prefix == "icev" and propulsion in {"PHEV", "BEV"}:
        propulsion = "HEV" if _parse_fuel(consulta.get("combustivel")) == "HIBRIDO" else "ICE"
    return TechnicalIdentity(
        source="FIPE",
        original=full_text,
        normalized=full_norm,
        brand=brand,
        model_normalized=model_norm,
        version_normalized=version_norm,
        engine_normalized=engine_norm,
        model_tokens=model_norm.significant_tokens(),
        model_core_tokens=model_core,
        model_alnum_anchors=alnum,
        descriptors=descriptors,
        trim_tokens=_trim_tokens(version_norm, model_norm),
        semantic_tokens=semantic,
        commercial_power=_commercial_power(full_norm),
        displacements=_parse_displacements(model_text),
        valves=_parse_valves(full_norm),
        turbo=_parse_turbo(full_norm),
        transmission=transmission,
        transmission_subtype=subtype,
        gears=gears,
        drive=_parse_drive(full_norm),
        body=_parse_body(full_norm),
        fuel=_parse_fuel(consulta.get("combustivel"), model_text),
        propulsion=propulsion,
        year=year,
        model_year=(_parse_model_year(model_text, consulta.get("texto_ano"), consulta.get("ano_modelo")) or year),
        zero_km=zero_km,
        metadata=dict(consulta),
    )


def build_record_identity(record: dict[str, Any]) -> TechnicalIdentity:
    brand = _brand_key(record.get("marca_normalizada") or record.get("marca"))
    model_text = str(record.get("modelo") or "")
    version_text = str(record.get("versao_corrigida") or record.get("versao") or "")
    engine_text = str(record.get("motor_corrigido") or record.get("motor") or "")
    transmission_text = str(record.get("transmissao_normalizada") or record.get("transmissao") or "")
    full_text = " ".join(
        str(record.get(k) or "")
        for k in (
            "marca", "modelo", "versao_corrigida", "versao", "motor_corrigido", "motor",
            "transmissao", "combustivel", "tipo_propulsao", "ano_tabela",
        )
    )
    full_norm = AutomotiveNormalizer.normalize(full_text)
    model_norm = AutomotiveNormalizer.normalize(model_text)
    version_norm = AutomotiveNormalizer.normalize(version_text)
    engine_norm = AutomotiveNormalizer.normalize(engine_text)
    model_core, alnum, descriptors = _model_core_tokens(model_norm, brand)
    semantic = _semantic_tokens(full_norm, brand)
    trans_norm = AutomotiveNormalizer.normalize(transmission_text)
    transmission, subtype, gears = _parse_transmission(
        AutomotiveNormalizer.normalize(f"{full_norm.normalized} {trans_norm.normalized}")
    )
    propulsion = _parse_propulsion(
        record.get("tipo_propulsao_normalizado"), record.get("tipo_propulsao"),
        record.get("combustivel_normalizado"), record.get("combustivel"), full_text,
    )
    # Campos saneados são a fonte de verdade para a propulsão.
    prop_norm = str(record.get("tipo_propulsao_normalizado") or "").upper()
    if prop_norm == "PLUG_IN":
        propulsion = "PHEV"
    elif prop_norm == "ELETRICO":
        propulsion = "BEV"
    elif prop_norm == "HIBRIDO":
        propulsion = "HEV"
    elif prop_norm == "COMBUSTAO":
        propulsion = "ICE"
    year = _parse_year(record.get("ano_tabela"))
    return TechnicalIdentity(
        source="PBEV",
        original=full_text,
        normalized=full_norm,
        brand=brand,
        model_normalized=model_norm,
        version_normalized=version_norm,
        engine_normalized=engine_norm,
        model_tokens=model_norm.significant_tokens(),
        model_core_tokens=model_core,
        model_alnum_anchors=alnum,
        descriptors=descriptors,
        trim_tokens=_trim_tokens(version_norm, model_norm),
        semantic_tokens=semantic,
        commercial_power=_commercial_power(full_norm),
        displacements=_parse_displacements(engine_text, version_text, model_text),
        valves=_parse_valves(AutomotiveNormalizer.normalize(f"{engine_text} {version_text}")),
        turbo=_parse_turbo(AutomotiveNormalizer.normalize(f"{engine_text} {version_text}")),
        transmission=transmission,
        transmission_subtype=subtype,
        gears=gears,
        drive=_parse_drive(full_norm),
        body=_parse_body(model_norm),
        fuel=_parse_fuel(record.get("combustivel_normalizado"), record.get("combustivel"), full_text),
        propulsion=propulsion,
        year=year,
        model_year=_parse_model_year(model_text, version_text, engine_text),
        zero_km=False,
        metadata=record,
    )


def compatible_number_sets(a: Iterable[float | int], b: Iterable[float | int], tolerance: float = 0.0) -> bool | None:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return None
    return any(abs(float(x) - float(y)) <= tolerance for x in sa for y in sb)
