from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pbev_matching_v2 import PbevMatcherV2
from services.pbev_matching_v2.identity import build_record_identity, compatible_number_sets
from services.pbev_service import PbevService

SEED = 4502


def record_id(record: dict[str, Any]) -> str:
    return str(record.get("id_pbev_preliminar") or record.get("id_pbev") or "")


def raw_record_name(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "").strip()
        for key in ("modelo", "versao_corrigida", "motor_corrigido", "transmissao")
        if str(record.get(key) or "").strip()
    ).strip()


def propulsion_for(record: dict[str, Any]) -> tuple[str, str]:
    prop = str(record.get("tipo_propulsao_normalizado") or record.get("tipo_propulsao") or "").upper()
    if any(token in prop for token in ("PHEV", "PLUG")):
        return "ve", "hibrido"
    if any(token in prop for token in ("ELETR", "BEV")):
        return "ve", "eletrico"
    if any(token in prop for token in ("HIBR", "HEV", "MHEV")):
        return "icev", "hibrido"
    return "icev", "combustao"


def fuel_for(record: dict[str, Any]) -> str:
    value = str(record.get("combustivel_normalizado") or record.get("combustivel") or "").upper()
    mapping = {
        "F": "Flex", "FLEX": "Flex", "G": "Gasolina", "GASOLINA": "Gasolina",
        "D": "Diesel", "DIESEL": "Diesel", "E": "Elétrico", "ELETRICO": "Elétrico",
        "ELÉTRICO": "Elétrico", "H": "Híbrido", "HIBRIDO": "Híbrido", "HÍBRIDO": "Híbrido",
    }
    if value in mapping:
        return mapping[value]
    prop = str(record.get("tipo_propulsao_normalizado") or "").upper()
    if "PHEV" in prop or "HEV" in prop or "HIBR" in prop:
        return "Híbrido"
    if "ELETR" in prop or "BEV" in prop:
        return "Elétrico"
    return value.title() or "Gasolina"


def compact_tokens(text: str) -> str:
    text = re.sub(r"\b([A-Za-z]{1,8})\s+(\d+(?:\.\d+)?[A-Za-z]?)\b", r"\1\2", text, count=2)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s+(T|V|I|D)\b", r"\1\2", text, flags=re.I)
    return text


def abbreviate(text: str) -> str:
    replacements = [
        (r"\bAUTOMATICO\b|\bAUTOMÁTICO\b", "Aut."),
        (r"\bMANUAL\b", "Mec."),
        (r"\bTURBO\b", "TB"),
        (r"\bTITANIUM\b", "TIT."),
        (r"\bEDITION\b", "Ed."),
        (r"\bPICKUP\b", "Pick-up"),
    ]
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.I)
    out = out.replace(" / ", "/").replace(" - ", "-")
    return out


def reorder_and_drop(text: str, rng: random.Random) -> str:
    parts = [p for p in re.split(r"\s+", text) if p]
    if len(parts) > 7:
        # Remove um token textual secundário, nunca números/motor/transmissão.
        removable = [i for i, p in enumerate(parts[1:-2], start=1) if p.isalpha() and len(p) > 2]
        if removable:
            parts.pop(rng.choice(removable))
    # Move os dois últimos elementos para o meio; simula ordem FIPE/PBEV diferente.
    if len(parts) > 6:
        tail = parts[-2:]
        parts = parts[:-2]
        insert_at = min(2, len(parts))
        parts[insert_at:insert_at] = tail
    return " ".join(parts)


def variants_for(record: dict[str, Any], rng: random.Random) -> list[tuple[str, str]]:
    base = raw_record_name(record)
    return [
        ("abreviado", abbreviate(base)),
        ("colado", compact_tokens(abbreviate(base))),
        ("reordenado_sem_secundario", reorder_and_drop(abbreviate(base), rng)),
    ]


def build_query(record: dict[str, Any], text: str) -> dict[str, Any]:
    year = int(record.get("ano_tabela") or 0)
    fuel = fuel_for(record)
    prefix, vehicle_type = propulsion_for(record)
    return {
        "prefixo": prefix,
        "marca": record.get("marca"),
        "modelo": text,
        "texto_modelo": f"{text} {year} {fuel}",
        "ano": year,
        "ano_codigo": str(year),
        "texto_ano": f"{year} {fuel}",
        "combustivel": fuel,
        "tipo_veiculo": vehicle_type,
    }


def equivalent(service: PbevService, source_item, candidate_item, query) -> bool:
    if record_id(source_item.record) == record_id(candidate_item.record):
        return True
    if source_item.identity.year != candidate_item.identity.year:
        return False
    if not PbevMatcherV2.technically_equivalent(query, source_item, candidate_item):
        return False
    return service._assinatura_sugestao(source_item.suggestion) == service._assinatura_sugestao(candidate_item.suggestion)


def decision_equivalent(service: PbevService, source: dict[str, Any], selected: dict[str, Any] | None, suggestion: dict[str, Any] | None, records_by_id: dict[str, dict[str, Any]]) -> bool:
    if not selected:
        return False
    selected_record = records_by_id.get(str(selected.get("id_pbev") or ""))
    if selected_record is None:
        return False
    if record_id(source) == record_id(selected_record):
        return True
    a, b = build_record_identity(source), build_record_identity(selected_record)
    if a.year != b.year or a.propulsion != b.propulsion:
        return False
    if compatible_number_sets(a.displacements, b.displacements, tolerance=0.11) is False:
        return False
    if a.transmission and b.transmission and a.transmission != b.transmission:
        return False
    if not ((set(a.model_alnum_anchors) & set(b.model_alnum_anchors)) or (set(a.model_core_tokens) & set(b.model_core_tokens))):
        return False
    return service._assinatura_sugestao(service.montar_sugestao_consumo(source)) == service._assinatura_sugestao(suggestion)


def run(sample_size: int, output_dir: Path) -> dict[str, Any]:
    rng = random.Random(SEED)
    service = PbevService()
    cache = service.carregar_base_pbev()

    usable = []
    by_brand = defaultdict(list)
    for row in cache.registros:
        ok, _ = service.validar_flags_autofill(row)
        suggestion = service.montar_sugestao_consumo(row)
        if ok and suggestion and row.get("marca") and row.get("modelo") and row.get("ano_tabela"):
            usable.append(row)
            by_brand[service._marca_key(row.get("marca"))].append(row)

    records_by_id = {record_id(row): row for row in usable if record_id(row)}

    # Amostra equilibrada: pelo menos um registro por marca, depois aleatório global.
    selected = []
    seen = set()
    for brand in sorted(by_brand):
        row = rng.choice(by_brand[brand])
        selected.append(row)
        seen.add(record_id(row))
    remaining = [r for r in usable if record_id(r) not in seen]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, sample_size - len(selected))])
    selected = selected[:sample_size]

    matcher_cache: dict[str, PbevMatcherV2] = {}
    metrics = Counter()
    metrics_by_variant = defaultdict(Counter)
    failures = []
    latencies_ms = []
    start = time.perf_counter()

    for source in selected:
        brand_key = service._marca_key(source.get("marca"))
        matcher = matcher_cache.get(brand_key)
        if matcher is None:
            matcher = PbevMatcherV2(
                by_brand[brand_key],
                suggestion_builder=service.montar_sugestao_consumo,
                flags_validator=service.validar_flags_autofill,
            )
            matcher_cache[brand_key] = matcher

        for variant_name, text in variants_for(source, rng):
            query_dict = build_query(source, text)
            t0 = time.perf_counter()
            ranking = matcher.rank(query_dict)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            metrics["queries"] += 1
            metrics_by_variant[variant_name]["queries"] += 1

            source_item = next((x for x in ranking.all_evaluated if record_id(x.record) == record_id(source)), None)
            top = ranking.ranked[:5]
            positions = []
            if source_item is not None:
                for idx, item in enumerate(top, start=1):
                    if equivalent(service, source_item, item, ranking.query):
                        positions.append(idx)
            pos = min(positions) if positions else None
            if pos == 1:
                metrics["recall_at_1"] += 1
                metrics_by_variant[variant_name]["recall_at_1"] += 1
            if pos is not None and pos <= 3:
                metrics["recall_at_3"] += 1
                metrics_by_variant[variant_name]["recall_at_3"] += 1
            if pos is not None and pos <= 5:
                metrics["recall_at_5"] += 1
                metrics_by_variant[variant_name]["recall_at_5"] += 1
            if pos is None and len(failures) < 50:
                failures.append({
                    "id_origem": record_id(source),
                    "marca": source.get("marca"),
                    "nome_origem": raw_record_name(source),
                    "variante": variant_name,
                    "consulta": text,
                    "top5": [
                        {
                            "id": record_id(item.record),
                            "nome": raw_record_name(item.record),
                            "score": item.score,
                            "bloqueios": item.hard_blocks,
                        }
                        for item in top
                    ],
                })

    # Mede também a decisão final do endpoint em uma subamostra. O objetivo é
    # precisão do autofill, não apenas recuperação no ranking.
    decision_metrics = Counter()
    decision_failures = []
    decision_sample = selected[: min(200, len(selected))]
    for source in decision_sample:
        variant_name, text = variants_for(source, rng)[1]  # forma com tokens colados
        query_dict = build_query(source, text)
        response = service.sugerir_consumo(query_dict)
        decision_metrics["queries"] += 1
        if response.get("autopreencher"):
            decision_metrics["autofills"] += 1
            if decision_equivalent(service, source, response.get("candidato"), response.get("sugestoes_consumo"), records_by_id):
                decision_metrics["correct_autofills"] += 1
            else:
                decision_metrics["false_autofills"] += 1
                if len(decision_failures) < 25:
                    decision_failures.append({
                        "id_origem": record_id(source),
                        "nome_origem": raw_record_name(source),
                        "consulta": text,
                        "candidato": response.get("candidato"),
                        "criterio": response.get("criterio_match"),
                    })
        else:
            decision_metrics["manual"] += 1

    elapsed = time.perf_counter() - start
    q = max(1, metrics["queries"])
    result = {
        "motor": "V2",
        "seed": SEED,
        "registros_pbev_total": len(cache.registros),
        "registros_pbev_utilizaveis": len(usable),
        "registros_amostrados": len(selected),
        "variacoes_por_registro": 3,
        "consultas_sinteticas": metrics["queries"],
        "recall_at_1": metrics["recall_at_1"] / q,
        "recall_at_3": metrics["recall_at_3"] / q,
        "recall_at_5": metrics["recall_at_5"] / q,
        "decisoes_finais_avaliadas": decision_metrics["queries"],
        "autofills": decision_metrics["autofills"],
        "autofills_corretos": decision_metrics["correct_autofills"],
        "falsos_autofills": decision_metrics["false_autofills"],
        "precisao_autofill": (decision_metrics["correct_autofills"] / decision_metrics["autofills"]) if decision_metrics["autofills"] else 1.0,
        "cobertura_autofill_sintetica": decision_metrics["autofills"] / max(1, decision_metrics["queries"]),
        "falhas_decisao_amostra": decision_failures,
        "tempo_total_s": elapsed,
        "latencia_media_ms": sum(latencies_ms) / max(1, len(latencies_ms)),
        "latencia_p95_ms": sorted(latencies_ms)[int(0.95 * (len(latencies_ms) - 1))] if latencies_ms else 0.0,
        "por_variante": {},
        "falhas_top5_amostra": failures,
        "observacao": (
            "Benchmark sintético: o registro PBEV de origem ou outro registro tecnicamente equivalente "
            "com o mesmo consumo é aceito como correto. Não substitui validação com pares FIPE reais."
        ),
    }
    for name, values in sorted(metrics_by_variant.items()):
        n = max(1, values["queries"])
        result["por_variante"][name] = {
            "consultas": values["queries"],
            "recall_at_1": values["recall_at_1"] / n,
            "recall_at_3": values["recall_at_3"] / n,
            "recall_at_5": values["recall_at_5"] / n,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_matching_pbev_v2.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md = [
        "# Benchmark sintético — Motor PBEV V2",
        "",
        f"- Registros PBEV utilizáveis: **{len(usable)}**",
        f"- Registros amostrados: **{len(selected)}**",
        f"- Consultas sintéticas: **{metrics['queries']}**",
        f"- Recall@1 técnico: **{result['recall_at_1']:.2%}**",
        f"- Recall@3 técnico: **{result['recall_at_3']:.2%}**",
        f"- Recall@5 técnico: **{result['recall_at_5']:.2%}**",
        f"- Decisões finais avaliadas: **{result['decisoes_finais_avaliadas']}**",
        f"- Precisão do autofill sintético: **{result['precisao_autofill']:.2%}**",
        f"- Falsos autofills na subamostra: **{result['falsos_autofills']}**",
        f"- Cobertura automática sintética: **{result['cobertura_autofill_sintetica']:.2%}**",
        f"- Latência média do ranking: **{result['latencia_media_ms']:.2f} ms**",
        f"- Latência p95 do ranking: **{result['latencia_p95_ms']:.2f} ms**",
        "",
        "O teste gera abreviações, tokens colados e reordenação/remoção de termo secundário a partir da própria base PBEV. "
        "Ele mede recuperação técnica local e não é apresentado como prova de 100% sobre toda nomenclatura FIPE futura.",
    ]
    (output_dir / "benchmark_matching_pbev_v2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/auditoria_matching_v2"))
    args = parser.parse_args()
    result = run(args.sample_size, args.output_dir)
    print(json.dumps({k: result[k] for k in ("consultas_sinteticas", "recall_at_1", "recall_at_3", "recall_at_5", "tempo_total_s")}, indent=2))


if __name__ == "__main__":
    main()
