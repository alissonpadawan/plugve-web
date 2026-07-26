#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.auditar_matching_pbev import (  # noqa: E402
    _texto_candidato,
    carregar_casos,
    validar_expectativa,
    validar_invariantes,
)
from services.pbev_service import PbevService  # noqa: E402

DEFAULT_CASES = ROOT / "data" / "pbev" / "casos_regressao_matching_v45_etapa2.json"
DEFAULT_OUTPUT = ROOT / "docs" / "auditoria_matching_v45_etapa2"


def _candidate_contract(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    candidate = result.get("candidato") or {}
    text = _texto_candidato(result)
    if expected.get("nivel_match") == "sem_match":
        return not candidate
    if not candidate:
        return False
    if "modelo_igual" in expected and str(candidate.get("modelo") or "").upper() != str(expected["modelo_igual"]).upper():
        return False
    if "modelo_contem" in expected and str(expected["modelo_contem"]).upper() not in str(candidate.get("modelo") or "").upper():
        return False
    if "modelo_versao_contem" in expected and str(expected["modelo_versao_contem"]).upper() not in text:
        return False
    if "modelo_nao_contem" in expected and str(expected["modelo_nao_contem"]).upper() in text:
        return False
    return True


def evaluate_case(service: PbevService, case: dict[str, Any]) -> dict[str, Any]:
    result = service.sugerir_consumo(case.get("consulta") or {})
    errors = validar_expectativa(result, case.get("esperado") or {})
    errors.extend(validar_invariantes(result))
    diagnostics = result.get("diagnostico") or {}
    filters = (result.get("debug") or {}).get("filtros") or {}
    normalization = (result.get("debug") or {}).get("normalizacao") or {}
    candidate = result.get("candidato") or {}
    suggestion = result.get("sugestoes_consumo") or {}
    return {
        "id": case.get("id"),
        "origem": case.get("origem"),
        "status_v45": case.get("status_v45"),
        "status_execucao": "APROVADO" if not errors else "FALHA",
        "erros": errors,
        "contrato_localizacao_ou_ausencia_atendido": _candidate_contract(result, case.get("esperado") or {}),
        "nivel_match": result.get("nivel_match"),
        "autopreencher": result.get("autopreencher"),
        "criterio_match": result.get("criterio_match"),
        "cobertura_pbev": result.get("cobertura_pbev"),
        "score": result.get("score"),
        "score_bruto": result.get("score_bruto"),
        "ano_tabela_pbev": result.get("ano_tabela_pbev"),
        "candidato": _texto_candidato(result),
        "id_pbev": candidate.get("id_pbev"),
        "tipo_consumo": suggestion.get("tipo"),
        "gasolina_cidade_km_l": suggestion.get("gasolina_cidade_km_l"),
        "etanol_cidade_km_l": suggestion.get("etanol_cidade_km_l"),
        "gasolina_diesel_cidade_km_l": suggestion.get("gasolina_diesel_cidade_km_l"),
        "consumo_eletrico_kwh_km": suggestion.get("consumo_eletrico_kwh_km"),
        "tokens_fortes_fipe": diagnostics.get("tokens_fortes_fipe") or normalization.get("tokens_fortes_modelo") or [],
        "tokens_fortes_pbev": diagnostics.get("tokens_fortes_pbev") or [],
        "identidade_tecnica_forte": diagnostics.get("identidade_tecnica_forte"),
        "tecnica_suficiente_para_consumo": diagnostics.get("tecnica_suficiente_para_consumo"),
        "dominante": diagnostics.get("dominante"),
        "ambiguidade_proxima": diagnostics.get("ambiguidade_proxima"),
        "registros_marca": filters.get("registros_marca"),
        "registros_avaliados_marca": filters.get("registros_avaliados_marca"),
        "candidatos_busca_principal": filters.get("candidatos_busca_principal"),
        "candidatos_busca_resgate": filters.get("candidatos_busca_resgate"),
        "busca_resgate_acionada": filters.get("busca_resgate_acionada"),
        "descartados_prefiltro_identidade": filters.get("descartados_prefiltro_identidade"),
        "motivo": result.get("motivo"),
    }


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row["status_execucao"] for row in rows)
    negatives = [row for row in rows if row.get("nivel_match") == "sem_match"]
    positives = [row for row in rows if row.get("nivel_match") != "sem_match"]
    corrected = [row for row in rows if row.get("status_v45") == "lacuna_corrigida_etapa2"]
    return {
        "versao_site_base": "V44.3",
        "etapa": "V45 Etapa 2 — motor geral",
        "casos_total": len(rows),
        "casos_aprovados": statuses.get("APROVADO", 0),
        "falhas": statuses.get("FALHA", 0),
        "positivos_localizados": sum(1 for row in positives if row.get("candidato")),
        "positivos_autopreenchidos": sum(1 for row in positives if row.get("autopreencher")),
        "negativos_preservados": sum(1 for row in negatives if not row.get("candidato")),
        "lacunas_corrigidas_etapa2": len(corrected),
        "casos_corrigidos": [row["id"] for row in corrected],
        "prefiltro_destrutivo_removido": all((row.get("descartados_prefiltro_identidade") or 0) == 0 for row in rows),
        "arquivos_producao_alterados": [
            "services/pbev_service.py",
            "data/pbev/aliases_automotivos_v1.json",
        ],
        "interface_v44_alterada": False,
    }


def save_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "matriz_regressao_v45_etapa2.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = sorted({key for row in rows for key in row})
    with (output_dir / "matriz_regressao_v45_etapa2.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    (output_dir / "resumo_v45_etapa2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Matching FIPE × PBEV/Inmetro — V45 Etapa 2",
        "",
        "## Resultado executivo",
        "",
        f"- Casos executados: **{summary['casos_total']}**.",
        f"- Casos aprovados: **{summary['casos_aprovados']}**.",
        f"- Positivos localizados: **{summary['positivos_localizados']}**.",
        f"- Positivos autopreenchidos: **{summary['positivos_autopreenchidos']}**.",
        f"- Negativos preservados: **{summary['negativos_preservados']}**.",
        f"- Lacunas corrigidas nesta etapa: **{summary['lacunas_corrigidas_etapa2']}**.",
        "",
        "## Núcleo implementado",
        "",
        "- aliases automotivos gerais versionados em JSON;",
        "- separação entre tokens comerciais e componentes técnicos;",
        "- extração estruturada de cilindrada, válvulas, turbo, transmissão, marchas, tração, carroceria e MY;",
        "- busca principal seguida de busca de resgate quando não há candidato defensável;",
        "- nenhum candidato da marca é descartado silenciosamente pelo antigo pré-filtro;",
        "- bloqueios duros para incompatibilidades explícitas, mantendo ausência como ausência;",
        "- auditoria com identidade FIPE/PBEV e faixa de busca.",
        "",
        "## Casos corrigidos",
        "",
    ]
    lines.extend(f"- `{case_id}`" for case_id in summary["casos_corrigidos"])
    lines.extend([
        "",
        "## Matriz",
        "",
        "| Caso | Estado | Nível | Autofill | Candidato |",
        "|---|---|---|---:|---|",
    ])
    for row in rows:
        lines.append(
            f"| `{row['id']}` | {row['status_execucao']} | {row['nivel_match']} | "
            f"{'sim' if row['autopreencher'] else 'não'} | {row['candidato'] or '—'} |"
        )
    lines.extend([
        "",
        "## Preservação",
        "",
        "Nenhum template, JavaScript, rota de TCO, depreciação, ANP, ANEEL ou Painel Local foi alterado.",
        "A etapa modifica apenas o núcleo PBEV, seus aliases, testes e documentação.",
    ])
    (output_dir / "diagnostico_matching_pbev_v45_etapa2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(cases_path: Path = DEFAULT_CASES, output_dir: Path = DEFAULT_OUTPUT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service = PbevService(
        base_path=ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
        manifest_path=ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
    )
    rows = [evaluate_case(service, case) for case in carregar_casos(cases_path)]
    summary = build_summary(rows)
    save_outputs(rows, summary, output_dir)
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida a V45 Etapa 2 do matching FIPE × PBEV.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    _, summary = run(args.input, args.output_dir)
    print(
        f"V45 Etapa 2: {summary['casos_aprovados']}/{summary['casos_total']} aprovados; "
        f"falhas={summary['falhas']}"
    )
    print(f"Saída: {args.output_dir}")
    return 1 if summary["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
