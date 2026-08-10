from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from services.pbev_matching_v46.normalizer import (
    build_text_views,
    jaccard,
    model_core_tokens,
    overlap_coefficient,
    sequence_ratio,
)
from services.pbev_service import PbevService
from services.tipo_veiculo_service import normalizar_texto


CONTEXT_VE = "ve"
CONTEXT_ICEV = "icev"

_PROP_CONTEXT = {
    "ELETRICO": CONTEXT_VE,
    "BEV": CONTEXT_VE,
    "PLUG_IN": CONTEXT_VE,
    "PHEV": CONTEXT_VE,
    "HIBRIDO": CONTEXT_ICEV,
    "HEV": CONTEXT_ICEV,
    "MHEV": CONTEXT_ICEV,
    "COMBUSTAO": CONTEXT_ICEV,
    "ICE": CONTEXT_ICEV,
}

_PLUGIN_PATTERNS = (
    r"\bPHEV(?:\s*[-/]?\s*\d{1,4})?\b", r"\bPLUG\s*IN\b", r"\bPLUGIN\b", r"\bDM\s*I\b", r"\bDMI\b",
    r"\bE\s*HYBRID\b", r"\bTFSI\s*E\b", r"\bRECHARGE\b", r"\b(?:XDRIVE|SDRIVE)?\s*\d{2,3}E\b", r"\bT8\b",
)
_ELECTRIC_PATTERNS = (
    r"\bELETRIC[OA]\b", r"\bELECTRIC\b", r"\bBEV\b", r"\bEV\b", r"\bE\s*TRON\b",
    r"\bETRON\b", r"\bZERO\s+EMISSAO\b", r"\bE\s*\d{3,4}\b",
)
_HEV_PATTERNS = (
    r"\bMHEV\b", r"\bMILD\s+HYBRID\b", r"\bHEV(?:\s*[-/]?\s*\d{1,3})?\b", r"\bE\s*HEV\b",
)
_HYBRID_GENERIC_PATTERNS = (r"\bHIBRID[OA]\b", r"\bHYBRID\b")
_COMBUSTION_FUEL_PATTERNS = (
    r"\bDIESEL\b", r"\bFLEX\b", r"\bGASOLINA\b", r"\bETANOL\b", r"\bALCOOL\b",
)


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _record_year(record: dict[str, Any]) -> int | None:
    for key in ("ano_tabela", "ano", "ano_modelo"):
        try:
            value = int(float(record.get(key)))
            if 2010 <= value <= 2035:
                return value
        except (TypeError, ValueError):
            pass
    return None


def _record_propulsion(record: dict[str, Any]) -> str:
    value = str(record.get("tipo_propulsao_normalizado") or record.get("tipo_propulsao") or "").strip().upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value).strip("_")
    return value


@dataclass(frozen=True)
class CatalogPropulsionDecision:
    contexts: frozenset[str]
    tipo_plugve: str
    source: str
    confidence: float
    top_score: float = 0.0
    margin: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "contextos": sorted(self.contexts),
            "tipo_plugve": self.tipo_plugve,
            "origem_classificacao": self.source,
            "confianca_classificacao": round(float(self.confidence), 4),
            "score_pbev": round(float(self.top_score), 4),
            "margem_pbev": round(float(self.margin), 4),
        }


class FipeCatalogPropulsionClassifier:
    """Classifica a elegibilidade VE/ICEV usando texto FIPE + base local PBEV.

    O catálogo não usa o lado da tela para inventar a propulsão. Evidência explícita
    no nome/combustível vence; nos nomes comerciais sem indicação, a base PBEV local
    atua como índice de identidade. Híbrido genérico só vira PHEV com evidência PBEV
    dominante; em ambiguidade, permanece HEV/ICEV por segurança.
    """

    _lock = threading.RLock()

    def __init__(self, pbev_service: PbevService | None = None):
        self.pbev_service = pbev_service or PbevService()
        self._signature: tuple[str, float] | None = None
        self._brand_contexts: dict[str, frozenset[str]] = {}
        self._brand_records: dict[str, list[dict[str, Any]]] = {}
        self._prepared_by_brand: dict[str, list[dict[str, Any]]] = {}
        self._decision_cache: dict[tuple[str, str, int | None, str], CatalogPropulsionDecision] = {}

    def _ensure_index(self) -> None:
        cache = self.pbev_service.carregar_base_pbev()
        signature = (cache.path, cache.mtime)
        with self._lock:
            if signature == self._signature:
                return
            self._brand_records = {str(k): list(v) for k, v in cache.indice_marca.items()}
            contexts: dict[str, set[str]] = {}
            for brand, records in self._brand_records.items():
                bucket = contexts.setdefault(brand, set())
                for record in records:
                    context = _PROP_CONTEXT.get(_record_propulsion(record))
                    if context:
                        bucket.add(context)
            self._brand_contexts = {key: frozenset(value) for key, value in contexts.items()}
            self._prepared_by_brand = {}
            self._decision_cache = {}
            self._signature = signature

    def brand_contexts(self, brand: Any) -> frozenset[str]:
        self._ensure_index()
        key = self.pbev_service._marca_key(brand)
        return self._brand_contexts.get(key, frozenset())

    def model_evidence(self, brand: Any, model: Any, *, year: int | None = None) -> dict[str, Any]:
        contexts, score, margin, propulsion = self._pbev_evidence(brand, str(model or ""), year)
        return {
            "contexts": sorted(contexts),
            "score": float(score),
            "margin": float(margin),
            "propulsion": propulsion,
            "found": bool(score >= 0.70),
        }

    def _prepared_records(self, brand: Any) -> list[dict[str, Any]]:
        self._ensure_index()
        key = self.pbev_service._marca_key(brand)
        with self._lock:
            cached = self._prepared_by_brand.get(key)
            if cached is not None:
                return cached

        prepared: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int | None]] = set()
        for record in self._brand_records.get(key, []):
            prop = _record_propulsion(record)
            context = _PROP_CONTEXT.get(prop)
            if not context:
                continue
            year = _record_year(record)
            model = str(record.get("modelo_normalizado") or record.get("modelo") or "").strip()
            version = str(record.get("versao_normalizada") or record.get("versao") or "").strip()
            motor = str(record.get("motor_normalizado") or record.get("motor") or "").strip()
            transmission = str(record.get("transmissao_normalizada") or record.get("transmissao") or "").strip()
            identity = f"{model} {version} {motor} {transmission}".strip()
            dedup_key = (identity, prop, year)
            if not identity or dedup_key in seen:
                continue
            seen.add(dedup_key)
            model_views = build_text_views(model)
            full_views = build_text_views(identity)
            prepared.append({
                "context": context,
                "propulsion": prop,
                "year": year,
                "model_views": model_views,
                "full_views": full_views,
                "model_core": model_core_tokens(model_views),
                "full_core": model_core_tokens(full_views),
            })

        with self._lock:
            self._prepared_by_brand[key] = prepared
        return prepared

    @staticmethod
    def _similarity(query: str, prepared: dict[str, Any]) -> float:
        query_views = build_text_views(query)
        query_core = model_core_tokens(query_views)
        model_core = prepared["model_core"]
        full_core = prepared["full_core"]
        model_views = prepared["model_views"]
        full_views = prepared["full_views"]

        model_coverage = len(model_core & query_core) / max(1, len(model_core)) if model_core else 0.0
        query_coverage = len(model_core & query_core) / max(1, len(query_core)) if query_core else 0.0
        exact_model = 1.0 if model_core and model_core <= query_core else 0.0
        compact_model = 1.0 if model_views.compact and model_views.compact in query_views.atoms else 0.0
        core_overlap = overlap_coefficient(query_core, model_core)
        atom_overlap = overlap_coefficient(query_views.atoms, full_views.atoms)
        chars = jaccard(query_views.char_ngrams, full_views.char_ngrams)
        sequence = sequence_ratio(query_views.compact, full_views.compact)
        full_overlap = overlap_coefficient(query_core, full_core)

        model_identity = max(
            exact_model,
            compact_model,
            0.78 * model_coverage + 0.22 * query_coverage,
            0.72 * core_overlap + 0.28 * sequence_ratio(query_views.compact, model_views.compact),
        )
        residual = 0.36 * full_overlap + 0.24 * atom_overlap + 0.24 * chars + 0.16 * sequence
        return min(1.0, 0.76 * model_identity + 0.24 * residual)

    def _pbev_evidence(self, brand: Any, model: str, year: int | None) -> tuple[set[str], float, float, str]:
        ranked: list[tuple[float, str, str]] = []
        for prepared in self._prepared_records(brand):
            record_year = prepared.get("year")
            if year is not None and record_year is not None:
                diff = abs(int(record_year) - int(year))
                if diff > 1:
                    continue
            score = self._similarity(model, prepared)
            if year is not None and record_year is not None:
                score += 0.035 if record_year == year else 0.005
            ranked.append((min(1.0, score), str(prepared["context"]), str(prepared["propulsion"])))

        if not ranked:
            return set(), 0.0, 0.0, ""
        ranked.sort(key=lambda item: item[0], reverse=True)
        top_score = ranked[0][0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        threshold = max(0.70, top_score - 0.045)
        contexts = {context for score, context, _propulsion in ranked if score >= threshold}
        # Margem relevante é contra o melhor candidato de propulsão oposta.
        top_context = ranked[0][1]
        top_propulsion = ranked[0][2]
        opposite_scores = [score for score, context, _propulsion in ranked if context != top_context]
        opposite_best = max(opposite_scores) if opposite_scores else 0.0
        margin = top_score - opposite_best
        return contexts, top_score, margin, top_propulsion

    @staticmethod
    def _tipo_for_contexts(contexts: set[str] | frozenset[str], *, plugin: bool = False, electric: bool = False, hybrid: bool = False) -> str:
        if electric:
            return "EV_PURO"
        if plugin:
            return "PHEV"
        if contexts == {CONTEXT_VE}:
            return "PHEV" if hybrid else "EV_PURO"
        if contexts == {CONTEXT_ICEV}:
            return "HEV_NAO_PLUGIN" if hybrid else "COMBUSTAO"
        if CONTEXT_VE in contexts and CONTEXT_ICEV in contexts:
            return "MISTO"
        return "INDEFINIDO"

    def classify(self, brand: Any, model: Any, *, year: int | None = None, fuel: Any = "") -> CatalogPropulsionDecision:
        brand_text = str(brand or "").strip()
        model_text = str(model or "").strip()
        fuel_text = str(fuel or "").strip()
        brand_key = self.pbev_service._marca_key(brand_text)
        cache_key = (brand_key, normalizar_texto(model_text), year, normalizar_texto(fuel_text))
        with self._lock:
            cached = self._decision_cache.get(cache_key)
            if cached is not None:
                return cached

        normalized = normalizar_texto(f"{model_text} {fuel_text}")
        plugin = _has_any(normalized, _PLUGIN_PATTERNS)
        electric = _has_any(normalized, _ELECTRIC_PATTERNS)
        hev_explicit = _has_any(normalized, _HEV_PATTERNS)
        hybrid_generic = _has_any(normalized, _HYBRID_GENERIC_PATTERNS)
        combustion_fuel = _has_any(normalized, _COMBUSTION_FUEL_PATTERNS)

        if plugin:
            decision = CatalogPropulsionDecision(frozenset({CONTEXT_VE}), "PHEV", "fipe_explicito_plugin", 1.0)
        elif electric:
            decision = CatalogPropulsionDecision(frozenset({CONTEXT_VE}), "EV_PURO", "fipe_explicito_eletrico", 1.0)
        elif hev_explicit:
            decision = CatalogPropulsionDecision(frozenset({CONTEXT_ICEV}), "HEV_NAO_PLUGIN", "fipe_explicito_hev", 1.0)
        elif combustion_fuel and not hybrid_generic:
            decision = CatalogPropulsionDecision(frozenset({CONTEXT_ICEV}), "COMBUSTAO", "fipe_combustivel_combustao", 0.98)
        else:
            contexts, top_score, margin, top_propulsion = self._pbev_evidence(brand_text, model_text, year)
            strong = top_score >= 0.74

            if hybrid_generic:
                # O texto FIPE frequentemente informa apenas "Híbrido" mesmo quando
                # a versão é plug-in. Em famílias que possuem HEV e PHEV, a melhor
                # identidade PBEV pode ficar acompanhada por candidatos próximos da
                # outra propulsão. Nesses casos usamos a propulsão do melhor candidato
                # somente quando ela é plug-in e ainda mantém margem mínima real.
                # Isso resolve versões comerciais distintivas (ex.: GT/PHEV19/PHEV35)
                # sem converter um HEV genérico em PHEV pelo lado da interface.
                plugin_pbev_dominante = (
                    strong
                    and top_propulsion in {"PLUG_IN", "PHEV"}
                    and margin >= 0.030
                )
                if plugin_pbev_dominante:
                    decision = CatalogPropulsionDecision(
                        frozenset({CONTEXT_VE}), "PHEV", "pbev_plugin_top_dominante", min(0.97, top_score), top_score, margin
                    )
                else:
                    decision = CatalogPropulsionDecision(
                        frozenset({CONTEXT_ICEV}), "HEV_NAO_PLUGIN", "hibrido_generico_conservador", max(0.75, top_score), top_score, margin
                    )
            elif strong and contexts == {CONTEXT_VE}:
                decision = CatalogPropulsionDecision(
                    frozenset({CONTEXT_VE}),
                    "PHEV" if top_propulsion in {"PHEV", "PLUG_IN"} else "EV_PURO",
                    "pbev_eletrico_plugin",
                    min(0.96, top_score),
                    top_score,
                    margin,
                )
            elif strong and contexts == {CONTEXT_ICEV}:
                decision = CatalogPropulsionDecision(
                    frozenset({CONTEXT_ICEV}), "COMBUSTAO", "pbev_combustao_hev", min(0.94, top_score), top_score, margin
                )
            elif strong and contexts == {CONTEXT_VE, CONTEXT_ICEV}:
                # Uma família com configurações HEV e PHEV pode aparecer nos dois
                # blocos; os anos serão filtrados novamente com ano/combustível.
                decision = CatalogPropulsionDecision(
                    frozenset({CONTEXT_VE, CONTEXT_ICEV}), "MISTO", "pbev_familia_mista", min(0.88, top_score), top_score, margin
                )
            else:
                decision = CatalogPropulsionDecision(
                    frozenset({CONTEXT_ICEV}), "COMBUSTAO", "fallback_conservador_combustao", 0.62, top_score, margin
                )

        with self._lock:
            self._decision_cache[cache_key] = decision
        return decision
