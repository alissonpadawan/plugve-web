from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from rapidfuzz import fuzz

from .identity import TechnicalIdentity, build_query_identity, build_record_identity, compatible_number_sets
from .normalizer import AutomotiveNormalizer


@dataclass
class RankedCandidate:
    record: dict[str, Any]
    identity: TechnicalIdentity
    score: float
    public_score: float
    model_score: float
    lexical_score: float
    technical_score: float
    year_score: float
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    hard_blocks: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    suggestion: dict[str, Any] | None = None
    flags_ok: bool = True
    flag_blocks: list[str] = field(default_factory=list)
    retrieval_score: float = 0.0

    @property
    def usable(self) -> bool:
        return self.flags_ok and bool(self.suggestion) and not self.hard_blocks


@dataclass
class V2RankingResult:
    query: TechnicalIdentity
    ranked: list[RankedCandidate]
    all_evaluated: list[RankedCandidate]
    counts: dict[str, Any]


class PbevMatcherV2:
    """Matcher híbrido determinístico.

    A recuperação é ampla dentro da marca. A similaridade lexical ajuda a ordenar,
    mas nunca sobrepõe bloqueios técnicos explícitos. O cache de identidades evita
    reprocessar a base PBEV em cada consulta.
    """

    _identity_lock = threading.RLock()
    _identity_cache: dict[str, TechnicalIdentity] = {}
    _static_lock = threading.RLock()
    _static_cache: dict[str, tuple[dict[str, Any] | None, bool, list[str]]] = {}

    def __init__(
        self,
        records: Iterable[dict[str, Any]],
        *,
        suggestion_builder: Callable[[dict[str, Any]], dict[str, Any]],
        flags_validator: Callable[[dict[str, Any]], tuple[bool, list[str]]],
    ) -> None:
        self.records = list(records)
        self.suggestion_builder = suggestion_builder
        self.flags_validator = flags_validator
        self.profiles = [(record, self._identity_for_record(record)) for record in self.records]
        self._idf = self._build_idf(identity.semantic_tokens for _, identity in self.profiles)

    @classmethod
    def _record_cache_key(cls, record: dict[str, Any]) -> str:
        ident = record.get("id_pbev_preliminar") or record.get("id_pbev") or ""
        if ident:
            return str(ident)
        return "|".join(
            str(record.get(k) or "")
            for k in ("ano_tabela", "marca", "modelo", "versao_corrigida", "motor_corrigido", "transmissao")
        )

    @classmethod
    def _identity_for_record(cls, record: dict[str, Any]) -> TechnicalIdentity:
        key = cls._record_cache_key(record)
        with cls._identity_lock:
            cached = cls._identity_cache.get(key)
            if cached is not None:
                return cached
        identity = build_record_identity(record)
        with cls._identity_lock:
            cls._identity_cache[key] = identity
        return identity

    def _static_for_record(self, record: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, list[str]]:
        key = self._record_cache_key(record)
        with self._static_lock:
            cached = self._static_cache.get(key)
            if cached is not None:
                suggestion, flags_ok, blocks = cached
                return suggestion, flags_ok, list(blocks)
        suggestion = self.suggestion_builder(record)
        flags_ok, blocks = self.flags_validator(record)
        stored = (suggestion, bool(flags_ok), list(blocks))
        with self._static_lock:
            self._static_cache[key] = stored
        return suggestion, bool(flags_ok), list(blocks)

    @staticmethod
    def _build_idf(documents: Iterable[Iterable[str]]) -> dict[str, float]:
        docs = [set(doc) for doc in documents]
        n = max(1, len(docs))
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(doc)
        return {token: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5)) for token, freq in df.items()}

    def _bm25_like(self, query: TechnicalIdentity, candidate: TechnicalIdentity) -> float:
        q = query.semantic_tokens
        d = candidate.semantic_tokens
        if not q or not d:
            return 0.0
        raw = sum(self._idf.get(token, 0.2) for token in q & d)
        denom = sum(self._idf.get(token, 0.2) for token in q) or 1.0
        return min(1.0, raw / denom)

    @staticmethod
    def _side_allowed(query: TechnicalIdentity, candidate: TechnicalIdentity) -> tuple[bool, str | None]:
        prefix = str(query.metadata.get("prefixo") or "").lower()
        prop = candidate.propulsion
        if prefix == "ve":
            if prop not in {"BEV", "PHEV"}:
                return False, f"propulsão {prop or '-'} incompatível com lado VE/PHEV"
            # Entrada explicitamente elétrica pura não deve casar com PHEV.
            if query.propulsion == "BEV" and prop != "BEV":
                return False, "BEV FIPE incompatível com PHEV"
            if query.propulsion == "PHEV" and prop != "PHEV":
                return False, "PHEV FIPE incompatível com BEV"
        elif prefix == "icev":
            if prop not in {"ICE", "HEV", "MHEV"}:
                return False, f"propulsão {prop or '-'} incompatível com lado ICEV/HEV"
            if query.fuel == "HIBRIDO" and prop not in {"HEV", "MHEV"}:
                return False, "veículo híbrido no lado ICEV exige HEV/MHEV não plug-in"
            if query.fuel and query.fuel != "HIBRIDO" and prop in {"HEV", "MHEV"}:
                # Uma FIPE que diz apenas gasolina pode ser MHEV em alguns casos;
                # não bloqueia, mas o score técnico tratará como informação ausente.
                pass
        else:
            # Fora da Simular, usa a propulsão detectada como filtro conservador.
            if query.propulsion == "BEV" and prop != "BEV":
                return False, "BEV FIPE incompatível com outra propulsão"
            if query.propulsion == "PHEV" and prop != "PHEV":
                return False, "PHEV FIPE incompatível com outra propulsão"
        return True, None

    @staticmethod
    def _fuel_compatible(query: TechnicalIdentity, candidate: TechnicalIdentity) -> tuple[bool, str | None]:
        q, c = query.fuel, candidate.fuel
        if not q or not c or q == "HIBRIDO":
            return True, None
        if q == c:
            return True, None
        if q == "GASOLINA" and candidate.propulsion in {"HEV", "MHEV", "PHEV"} and c in {"GASOLINA", "HIBRIDO"}:
            return True, None
        return False, f"combustível incompatível ({q} x {c})"

    @staticmethod
    def _short_code_tokens(identity: TechnicalIdentity) -> set[str]:
        return {
            token for token in identity.model_core_tokens
            if 2 <= len(token) <= 5 and token.isalnum() and token not in {"CROSS", "MINI", "PLUS", "PRO"}
        }

    @classmethod
    def _model_hard_contradictions(
        cls, query: TechnicalIdentity, candidate: TechnicalIdentity, model_fuzz: float
    ) -> list[str]:
        blocks: list[str] = []
        q_core, c_core = set(query.model_core_tokens), set(candidate.model_core_tokens)
        q_alnum, c_alnum = set(query.model_alnum_anchors), set(candidate.model_alnum_anchors)

        if q_alnum and c_alnum and not (q_alnum & c_alnum):
            blocks.append(
                "identificador alfanumérico de modelo divergente: "
                f"{', '.join(sorted(q_alnum))} x {', '.join(sorted(c_alnum))}"
            )
            return blocks

        # PRO/PLUS/MINI/CROSS no campo de modelo são descritores estruturais.
        if query.descriptors and candidate.descriptors and not (query.descriptors & candidate.descriptors):
            blocks.append(
                "descritor estrutural de modelo divergente: "
                f"{', '.join(sorted(query.descriptors))} x {', '.join(sorted(candidate.descriptors))}"
            )
        # CROSS identifica uma família comercial distinta (YARIS x YARIS CROSS,
        # COROLLA x COROLLA CROSS). A ausência na FIPE não pode ser tratada como
        # simples acabamento omitido.
        strict_candidate_only = set(candidate.descriptors) & {"CROSS"}
        if strict_candidate_only and not (strict_candidate_only & set(query.descriptors)):
            blocks.append(
                "descritor estrutural presente apenas no PBEV: "
                + ", ".join(sorted(strict_candidate_only))
            )

        shared = q_core & c_core
        q_codes, c_codes = cls._short_code_tokens(query), cls._short_code_tokens(candidate)
        # Evita XFR→XF, XKR→F-TYPE, SF90→ROMA e casos similares. Exige token
        # exato para códigos curtos quando os dois lados os possuem.
        if q_codes and c_codes and not (q_codes & c_codes) and not (q_alnum & c_alnum):
            if model_fuzz < 92.0 or any(len(t) <= 4 for t in q_codes | c_codes):
                blocks.append(
                    "código comercial de família divergente: "
                    f"{', '.join(sorted(q_codes))} x {', '.join(sorted(c_codes))}"
                )

        if not shared and model_fuzz < 52.0:
            blocks.append("família/modelo sem evidência lexical defensável")
        return blocks

    @staticmethod
    def _technical_hard_contradictions(query: TechnicalIdentity, candidate: TechnicalIdentity) -> list[str]:
        blocks: list[str] = []
        disp = compatible_number_sets(query.displacements, candidate.displacements, tolerance=0.11)
        if disp is False:
            blocks.append(
                "cilindrada divergente: "
                f"{', '.join(f'{v:.1f}' for v in sorted(query.displacements))} x "
                f"{', '.join(f'{v:.1f}' for v in sorted(candidate.displacements))}"
            )
        valves = compatible_number_sets(query.valves, candidate.valves)
        if valves is False:
            blocks.append(
                "válvulas divergentes: "
                f"{', '.join(map(str, sorted(query.valves)))} x {', '.join(map(str, sorted(candidate.valves)))}"
            )
        if query.transmission and candidate.transmission and query.transmission != candidate.transmission:
            blocks.append(f"transmissão incompatível: {query.transmission} x {candidate.transmission}")
        if query.drive and candidate.drive and query.drive != candidate.drive:
            blocks.append(f"tração incompatível: {query.drive} x {candidate.drive}")
        if query.body and candidate.body and query.body != candidate.body:
            blocks.append(f"carroceria incompatível: {query.body} x {candidate.body}")
        if query.model_year and candidate.model_year and query.model_year != candidate.model_year:
            blocks.append(f"ano-modelo MY incompatível: MY{query.model_year} x MY{candidate.model_year}")
        return blocks

    @staticmethod
    def _year_relation(query: TechnicalIdentity, candidate: TechnicalIdentity) -> tuple[float, str, int | None, bool]:
        if not candidate.year:
            return 0.0, "indefinido", None, False
        if query.year:
            diff = abs(query.year - candidate.year)
            if diff == 0:
                return 10.0, "exato", 0, True
            if diff == 1:
                return 6.0, "adjacente", 1, True
            if query.zero_km and diff <= 3 and candidate.year <= query.year:
                return max(1.0, 5.0 - diff), "zero_km_tabela_anterior", diff, True
            if diff == 2:
                return 0.0, "familia_tecnica_proxima", diff, False
            return -min(12.0, 3.0 + diff), "distante", diff, False
        if query.zero_km:
            return min(10.0, max(0.0, candidate.year - 2016) * 0.7), "zero_km_mais_recente", None, True
        return 0.0, "indefinido", None, False

    @staticmethod
    def _model_features(query: TechnicalIdentity, candidate: TechnicalIdentity) -> dict[str, float]:
        q_tokens = set(query.model_core_tokens) or set(query.model_tokens)
        c_tokens = set(candidate.model_core_tokens) or set(candidate.model_tokens)
        shared = q_tokens & c_tokens
        cand_coverage = len(shared) / len(c_tokens) if c_tokens else 0.0
        query_coverage = len(shared) / len(q_tokens) if q_tokens else 0.0
        model_fuzz = float(
            fuzz.token_set_ratio(query.model_normalized.normalized, candidate.model_normalized.normalized)
        )
        full_fuzz = float(fuzz.token_set_ratio(query.normalized.normalized, candidate.normalized.normalized))
        compact_fuzz = float(fuzz.ratio(query.model_normalized.compact, candidate.model_normalized.compact))
        char_cosine = AutomotiveNormalizer.cosine_from_sets(
            query.normalized.char_ngrams, candidate.normalized.char_ngrams
        )
        token_jaccard = AutomotiveNormalizer.jaccard(query.semantic_tokens, candidate.semantic_tokens)
        token_overlap = AutomotiveNormalizer.overlap_coefficient(query.semantic_tokens, candidate.semantic_tokens)
        return {
            "cand_model_coverage": cand_coverage,
            "query_model_coverage": query_coverage,
            "model_fuzz": model_fuzz,
            "full_fuzz": full_fuzz,
            "compact_fuzz": compact_fuzz,
            "char_cosine": char_cosine,
            "token_jaccard": token_jaccard,
            "token_overlap": token_overlap,
            "shared_model_tokens": float(len(shared)),
        }

    def _score_one(self, query: TechnicalIdentity, record: dict[str, Any], candidate: TechnicalIdentity) -> RankedCandidate:
        suggestion, flags_ok, flag_blocks = self._static_for_record(record)
        reasons: list[str] = ["marca compatível"]
        penalties: list[str] = []
        hard_blocks: list[str] = []

        side_ok, side_reason = self._side_allowed(query, candidate)
        if not side_ok and side_reason:
            hard_blocks.append(side_reason)
        fuel_ok, fuel_reason = self._fuel_compatible(query, candidate)
        if not fuel_ok and fuel_reason:
            hard_blocks.append(fuel_reason)

        features = self._model_features(query, candidate)
        model_fuzz = features["model_fuzz"]
        hard_blocks.extend(self._model_hard_contradictions(query, candidate, model_fuzz))
        hard_blocks.extend(self._technical_hard_contradictions(query, candidate))

        model_score = 0.0
        shared = set(query.model_core_tokens) & set(candidate.model_core_tokens)
        if shared:
            model_score += 22.0
            reasons.append(f"família/modelo compatível: {', '.join(sorted(shared))}")
        model_score += 13.0 * features["cand_model_coverage"]
        model_score += 6.0 * features["query_model_coverage"]
        model_score += 5.0 * (model_fuzz / 100.0)
        if query.model_alnum_anchors & candidate.model_alnum_anchors:
            model_score += 8.0
            reasons.append(
                "identificador alfanumérico compatível: "
                + ", ".join(sorted(query.model_alnum_anchors & candidate.model_alnum_anchors))
            )
        if query.descriptors & candidate.descriptors:
            model_score += 4.0
            reasons.append("descritor estrutural de modelo compatível")
        model_score = min(50.0, model_score)

        lexical_score = (
            7.0 * (features["full_fuzz"] / 100.0)
            + 4.0 * (features["compact_fuzz"] / 100.0)
            + 5.0 * features["char_cosine"]
            + 4.0 * features["token_overlap"]
            + 2.0 * self._bm25_like(query, candidate)
        )

        technical_score = 0.0
        disp = compatible_number_sets(query.displacements, candidate.displacements, tolerance=0.11)
        if disp is True:
            technical_score += 8.0
            reasons.append("cilindrada compatível")
        valves = compatible_number_sets(query.valves, candidate.valves)
        if valves is True:
            technical_score += 4.0
            reasons.append("válvulas compatíveis")
        if query.turbo is True and candidate.turbo is True:
            technical_score += 5.0
            reasons.append("turbo compatível")
        elif query.turbo is True and candidate.turbo is None:
            penalties.append("turbo FIPE não confirmado no PBEV")
        elif query.turbo is None and candidate.turbo is True:
            # Ausência não é contradição, mas uma versão aspirada concorrente deve
            # vencer quando o texto FIPE não menciona turbo.
            technical_score -= 3.0
            penalties.append("turbo aparece apenas no candidato PBEV")
        if query.transmission and candidate.transmission and query.transmission == candidate.transmission:
            technical_score += 6.0
            reasons.append("transmissão compatível")
        if query.transmission_subtype and candidate.transmission_subtype:
            if query.transmission_subtype == candidate.transmission_subtype:
                technical_score += 2.0
            elif query.transmission == candidate.transmission == "AUTO":
                technical_score += 0.5
                penalties.append("subtipo de transmissão diferente, mas ambos automáticos")
        if query.gears and candidate.gears:
            if query.gears == candidate.gears:
                technical_score += 2.0
            else:
                technical_score -= 2.0
                penalties.append(f"número de marchas diferente ({query.gears} x {candidate.gears})")
        if query.drive and candidate.drive and query.drive == candidate.drive:
            technical_score += 4.0
            reasons.append("tração compatível")
        if query.body and candidate.body and query.body == candidate.body:
            technical_score += 3.0
            reasons.append("carroceria compatível")
        if candidate.propulsion:
            technical_score += 6.0
            reasons.append(f"propulsão {candidate.propulsion} compatível")
        if fuel_ok and candidate.fuel:
            technical_score += 4.0
            reasons.append(f"combustível {candidate.fuel.lower()} compatível")

        # Acabamento/designação comercial é evidência suave. Nunca trava sozinho.
        trim_shared = (query.trim_tokens | query.semantic_tokens) & candidate.trim_tokens
        query_trim_coverage = (len(trim_shared & query.trim_tokens) / len(query.trim_tokens)) if query.trim_tokens else 0.0
        candidate_trim_coverage = (len(trim_shared) / len(candidate.trim_tokens)) if candidate.trim_tokens else 0.0
        if trim_shared:
            technical_score += min(6.0, 2.0 + len(trim_shared) * 1.5)
            reasons.append("acabamento/designação parcialmente compatível: " + ", ".join(sorted(trim_shared)))
        power_shared = query.commercial_power & candidate.commercial_power
        if power_shared:
            technical_score += 3.0
            reasons.append("designação comercial de potência compatível: " + ", ".join(sorted(power_shared)))
        elif query.commercial_power:
            penalties.append(
                "designação comercial FIPE não confirmada no PBEV: "
                + ", ".join(sorted(query.commercial_power))
            )

        year_score, year_relation, year_diff, year_compatible = self._year_relation(query, candidate)
        if year_relation == "exato":
            reasons.append("ano PBEV igual ao ano-modelo FIPE")
        elif year_relation == "adjacente":
            reasons.append("ano PBEV adjacente ao ano-modelo FIPE")
        elif year_relation == "zero_km_tabela_anterior":
            reasons.append("ano PBEV anterior aceito no contexto zero km")
        elif year_relation == "distante":
            penalties.append(f"ano distante ({query.year} x {candidate.year})")

        score = model_score + lexical_score + technical_score + year_score
        if hard_blocks:
            score = min(score, 24.0)
        if not flags_ok:
            penalties.extend(flag_blocks)
        if not suggestion:
            penalties.append("registro sem sugestão de consumo aplicável")

        model_confident = bool(
            (set(query.model_core_tokens) & set(candidate.model_core_tokens))
            and (features["cand_model_coverage"] >= 0.5 or model_fuzz >= 78.0)
            and not self._model_hard_contradictions(query, candidate, model_fuzz)
        )
        technical_confident = bool(
            model_confident
            and not hard_blocks
            and (disp is not False)
            and (query.transmission is None or candidate.transmission is None or query.transmission == candidate.transmission)
            and side_ok
            and fuel_ok
        )
        features.update({
            "model_confident": model_confident,
            "technical_confident": technical_confident,
            "year_relation": year_relation,
            "year_diff": year_diff,
            "year_compatible": year_compatible,
            "fuel_ok": fuel_ok,
            "side_ok": side_ok,
            "trim_shared": sorted(trim_shared),
            "query_trim_coverage": query_trim_coverage,
            "candidate_trim_coverage": candidate_trim_coverage,
            "power_shared": sorted(power_shared),
            "query_zero_km": bool(query.zero_km),
        })
        return RankedCandidate(
            record=record,
            identity=candidate,
            score=round(score, 4),
            public_score=round(max(0.0, min(100.0, score)), 4),
            model_score=round(model_score, 4),
            lexical_score=round(lexical_score, 4),
            technical_score=round(technical_score, 4),
            year_score=round(year_score, 4),
            reasons=reasons,
            penalties=penalties,
            hard_blocks=hard_blocks,
            features=features,
            suggestion=suggestion,
            flags_ok=flags_ok,
            flag_blocks=flag_blocks,
            retrieval_score=self._bm25_like(query, candidate),
        )

    @staticmethod
    def _sort_key(item: RankedCandidate) -> tuple[Any, ...]:
        exact_year = item.features.get("year_relation") == "exato"
        model_confident = bool(item.features.get("model_confident"))
        technical_confident = bool(item.features.get("technical_confident"))
        zero_km_year_priority = (item.identity.year or 0) if item.features.get("query_zero_km") else 0
        return (
            item.usable,
            not item.hard_blocks,
            technical_confident,
            model_confident,
            exact_year,
            zero_km_year_priority,
            item.score,
            item.identity.year or 0,
        )

    def _retrieval_score(self, query: TechnicalIdentity, candidate: TechnicalIdentity) -> float:
        shared_core = set(query.model_core_tokens) & set(candidate.model_core_tokens)
        shared_anchor = set(query.model_alnum_anchors) & set(candidate.model_alnum_anchors)
        shared_semantic = set(query.semantic_tokens) & set(candidate.semantic_tokens)
        score = 0.0
        score += 45.0 * len(shared_anchor)
        score += 24.0 * len(shared_core)
        score += 12.0 * self._bm25_like(query, candidate)
        score += min(12.0, sum(self._idf.get(t, 0.2) for t in shared_semantic))
        if query.descriptors & candidate.descriptors:
            score += 8.0
        if compatible_number_sets(query.displacements, candidate.displacements, tolerance=0.11) is True:
            score += 5.0
        if query.year and candidate.year:
            diff = abs(query.year - candidate.year)
            score += 4.0 if diff == 0 else (2.0 if diff == 1 else 0.0)
        # Fuzzy apenas sobre o modelo, ainda barato no universo da marca.
        score += 8.0 * (fuzz.token_set_ratio(
            query.model_normalized.normalized, candidate.model_normalized.normalized
        ) / 100.0)
        side_ok, _ = self._side_allowed(query, candidate)
        if not side_ok:
            score -= 40.0
        return score

    def _shortlist(self, query: TechnicalIdentity, limit: int = 120) -> tuple[list[tuple[dict[str, Any], TechnicalIdentity]], int]:
        if len(self.profiles) <= limit:
            return list(self.profiles), 0
        scored: list[tuple[float, dict[str, Any], TechnicalIdentity]] = []
        mandatory: list[tuple[dict[str, Any], TechnicalIdentity]] = []
        mandatory_ids: set[int] = set()
        q_core = set(query.model_core_tokens)
        q_anchor = set(query.model_alnum_anchors)
        for record, identity in self.profiles:
            score = self._retrieval_score(query, identity)
            scored.append((score, record, identity))
            if (q_anchor and q_anchor & set(identity.model_alnum_anchors)) or (q_core and q_core & set(identity.model_core_tokens)):
                mandatory.append((record, identity))
                mandatory_ids.add(id(record))
        scored.sort(key=lambda x: (x[0], x[2].year or 0), reverse=True)
        selected = list(mandatory)
        for _, record, identity in scored:
            if id(record) in mandatory_ids:
                continue
            selected.append((record, identity))
            mandatory_ids.add(id(record))
            if len(selected) >= max(limit, len(mandatory)):
                break
        return selected, max(0, len(self.profiles) - len(selected))

    def rank(self, consulta: dict[str, Any]) -> V2RankingResult:
        query = build_query_identity(consulta)
        evaluated: list[RankedCandidate] = []
        counts = {
            "registros_marca": len(self.profiles),
            "registros_avaliados_marca": 0,
            "candidatos_propulsao_bloqueados": 0,
            "candidatos_contradicao_bloqueados": 0,
            "candidatos_bloqueados_flags": 0,
            "com_sugestao_consumo": 0,
            "sem_sugestao_consumo": 0,
        }
        shortlisted, retrieval_discarded = self._shortlist(query)
        counts["descartados_recuperacao"] = retrieval_discarded
        counts["candidatos_recuperados"] = len(shortlisted)
        for record, identity in shortlisted:
            item = self._score_one(query, record, identity)
            counts["registros_avaliados_marca"] += 1
            if any("propulsão" in block or "PHEV" in block or "BEV" in block for block in item.hard_blocks):
                counts["candidatos_propulsao_bloqueados"] += 1
            if item.hard_blocks:
                counts["candidatos_contradicao_bloqueados"] += 1
            if not item.flags_ok:
                counts["candidatos_bloqueados_flags"] += 1
            if item.suggestion:
                counts["com_sugestao_consumo"] += 1
            else:
                counts["sem_sugestao_consumo"] += 1
            evaluated.append(item)

        evaluated.sort(key=self._sort_key, reverse=True)
        ranked = [item for item in evaluated if item.usable and not item.hard_blocks]
        counts["candidatos_considerados"] = len(evaluated)
        counts["candidatos_utilizaveis"] = len(ranked)
        return V2RankingResult(query=query, ranked=ranked, all_evaluated=evaluated, counts=counts)

    @staticmethod
    def technically_equivalent(query: TechnicalIdentity, a: RankedCandidate, b: RankedCandidate) -> bool:
        ia, ib = a.identity, b.identity
        if ia.propulsion != ib.propulsion:
            return False
        if ia.fuel and ib.fuel and ia.fuel != ib.fuel:
            return False
        if compatible_number_sets(ia.displacements, ib.displacements, tolerance=0.11) is False:
            return False
        if ia.transmission and ib.transmission and ia.transmission != ib.transmission:
            return False
        if ia.drive and ib.drive and ia.drive != ib.drive:
            return False
        # Quando a FIPE não informa carroceria, hatch/sedan podem ser resolvidos
        # pelo consumo conservador; quando informa, a contradição já foi bloqueada.
        if query.body and ia.body and ib.body and ia.body != ib.body:
            return False
        # Turbo diferencia configuração sempre que apenas um candidato o informa.
        # Isso impede agrupar uma versão aspirada com outra turbo somente porque
        # a FIPE omitiu a palavra TURBO.
        if ia.turbo != ib.turbo and (ia.turbo is True or ib.turbo is True):
            return False
        shared_a = set(query.model_core_tokens) & set(ia.model_core_tokens)
        shared_b = set(query.model_core_tokens) & set(ib.model_core_tokens)
        return bool(shared_a and shared_b)
