from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

from .models import CandidateScore, TechnicalEvidence, TextViews
from .normalizer import (
    TOKEN_ALIASES,
    build_text_views,
    compute_idf,
    extract_technical_evidence,
    jaccard,
    model_core_tokens,
    overlap_coefficient,
    sequence_ratio,
    token_f1,
)


PROPULSION_CANONICAL = {
    "ELETRICO": "BEV",
    "BEV": "BEV",
    "EV": "BEV",
    "PLUG_IN": "PHEV",
    "PLUGIN": "PHEV",
    "PHEV": "PHEV",
    "HIBRIDO": "HEV",
    "HEV": "HEV",
    "MHEV": "MHEV",
    "COMBUSTAO": "ICE",
    "ICE": "ICE",
}

FUEL_CANONICAL = {
    "F": "FLEX", "FLEX": "FLEX", "ETANOL": "FLEX", "ALCOOL": "FLEX",
    "G": "GASOLINA", "GASOLINA": "GASOLINA",
    "D": "DIESEL", "DIESEL": "DIESEL",
    "E": "ELETRICO", "ELETRICO": "ELETRICO", "ELETRICA": "ELETRICO",
    "HIBRIDO": "HIBRIDO", "HIBRIDA": "HIBRIDO", "HYBRID": "HIBRIDO",
}



class PbevMultiviewMatcher:
    """Matching por evidências multivisão.

    O motor não força cada token FIPE a um slot semântico. Ele preserva versões
    compactas, segmentadas e tokenizadas do mesmo texto, extrai somente fatos
    técnicos de alta confiança e compara essas evidências com os campos já
    estruturados da base PBEV.
    """

    def __init__(self, service: Any):
        self.service = service
        self._cache_signature: tuple[str, float] | None = None
        self._record_cache: dict[str, dict[str, Any]] = {}
        self._idf_by_brand: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Construção das representações
    # ------------------------------------------------------------------
    @staticmethod
    def _record_id(record: dict[str, Any]) -> str:
        return str(record.get("id_pbev_preliminar") or record.get("chave_tecnica_normalizada") or id(record))

    def _query_text(self, query: dict[str, Any]) -> str:
        return " ".join(
            str(query.get(key) or "")
            for key in ("modelo", "texto_modelo", "combustivel", "texto_ano")
        ).strip()

    def _query_model_text(self, query: dict[str, Any]) -> str:
        return str(query.get("modelo") or query.get("texto_modelo") or "").strip()

    @staticmethod
    def _record_model_text(record: dict[str, Any]) -> str:
        return str(record.get("modelo_normalizado") or record.get("modelo") or "")

    @staticmethod
    def _record_version_text(record: dict[str, Any]) -> str:
        return str(
            record.get("versao_normalizada")
            or record.get("versao_corrigida")
            or record.get("versao")
            or ""
        )

    @staticmethod
    def _record_full_text(record: dict[str, Any]) -> str:
        return " ".join(
            str(record.get(key) or "")
            for key in (
                "modelo_normalizado", "modelo", "versao_normalizada", "versao_corrigida", "versao",
                "motor_normalizado", "motor_corrigido", "motor", "transmissao_normalizada", "transmissao",
            )
        ).strip()

    @staticmethod
    def _record_year(record: dict[str, Any]) -> int | None:
        try:
            value = int(record.get("ano_tabela") or 0)
            return value if 2010 <= value <= 2035 else None
        except Exception:
            return None

    @staticmethod
    def _canon_propulsion(value: Any) -> str | None:
        normalized = re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
        return PROPULSION_CANONICAL.get(normalized)

    @staticmethod
    def _canon_fuel(value: Any) -> str | None:
        normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
        return FUEL_CANONICAL.get(normalized)

    def _query_propulsion(self, query: dict[str, Any]) -> str | None:
        prefix = str(query.get("prefixo") or "").lower()
        vehicle_type = str(query.get("tipo_veiculo") or "").lower()
        full = build_text_views(self._query_text(query))
        electric = bool({"ELETRICO", "ELETRICA", "BEV", "EV"} & full.tokens)
        hybrid = bool({"HIBRIDO", "HIBRIDA", "HYBRID", "PHEV", "PLUGIN"} & full.tokens) or "hibr" in vehicle_type
        plugin = bool({"PHEV", "PLUGIN"} & full.tokens)
        if electric:
            return "BEV"
        if prefix == "ve" and hybrid:
            return "PHEV"
        if plugin:
            return "PHEV"
        if hybrid:
            return "HEV"
        return "ICE"

    def _query_fuel(self, query: dict[str, Any], propulsion: str | None) -> str | None:
        if propulsion == "BEV":
            return "ELETRICO"
        direct = self._canon_fuel(query.get("combustivel"))
        if direct and direct != "HIBRIDO":
            return direct
        tokens = build_text_views(self._query_text(query)).tokens
        for token in ("DIESEL", "FLEX", "GASOLINA", "ELETRICO"):
            if token in tokens:
                return self._canon_fuel(token)
        return direct

    def _query_year(self, query: dict[str, Any]) -> tuple[int | None, bool]:
        resolved = self.service.resolver_ano_fipe_para_matching(query)
        year = resolved.get("ano_referencia")
        if year is None:
            try:
                raw = int(query.get("ano") or 0)
                if 2010 <= raw <= 2035:
                    year = raw
            except Exception:
                year = None
        return year, bool(resolved.get("zero_km_contexto"))

    def _prepare_records(self, cache: Any) -> None:
        signature = (cache.path, cache.mtime)
        if signature == self._cache_signature:
            return
        self._record_cache = {}
        by_brand_docs: dict[str, list[set[str]]] = defaultdict(list)
        for record in cache.registros:
            if not isinstance(record, dict):
                continue
            rid = self._record_id(record)
            model_views = build_text_views(self._record_model_text(record))
            version_views = build_text_views(self._record_version_text(record))
            full_views = build_text_views(self._record_full_text(record))
            propulsion = self._canon_propulsion(record.get("tipo_propulsao_normalizado") or record.get("tipo_propulsao"))
            fuel = self._canon_fuel(record.get("combustivel_normalizado") or record.get("combustivel"))
            tech = extract_technical_evidence(
                full_views,
                year=self._record_year(record),
                propulsion=propulsion,
                fuel=fuel,
                infer_natural=True,
            )
            brand = self.service._marca_key(record.get("marca_normalizada") or record.get("marca"))
            self._record_cache[rid] = {
                "model_views": model_views,
                "version_views": version_views,
                "full_views": full_views,
                "model_core": model_core_tokens(model_views),
                "tech": tech,
                "brand": brand,
            }
            by_brand_docs[brand].append(set(full_views.tokens))
        self._idf_by_brand = {brand: compute_idf(docs) for brand, docs in by_brand_docs.items()}
        self._cache_signature = signature

    # ------------------------------------------------------------------
    # Compatibilidade e pontuação
    # ------------------------------------------------------------------
    @staticmethod
    def _allowed_propulsions(query_propulsion: str | None, prefix: str) -> set[str]:
        if query_propulsion == "BEV":
            return {"BEV"}
        if query_propulsion == "PHEV":
            return {"PHEV"}
        if query_propulsion == "HEV":
            return {"HEV", "MHEV"}
        if prefix == "ve":
            return {"BEV", "PHEV"}
        return {"ICE", "HEV", "MHEV"}

    @staticmethod
    def _model_affinity(query_views: TextViews, record_views: TextViews, record_core: frozenset[str]) -> float:
        query_core = model_core_tokens(query_views)
        if not record_core:
            return 0.0
        coverage = len(record_core & query_core) / len(record_core)
        exact_subset = 1.0 if record_core <= query_core else 0.0
        compact_containment = 1.0 if record_views.compact and record_views.compact in query_views.atoms else 0.0
        atom_overlap = overlap_coefficient(record_views.atoms, query_views.atoms)
        char_sim = jaccard(record_views.char_ngrams, query_views.char_ngrams)
        seq = sequence_ratio(record_views.compact, query_views.compact)
        # Cobertura dos tokens do modelo é a evidência principal; similaridade de
        # caracteres atua como resgate, nunca como única prova forte.
        return min(1.0, max(exact_subset, compact_containment, coverage * 0.92 + atom_overlap * 0.08, char_sim * 0.72 + seq * 0.28))

    @staticmethod
    def _version_affinity(query_views: TextViews, version_views: TextViews, idf: dict[str, float]) -> float:
        if not version_views.tokens:
            return 0.0
        # Remove fatos técnicos para que acabamento/designação comercial decidam esta parcela.
        technical_pattern = re.compile(r"^(?:\d\.\d|\d{1,2}V|V\d{1,2}|\d+P|A\d|M\d|CVT\d|DCT\d|DHT\d)$")
        q = {t for t in query_views.tokens if not technical_pattern.fullmatch(t) and t not in TOKEN_ALIASES}
        c = {t for t in version_views.tokens if not technical_pattern.fullmatch(t) and t not in TOKEN_ALIASES}
        if not c:
            return 0.0
        weighted = token_f1(q, c, idf)
        shared = q & c
        candidate_weight = sum(max(0.2, float(idf.get(t, 1.0))) for t in c)
        coverage = (
            sum(max(0.2, float(idf.get(t, 1.0))) for t in shared) / candidate_weight
            if candidate_weight else 0.0
        )
        overlap = overlap_coefficient(q, c)
        atoms = overlap_coefficient(query_views.atoms, version_views.atoms)
        seq = sequence_ratio(query_views.compact, version_views.compact)
        return min(1.0, 0.46 * coverage + 0.24 * weighted + 0.18 * overlap + 0.08 * atoms + 0.04 * seq)

    @staticmethod
    def _technical_compare(query: TechnicalEvidence, record: TechnicalEvidence) -> tuple[float, list[str], list[str], list[str]]:
        score_parts: list[float] = []
        hard: list[str] = []
        penalties: list[str] = []
        reasons: list[str] = []

        if query.displacements and record.displacements:
            best = min(abs(a - b) for a in query.displacements for b in record.displacements)
            if best <= 0.11:
                score_parts.append(1.0)
                reasons.append("cilindrada compatível")
            elif best >= 0.35:
                hard.append("cilindrada explicitamente incompatível")
            else:
                score_parts.append(0.3)
                penalties.append("cilindrada aproximada")
        else:
            score_parts.append(0.5)

        if query.transmission_family and record.transmission_family:
            if query.transmission_family != record.transmission_family:
                hard.append("transmissão manual/automática incompatível")
            else:
                score_parts.append(1.0)
                reasons.append("família de transmissão compatível")
                if query.transmission_subtype and record.transmission_subtype:
                    if query.transmission_subtype == record.transmission_subtype:
                        score_parts.append(1.0)
                    elif {query.transmission_subtype, record.transmission_subtype} <= {"AUTO", "CVT", "DCT", "DHT"}:
                        score_parts.append(0.65)
                        penalties.append("subtipo automático escrito de forma diferente")
        else:
            score_parts.append(0.5)

        if query.valves and record.valves:
            if query.valves & record.valves:
                score_parts.append(1.0)
                reasons.append("válvulas compatíveis")
            else:
                score_parts.append(0.1)
                penalties.append("número de válvulas divergente")
        else:
            score_parts.append(0.5)

        if query.turbo is not None and record.turbo is not None:
            if query.turbo == record.turbo:
                score_parts.append(1.0)
                reasons.append("aspiração compatível")
            elif query.turbo is False and record.turbo is True and query.displacements and query.valves:
                hard.append("motor turbo incompatível com configuração FIPE detalhada sem turbo")
            else:
                score_parts.append(0.1)
                penalties.append("turbo/aspirado divergente")
        else:
            score_parts.append(0.5)

        if query.drives and record.drives:
            if query.drives & record.drives:
                score_parts.append(1.0)
            else:
                score_parts.append(0.15)
                penalties.append("tração divergente")
        else:
            score_parts.append(0.5)

        if query.bodies and record.bodies:
            if query.bodies & record.bodies:
                score_parts.append(1.0)
            else:
                # CROSS é parte da identidade comercial; demais carrocerias podem
                # estar omitidas na FIPE/PBEV e ficam como contradição condicional.
                if "CROSS" in query.bodies or "CROSS" in record.bodies:
                    hard.append("família/carroceria CROSS incompatível")
                else:
                    score_parts.append(0.0)
                    penalties.append("carroceria divergente")
        else:
            score_parts.append(0.5)

        return (sum(score_parts) / max(1, len(score_parts))), hard, penalties, reasons

    @staticmethod
    def _year_affinity(query: TechnicalEvidence, record: TechnicalEvidence, record_views: TextViews) -> tuple[float, list[str]]:
        penalties: list[str] = []
        if query.year and record.year:
            diff = abs(query.year - record.year)
            if diff == 0:
                affinity = 1.0
            elif diff == 1:
                affinity = 0.72
            elif query.zero_km and record.year <= query.year and diff <= 3:
                affinity = 0.45
            else:
                affinity = max(0.0, 0.35 - diff * 0.08)
                penalties.append(f"ano distante ({query.year} x {record.year})")
        elif query.zero_km and record.year:
            affinity = 0.65
        else:
            affinity = 0.5

        # Um MY explicitamente posterior no candidato não é equivalente ao ano da
        # consulta quando o próprio nome FIPE não informa esse MY.
        if record.model_years and not query.model_years:
            if query.year and any(my > query.year for my in record.model_years):
                affinity *= 0.20
                penalties.append("candidato pertence a MY posterior não informado na FIPE")
        elif query.model_years and record.model_years and not (query.model_years & record.model_years):
            affinity *= 0.15
            penalties.append("MY explicitamente incompatível")
        return affinity, penalties

    def _score_candidate(
        self,
        record: dict[str, Any],
        *,
        query_views: TextViews,
        query_model_views: TextViews,
        query_tech: TechnicalEvidence,
        allowed_propulsions: set[str],
        brand_idf: dict[str, float],
    ) -> CandidateScore:
        cached = self._record_cache[self._record_id(record)]
        model_views: TextViews = cached["model_views"]
        version_views: TextViews = cached["version_views"]
        full_views: TextViews = cached["full_views"]
        record_tech: TechnicalEvidence = cached["tech"]

        hard: list[str] = []
        penalties: list[str] = []
        reasons: list[str] = []

        if record_tech.propulsion not in allowed_propulsions:
            hard.append(f"propulsão {record_tech.propulsion or 'desconhecida'} incompatível com o lado da consulta")

        # Combustível só veta quando não estamos comparando híbridos/PHEV, pois a
        # PBEV registra o combustível térmico como gasolina nesses veículos.
        if query_tech.propulsion in {"ICE", "BEV"} and query_tech.fuel and record_tech.fuel:
            if query_tech.fuel != record_tech.fuel:
                hard.append(f"combustível incompatível ({query_tech.fuel} x {record_tech.fuel})")

        model_affinity = self._model_affinity(query_model_views, model_views, cached["model_core"])
        if model_affinity < 0.48:
            hard.append("identidade de modelo insuficiente")
        elif model_affinity >= 0.90:
            reasons.append("modelo/família presente de forma inequívoca")

        version_affinity = self._version_affinity(query_views, version_views, brand_idf)
        text_affinity = (
            0.45 * token_f1(query_views.tokens, full_views.tokens, brand_idf)
            + 0.30 * jaccard(query_views.char_ngrams, full_views.char_ngrams)
            + 0.15 * overlap_coefficient(query_views.atoms, full_views.atoms)
            + 0.10 * sequence_ratio(query_views.compact, full_views.compact)
        )

        technical_affinity, tech_hard, tech_penalties, tech_reasons = self._technical_compare(query_tech, record_tech)
        hard.extend(tech_hard)
        penalties.extend(tech_penalties)
        reasons.extend(tech_reasons)

        year_affinity, year_penalties = self._year_affinity(query_tech, record_tech, model_views)
        penalties.extend(year_penalties)

        flags_ok, flag_blocks = self.service.validar_flags_autofill(record)
        suggestion = self.service.montar_sugestao_consumo(record)

        # Score explicável. Modelo e técnica dominam; texto bruto não consegue
        # compensar uma identidade errada.
        score = 100.0 * (
            0.43 * model_affinity
            + 0.20 * version_affinity
            + 0.09 * text_affinity
            + 0.18 * technical_affinity
            + 0.10 * year_affinity
        )
        if query_tech.year and record_tech.year == query_tech.year and model_affinity >= 0.90:
            score += 8.0
            reasons.append("ciclo PBEV do ano-modelo exato priorizado")
        if query_tech.zero_km and query_tech.year and record_tech.year == query_tech.year:
            score += 4.0
            reasons.append("zero km: ciclo PBEV do ano-modelo priorizado")
        score -= min(18.0, 3.0 * len(penalties))
        if hard:
            score = min(score, 34.0)
        if not flags_ok:
            score = min(score, 45.0)
        if not suggestion:
            score = min(score, 49.0)

        return CandidateScore(
            record=record,
            score=max(0.0, score),
            model_affinity=model_affinity,
            version_affinity=version_affinity,
            text_affinity=text_affinity,
            technical_affinity=technical_affinity,
            year_affinity=year_affinity,
            hard_blocks=hard,
            penalties=penalties,
            reasons=reasons,
            query_views=query_views,
            record_views=full_views,
            query_tech=query_tech,
            record_tech=record_tech,
            suggestion=suggestion,
            flags_ok=flags_ok,
            flag_blocks=flag_blocks,
        )

    # ------------------------------------------------------------------
    # Equivalência, decisão e resposta
    # ------------------------------------------------------------------
    @staticmethod
    def _suggestion_signature(suggestion: dict[str, Any] | None) -> tuple[Any, ...]:
        if not suggestion:
            return tuple()
        keys = (
            "tipo", "gasolina_cidade_km_l", "gasolina_estrada_km_l",
            "gasolina_diesel_cidade_km_l", "gasolina_diesel_estrada_km_l",
            "etanol_cidade_km_l", "etanol_estrada_km_l",
            "consumo_eletrico_kwh_km", "eficiencia_eletrica_km_kwh",
        )
        return tuple(suggestion.get(k) for k in keys)

    @staticmethod
    def _technical_signature(candidate: CandidateScore, *, include_body: bool = False) -> tuple[Any, ...]:
        tech = candidate.record_tech or TechnicalEvidence()
        body = tuple(sorted(tech.bodies)) if include_body else tuple()
        return (
            tech.propulsion, tech.fuel, tuple(sorted(tech.displacements)), tuple(sorted(tech.valves)),
            tech.turbo, tech.transmission_family, tech.transmission_subtype, tech.gears,
            tuple(sorted(tech.drives)), body,
        )

    def _equivalent_group(self, top: CandidateScore, ranked: list[CandidateScore]) -> list[CandidateScore]:
        query_has_body = bool((top.query_tech or TechnicalEvidence()).bodies)
        signature = self._technical_signature(top, include_body=query_has_body)
        group = []
        for candidate in ranked:
            if not candidate.usable:
                continue
            if candidate.score < top.score - 12.0:
                continue
            if candidate.year_affinity < max(0.40, top.year_affinity - 0.02):
                continue
            if any("MY" in penalty for penalty in candidate.penalties):
                continue
            if self._technical_signature(candidate, include_body=query_has_body) == signature:
                group.append(candidate)
        return group

    @staticmethod
    def _conservative_candidate(group: list[CandidateScore]) -> CandidateScore | None:
        if not group:
            return None
        kind = str((group[0].suggestion or {}).get("tipo") or "")
        if kind in {"eletrico", "phev"}:
            return max(group, key=lambda c: float((c.suggestion or {}).get("consumo_eletrico_kwh_km") or -1))
        def city_consumption(c: CandidateScore) -> float:
            suggestion = c.suggestion or {}
            values = [
                suggestion.get("gasolina_cidade_km_l"),
                suggestion.get("gasolina_diesel_cidade_km_l"),
            ]
            numeric = [float(v) for v in values if v is not None]
            return min(numeric) if numeric else 10**9
        return min(group, key=city_consumption)

    @staticmethod
    def _candidate_debug(candidate: CandidateScore, position: int) -> dict[str, Any]:
        record = candidate.record
        return {
            "posicao": position,
            "id_pbev": record.get("id_pbev_preliminar"),
            "ano_tabela": record.get("ano_tabela"),
            "marca": record.get("marca"),
            "modelo": record.get("modelo"),
            "versao": record.get("versao_corrigida") or record.get("versao"),
            "motor": record.get("motor_corrigido") or record.get("motor"),
            "transmissao": record.get("transmissao"),
            "propulsao": record.get("tipo_propulsao_normalizado"),
            "score": round(candidate.score, 3),
            "evidencias": {
                "modelo": round(candidate.model_affinity, 4),
                "versao": round(candidate.version_affinity, 4),
                "texto": round(candidate.text_affinity, 4),
                "tecnica": round(candidate.technical_affinity, 4),
                "ano": round(candidate.year_affinity, 4),
            },
            "bloqueios": list(candidate.hard_blocks) + list(candidate.flag_blocks),
            "penalidades": list(candidate.penalties),
            "motivos": list(candidate.reasons),
            "tem_consumo": bool(candidate.suggestion),
        }

    def _empty_response(self, *, reason: str, debug: dict[str, Any], protected: bool = False) -> dict[str, Any]:
        response = {
            "encontrou": False,
            "nivel_match": "sem_match",
            "score": 0,
            "score_bruto": 0,
            "motivo": reason,
            "autopreencher": False,
            "criterio_match": "sem_match",
            "cobertura_pbev": "ausente",
            "origem": "Inmetro/PBEV",
            "ano_tabela_pbev": None,
            "candidato": None,
            "sugestoes_consumo": {},
            "flags": {},
            "fonte_oficial": {},
            "motivo_decisao": [],
            "motivo_nao_preenchimento": [reason],
            "candidatos_equivalentes": [],
            "diagnostico": {
                "motor_matching": "v46_multivisao",
                "decisao_protegida_sem_match": protected,
                "dominante": False,
                "ambiguidade_proxima": False,
                "identidade_tecnica_forte": False,
                "tecnica_suficiente_para_consumo": False,
                "tokens_fortes_fipe": [],
            },
            "valor_autopreenchido": False,
            "motor_matching": "v46_multivisao",
            "debug": debug,
        }
        response["diagnostico_terminal"] = self._terminal(debug, response)
        return response

    @staticmethod
    def _terminal(debug: dict[str, Any], response: dict[str, Any]) -> str:
        lines = [
            "CurVE · Matching FIPE × PBEV · Motor multivisão V46",
            f"Decisão: {response.get('nivel_match')} | autofill={response.get('autopreencher')} | score={response.get('score')}",
            f"Motivo: {response.get('motivo')}",
            "Candidatos:",
        ]
        for item in (debug.get("candidatos_top") or [])[:8]:
            lines.append(
                f"#{item.get('posicao')} {item.get('marca')} {item.get('modelo')} {item.get('versao')} "
                f"({item.get('ano_tabela')}) score={item.get('score')} "
                f"bloqueios={','.join(item.get('bloqueios') or []) or '-'}"
            )
        return "\n".join(lines)

    def suggest(self, query: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        cache = self.service.carregar_base_pbev()
        self._prepare_records(cache)

        query_views = build_text_views(self._query_text(query))
        query_model_views = build_text_views(self._query_model_text(query))
        propulsion = self._query_propulsion(query)
        fuel = self._query_fuel(query, propulsion)
        year, zero_km = self._query_year(query)
        query_tech = extract_technical_evidence(
            query_views,
            year=year,
            zero_km=zero_km,
            propulsion=propulsion,
            fuel=fuel,
            infer_natural=propulsion in {"ICE", "HEV", "MHEV"},
        )

        brand_key = self.service._marca_key(query.get("marca"))
        brand_keys = self.service._marca_keys_busca(query)
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key in brand_keys or [brand_key]:
            for record in cache.indice_marca.get(key, []):
                rid = self._record_id(record)
                if rid not in seen:
                    seen.add(rid)
                    records.append(record)

        debug: dict[str, Any] = {
            "entrada_fipe": dict(query),
            "normalizacao": {
                "texto_canonico": query_views.canonical,
                "texto_segmentado": query_views.segmented,
                "texto_compacto": query_views.compact,
                "tokens": sorted(query_views.tokens),
                "atomos": sorted(query_views.atoms),
                "modelo_canonico": query_model_views.canonical,
                "propulsao_consulta": propulsion,
                "combustivel_consulta": fuel,
                "ano_consulta": year,
                "zero_km": zero_km,
            },
            "filtros": {
                "registros_base": len(cache.registros),
                "registros_marca": len(records),
                "marcas_indexadas": len(cache.indice_marca),
                "motor": "v46_multivisao",
            },
            "candidatos_top": [],
        }

        if not brand_key or not records:
            return self._empty_response(reason="Marca FIPE ausente ou sem registros PBEV.", debug=debug)

        allowed = self._allowed_propulsions(propulsion, str(query.get("prefixo") or "").lower())
        idf = self._idf_by_brand.get(brand_key, {})
        ranked = [
            self._score_candidate(
                record,
                query_views=query_views,
                query_model_views=query_model_views,
                query_tech=query_tech,
                allowed_propulsions=allowed,
                brand_idf=idf,
            )
            for record in records
        ]
        ranked.sort(
            key=lambda c: (
                1 if c.usable else 0,
                c.score,
                c.model_affinity,
                c.version_affinity,
                c.year_affinity,
                self._record_year(c.record) or 0,
            ),
            reverse=True,
        )
        debug["candidatos_top"] = [self._candidate_debug(c, i + 1) for i, c in enumerate(ranked[:12])]
        debug["filtros"]["tempo_ms"] = round((time.perf_counter() - started) * 1000, 3)
        debug["filtros"]["candidatos_utilizaveis"] = sum(1 for c in ranked if c.usable)
        debug["filtros"]["candidatos_bloqueados"] = sum(1 for c in ranked if c.hard_blocks or not c.flags_ok)

        usable = [c for c in ranked if c.usable]
        if not usable:
            best_model = max((c.model_affinity for c in ranked), default=0.0)
            protected = best_model < 0.48
            reason = "Nenhum candidato PBEV passou os bloqueios técnicos e de identidade."
            return self._empty_response(reason=reason, debug=debug, protected=protected)

        top = usable[0]
        second = usable[1] if len(usable) > 1 else None
        margin = top.score - second.score if second else top.score
        group = self._equivalent_group(top, usable)
        signatures = {self._suggestion_signature(c.suggestion) for c in group}
        same_consumption = len(group) > 1 and len(signatures) == 1
        conservative = None
        conservative_used = False

        # Critério conservador apenas para candidatos tecnicamente equivalentes e
        # sem carroceria explícita na FIPE. Não resolve conflito de família/MY.
        version_scores = sorted((c.version_affinity for c in group), reverse=True)
        version_margin = version_scores[0] - version_scores[1] if len(version_scores) > 1 else version_scores[0] if version_scores else 0.0
        decisive_version = top.version_affinity >= 0.52 and version_margin >= 0.10
        if len(group) > 1 and len(signatures) > 1 and not query_tech.bodies and not decisive_version:
            conservative = self._conservative_candidate(group)
            if conservative and top.model_affinity >= 0.90 and top.technical_affinity >= 0.68:
                top = conservative
                conservative_used = True

        strong_identity = top.model_affinity >= 0.86
        sufficient_tech = top.technical_affinity >= 0.48 and not top.hard_blocks
        dominant = margin >= 5.0 or same_consumption or conservative_used
        exact_family_year = [
            c for c in usable
            if c.model_affinity >= 0.94 and c.year_affinity >= 0.99 and c.record_tech and c.record_tech.propulsion == top.record_tech.propulsion
        ]
        unique_family_configuration = len(exact_family_year) == 1 and exact_family_year[0] is top
        high = bool(
            strong_identity
            and sufficient_tech
            and (
                (top.score >= 60.0 and decisive_version)
                or (top.score >= 58.0 and same_consumption)
                or (top.score >= 62.0 and conservative_used)
                or (top.score >= 62.0 and unique_family_configuration)
                or (top.score >= 66.0 and dominant)
            )
        )

        if high:
            level, autofill = "alto", True
        elif top.score >= 55.0:
            level, autofill = "medio", False
        elif top.score >= 44.0:
            level, autofill = "baixo", False
        else:
            return self._empty_response(
                reason="Candidato localizado, mas sem evidência suficiente para uma correspondência defensável.",
                debug=debug,
                protected=top.model_affinity < 0.55,
            )

        family_only_conservative = bool(
            high
            and unique_family_configuration
            and top.model_affinity >= 0.94
            and top.version_affinity < 0.10
        )
        if not high:
            criterion = "aproximacao_com_observacao"
        elif conservative_used or family_only_conservative:
            criterion = "conservador_por_familia"
        elif same_consumption:
            criterion = "versoes_equivalentes"
        elif top.year_affinity < 0.99:
            criterion = "ano_modelo_adjacente"
        else:
            criterion = "exato"

        reasons = list(top.reasons)
        if same_consumption:
            reasons.append("candidatos tecnicamente equivalentes possuem o mesmo consumo")
        if conservative_used:
            reasons.append("configurações tecnicamente equivalentes resolvidas pelo critério conservador autorizado")
        if family_only_conservative:
            reasons.append("família técnica compatível, mas acabamento específico ausente na PBEV")
        if dominant:
            reasons.append("candidato dominante sobre o segundo colocado")
        nonfill = [] if autofill else list(top.penalties) + ["confiança insuficiente para autofill"]
        record = top.record
        public_candidate = self.service._candidato_publico(record)
        suggestion = dict(top.suggestion or {})
        if conservative_used or family_only_conservative:
            suggestion.setdefault("criterio_conservador_versoes_compativeis", True)
            suggestion.setdefault(
                "criterio_conservador_descricao",
                (
                    "Configurações PBEV tecnicamente equivalentes resolvidas pelo consumo conservador autorizado."
                    if conservative_used
                    else "Família técnica compatível; acabamento específico não consta na PBEV e foi mantida observação conservadora."
                ),
            )
            suggestion.setdefault(
                "versoes_pbev_consideradas",
                [
                    " ".join(str(c.record.get(k) or "") for k in ("modelo", "versao_corrigida", "ano_tabela")).strip()
                    for c in (group or [top])
                ],
            )

        score_public = round(min(100.0, top.score + (8.0 if high else 0.0)), 2)
        response = {
            "encontrou": True,
            "nivel_match": level,
            "score": score_public if level == "alto" else min(score_public, 89.0 if level == "medio" else 69.0),
            "score_bruto": round(top.score, 2),
            "motivo": "; ".join(reasons + nonfill) or "Matching multivisão avaliado.",
            "autopreencher": autofill,
            "criterio_match": criterion,
            "cobertura_pbev": "exata" if criterion in {"exato", "versoes_equivalentes"} else "familia",
            "origem": "Inmetro/PBEV",
            "ano_tabela_pbev": record.get("ano_tabela"),
            "candidato": public_candidate,
            "sugestoes_consumo": suggestion,
            "flags": self.service._flags_publicas(record),
            "fonte_oficial": self.service._fonte_oficial_por_ano(record.get("ano_tabela")),
            "motivo_decisao": reasons,
            "motivo_nao_preenchimento": nonfill,
            "candidatos_equivalentes": [self.service._candidato_publico(c.record) for c in group],
            "diagnostico": {
                "motor_matching": "v46_multivisao",
                "score_segundo_candidato": round(second.score, 2) if second else None,
                "diferenca_para_segundo": round(margin, 2) if second else None,
                "dominante": dominant,
                "candidatos_considerados": len(records),
                "candidatos_utilizaveis": len(usable),
                "candidatos_bloqueados": debug["filtros"]["candidatos_bloqueados"],
                "ano_exato": top.year_affinity >= 0.99,
                "ano_diff": abs((query_tech.year or 0) - (top.record_tech.year or 0)) if query_tech.year and top.record_tech and top.record_tech.year else None,
                "ano_relacao": "exato" if top.year_affinity >= 0.99 else "aproximado",
                "ano_compativel_fipe_pbev": top.year_affinity >= 0.45,
                "zero_km_contexto": zero_km,
                "identidade_tecnica_forte": strong_identity and sufficient_tech,
                "tecnica_suficiente_para_consumo": sufficient_tech,
                "ambiguidade_proxima": not dominant,
                "ambiguidade_resolvida_por_consumo": same_consumption,
                "ambiguidade_resolvida_por_criterio_conservador": conservative_used,
                "modelo_score": round(top.model_affinity * 40.0, 2),
                "combustivel_detectado_fipe": (
                    "PLUG_IN" if query_tech.propulsion == "PHEV"
                    else (query_tech.fuel or query_tech.propulsion)
                ),
                "tokens_fortes_fipe": sorted(a for a in query_model_views.atoms if 2 <= len(a) <= 16)[:80],
                "evidencias_multivisao": {
                    "modelo": round(top.model_affinity, 4),
                    "versao": round(top.version_affinity, 4),
                    "texto": round(top.text_affinity, 4),
                    "tecnica": round(top.technical_affinity, 4),
                    "ano": round(top.year_affinity, 4),
                },
                "tempo_ms": debug["filtros"]["tempo_ms"],
                "decisao_protegida_sem_match": False,
                "configuracao_familia_unica_no_ano": unique_family_configuration,
            },
            "valor_autopreenchido": autofill,
            "motor_matching": "v46_multivisao",
            "debug": debug,
        }
        response["diagnostico_terminal"] = self._terminal(debug, response)
        return response
