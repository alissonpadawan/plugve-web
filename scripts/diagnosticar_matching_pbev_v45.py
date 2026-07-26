#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

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

DEFAULT_CASES = ROOT / "data" / "pbev" / "casos_regressao_matching_v45_etapa1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "auditoria_matching_v45_etapa1"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _candidate_matches_contract(result: dict[str, Any], contract: dict[str, Any]) -> tuple[bool, list[str]]:
    """Valida apenas se o candidato-alvo foi localizado, sem exigir autofill."""
    if not contract:
        return bool(result.get("candidato") or result.get("nivel_match") == "sem_match"), []

    candidate = result.get("candidato") or {}
    errors: list[str] = []
    candidate_text = _texto_candidato(result)

    if "modelo_igual" in contract:
        obtained = str(candidate.get("modelo") or "").upper()
        expected = str(contract["modelo_igual"]).upper()
        if obtained != expected:
            errors.append(f"modelo_igual: esperado={expected!r}, obtido={obtained!r}")
    if "modelo_contem" in contract:
        expected = str(contract["modelo_contem"]).upper()
        obtained = str(candidate.get("modelo") or "").upper()
        if expected not in obtained:
            errors.append(f"modelo_contem: {expected!r} não está em {obtained!r}")
    if "modelo_versao_contem" in contract:
        expected = str(contract["modelo_versao_contem"]).upper()
        if expected not in candidate_text:
            errors.append(f"modelo_versao_contem: {expected!r} não está em {candidate_text!r}")
    if "ano_tabela_pbev" in contract and result.get("ano_tabela_pbev") != contract["ano_tabela_pbev"]:
        errors.append(
            f"ano_tabela_pbev: esperado={contract['ano_tabela_pbev']!r}, "
            f"obtido={result.get('ano_tabela_pbev')!r}"
        )
    if "tipo_consumo" in contract:
        obtained = (result.get("sugestoes_consumo") or {}).get("tipo")
        if obtained != contract["tipo_consumo"]:
            errors.append(f"tipo_consumo: esperado={contract['tipo_consumo']!r}, obtido={obtained!r}")

    return not errors, errors


def _top_debug(result: dict[str, Any], index: int = 0) -> dict[str, Any]:
    candidates = ((result.get("debug") or {}).get("candidatos_top") or [])
    return candidates[index] if index < len(candidates) else {}


def evaluate_case(service: PbevService, case: dict[str, Any]) -> dict[str, Any]:
    result = service.sugerir_consumo(case.get("consulta") or {})
    target_errors = validar_expectativa(result, case.get("esperado") or {})
    invariant_errors = validar_invariantes(result)
    all_errors = target_errors + invariant_errors
    known_gap = bool(case.get("falha_conhecida"))

    if not all_errors and known_gap:
        status = "LACUNA_CORRIGIDA"
    elif not all_errors:
        status = "APROVADO"
    elif known_gap:
        status = "FALHA_CONHECIDA"
    else:
        status = "REGRESSAO_INESPERADA"

    location_contract = case.get("contrato_localizacao") or case.get("esperado") or {}
    contract_ok, location_errors = _candidate_matches_contract(result, location_contract)
    expected = case.get("esperado") or {}
    expected_absence = bool(
        expected.get("nivel_match") == "sem_match"
        and not any(key in expected for key in ("modelo_igual", "modelo_contem", "modelo_versao_contem"))
    )
    candidate_present = bool(result.get("candidato"))
    located = bool(candidate_present and contract_ok and not expected_absence)
    expected_absence_confirmed = bool(expected_absence and contract_ok and not candidate_present)
    top = _top_debug(result, 0)
    second = _top_debug(result, 1)
    diagnostics = result.get("diagnostico") or {}
    filters = (result.get("debug") or {}).get("filtros") or {}
    normalization = (result.get("debug") or {}).get("normalizacao") or {}

    return {
        "id": case.get("id"),
        "origem": case.get("origem"),
        "status_v45": case.get("status_v45"),
        "status_execucao": status,
        "falha_conhecida": known_gap,
        "classificacao_falha": list(case.get("classificacao_falha") or []),
        "contrato_localizacao_ou_ausencia_atendido": contract_ok,
        "candidato_alvo_localizado": located,
        "ausencia_esperada_confirmada": expected_absence_confirmed,
        "erros_localizacao": location_errors,
        "erros_meta_v45": target_errors,
        "erros_invariantes": invariant_errors,
        "nivel_match": result.get("nivel_match"),
        "autopreencher": result.get("autopreencher"),
        "criterio_match": result.get("criterio_match"),
        "cobertura_pbev": result.get("cobertura_pbev"),
        "score": result.get("score"),
        "score_bruto": result.get("score_bruto"),
        "ano_tabela_pbev": result.get("ano_tabela_pbev"),
        "candidato": _texto_candidato(result),
        "id_pbev": (result.get("candidato") or {}).get("id_pbev"),
        "tipo_consumo": (result.get("sugestoes_consumo") or {}).get("tipo"),
        "gasolina_cidade_km_l": (result.get("sugestoes_consumo") or {}).get("gasolina_cidade_km_l"),
        "etanol_cidade_km_l": (result.get("sugestoes_consumo") or {}).get("etanol_cidade_km_l"),
        "consumo_eletrico_kwh_km": (result.get("sugestoes_consumo") or {}).get("consumo_eletrico_kwh_km"),
        "motivo": result.get("motivo"),
        "tokens_fortes_fipe": diagnostics.get("tokens_fortes_fipe") or normalization.get("tokens_fortes_modelo") or [],
        "tokens_fortes_pbev": diagnostics.get("tokens_fortes_pbev") or [],
        "identidade_tecnica_forte": diagnostics.get("identidade_tecnica_forte"),
        "tecnica_suficiente_para_consumo": diagnostics.get("tecnica_suficiente_para_consumo"),
        "dominante": diagnostics.get("dominante"),
        "ambiguidade_proxima": diagnostics.get("ambiguidade_proxima"),
        "ambiguidade_resolvida_por_consumo": diagnostics.get("ambiguidade_resolvida_por_consumo"),
        "diferenca_para_segundo": diagnostics.get("diferenca_para_segundo"),
        "descartados_prefiltro_identidade": filters.get("descartados_prefiltro_identidade"),
        "registros_marca": filters.get("registros_marca"),
        "top_sugestao": top.get("sugestao_consumo") or {},
        "segundo_candidato": _texto_debug_candidate(second),
        "segundo_sugestao": second.get("sugestao_consumo") or {},
    }


def _texto_debug_candidate(item: dict[str, Any]) -> str:
    candidate = item.get("candidato") or {}
    return " ".join(str(candidate.get(key) or "") for key in ("modelo", "versao")).upper().strip()


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def save_json_csv(rows: Iterable[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    data = list(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "matriz_regressao_v45_etapa1.json"
    csv_path = output_dir / "matriz_regressao_v45_etapa1.csv"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "id", "origem", "status_v45", "status_execucao", "falha_conhecida",
        "classificacao_falha", "contrato_localizacao_ou_ausencia_atendido",
        "candidato_alvo_localizado", "ausencia_esperada_confirmada", "erros_localizacao",
        "erros_meta_v45", "erros_invariantes", "nivel_match", "autopreencher",
        "criterio_match", "cobertura_pbev", "score", "score_bruto", "ano_tabela_pbev",
        "candidato", "id_pbev", "tipo_consumo", "gasolina_cidade_km_l",
        "etanol_cidade_km_l", "consumo_eletrico_kwh_km", "tokens_fortes_fipe",
        "tokens_fortes_pbev", "identidade_tecnica_forte", "tecnica_suficiente_para_consumo",
        "dominante", "ambiguidade_proxima", "ambiguidade_resolvida_por_consumo",
        "diferenca_para_segundo", "descartados_prefiltro_identidade", "registros_marca",
        "segundo_candidato", "top_sugestao", "segundo_sugestao", "motivo",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in data:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})
    return json_path, csv_path


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row["status_execucao"] for row in rows)
    classifications = Counter(
        classification
        for row in rows
        for classification in row.get("classificacao_falha") or []
        if row["status_execucao"] in {"FALHA_CONHECIDA", "REGRESSAO_INESPERADA"}
    )
    return {
        "versao_site_analisada": "V44.3",
        "etapa": "V45 Etapa 1 — diagnóstico e harness",
        "casos_total": len(rows),
        "casos_aprovados_meta_v45": statuses.get("APROVADO", 0) + statuses.get("LACUNA_CORRIGIDA", 0),
        "regressoes_protegidas_aprovadas": sum(
            1 for row in rows
            if row.get("status_v45") == "regressao_protegida" and row["status_execucao"] == "APROVADO"
        ),
        "falhas_conhecidas": statuses.get("FALHA_CONHECIDA", 0),
        "lacunas_corrigidas": statuses.get("LACUNA_CORRIGIDA", 0),
        "regressoes_inesperadas": statuses.get("REGRESSAO_INESPERADA", 0),
        "contratos_localizacao_ou_ausencia_atendidos": sum(
            1 for row in rows if row.get("contrato_localizacao_ou_ausencia_atendido")
        ),
        "candidatos_positivos_localizados": sum(1 for row in rows if row.get("candidato_alvo_localizado")),
        "ausencias_negativas_preservadas": sum(1 for row in rows if row.get("ausencia_esperada_confirmada")),
        "classificacoes_falha": dict(classifications),
        "arquivos_producao_alterados": [],
        "observacao": (
            "A Etapa 1 não modifica o motor de matching nem a interface. "
            "Falhas conhecidas permanecem visíveis no relatório e não mascaram regressões novas."
        ),
    }


def save_summary(summary: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "resumo_v45_etapa1.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_markdown(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "diagnostico_matching_pbev_v45.md"
    gaps = [row for row in rows if row["status_execucao"] in {"FALHA_CONHECIDA", "REGRESSAO_INESPERADA"}]
    lines = [
        "# Diagnóstico do matching FIPE × PBEV/Inmetro — V45 Etapa 1",
        "",
        "## Escopo congelado",
        "",
        "Esta etapa adiciona somente casos de regressão, ferramenta de diagnóstico e documentação.",
        "Nenhum arquivo de produção do motor, endpoint ou interface foi alterado.",
        "",
        "## Resultado executivo",
        "",
        f"- Site-base: **{summary['versao_site_analisada']}**.",
        f"- Casos executados: **{summary['casos_total']}**.",
        f"- Regressões protegidas aprovadas: **{summary['regressoes_protegidas_aprovadas']}**.",
        f"- Falhas conhecidas reproduzidas: **{summary['falhas_conhecidas']}**.",
        f"- Regressões inesperadas: **{summary['regressoes_inesperadas']}**.",
        f"- Contratos de localização/ausência atendidos: **{summary['contratos_localizacao_ou_ausencia_atendidos']}**.",
        f"- Candidatos positivos localizados: **{summary['candidatos_positivos_localizados']}**.",
        f"- Ausências negativas preservadas: **{summary['ausencias_negativas_preservadas']}**.",
        "",
        "## Matriz resumida",
        "",
        "| Caso | Estado | Contrato localização/ausência | Nível atual | Autofill | Candidato |",
        "|---|---|---:|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['id']}` | {row['status_execucao']} | "
            f"{'sim' if row['contrato_localizacao_ou_ausencia_atendido'] else 'não'} | "
            f"{_as_text(row['nivel_match'])} | {'sim' if row['autopreencher'] else 'não'} | "
            f"{row['candidato'] or '—'} |"
        )

    lines.extend(["", "## Lacunas e regressões", ""])
    if not gaps:
        lines.append("Nenhuma lacuna ou regressão foi detectada.")
    for row in gaps:
        lines.extend([
            f"### {row['id']}",
            "",
            f"- Estado: **{row['status_execucao']}**.",
            f"- Classificação: {_as_text(row['classificacao_falha']) or 'não classificada'}.",
            f"- Candidato localizado: **{'sim' if row['candidato_alvo_localizado'] else 'não'}**.",
            f"- Resultado atual: `{row['nivel_match']}`, autofill `{row['autopreencher']}`.",
            f"- Candidato atual: **{row['candidato'] or 'nenhum'}**.",
            f"- Score bruto: **{row['score_bruto']}**.",
            f"- Tokens fortes FIPE: `{_as_text(row['tokens_fortes_fipe']) or 'nenhum'}`.",
            f"- Identidade técnica forte: **{_as_text(row['identidade_tecnica_forte'])}**.",
            f"- Técnica suficiente para consumo: **{_as_text(row['tecnica_suficiente_para_consumo'])}**.",
            f"- Erros contra a meta V45: {_as_text(row['erros_meta_v45'])}.",
            "",
        ])

    creta = next((row for row in rows if row["id"] == "hyundai_creta_comfort_tb12v_zero_km"), None)
    if creta:
        lines.extend([
            "## Diagnóstico específico — Hyundai Creta Comfort 1.0 TB 12V",
            "",
            "O registro correto está presente e foi localizado como `PBEV-2026-0386`.",
            "A entrada FIPE e o candidato PBEV coincidem em marca, família, acabamento, ano,",
            "cilindrada, válvulas, turbo, combustível e transmissão.",
            "",
            "A falha reproduzida ocorre porque o extrator atual forma `TB12V` como token forte",
            "de identidade comercial. O PBEV registra o mesmo conjunto técnico como `12V T`,",
            "portanto o token artificial fica ausente no candidato e rebaixa a identidade técnica.",
            "",
            "Os dois candidatos líderes possuem a mesma sugestão de consumo, mas a resolução por",
            "consumo não é acionada porque ambos chegam à etapa de ambiguidade com identidade técnica",
            "marcada como insuficiente. O backend retorna `medio` e `autopreencher=false`, embora o",
            "candidato correto esteja localizado.",
            "",
            "### Contrato esperado para a próxima etapa",
            "",
            "- `TB`, `T` e `TURBO` devem ser comparados como característica técnica contextual.",
            "- `12V` deve continuar sendo assinatura de válvulas, não identificador comercial.",
            "- `TB12V` não pode ser criado como token forte de família/modelo.",
            "- Candidatos tecnicamente equivalentes e com consumo idêntico podem formar grupo equivalente.",
            "- O resultado esperado é match alto, editável e com procedência Inmetro.",
            "",
        ])

    lines.extend([
        "## Próxima etapa recomendada",
        "",
        "Implementar o núcleo geral em módulos separados: normalização contextual, extração de identidade",
        "técnica, geração ampla de candidatos, restrições duras, score explicável e resolução de equivalentes.",
        "O arquivo `services/pbev_service.py` só deve ser alterado na Etapa 2, mantendo este harness como",
        "critério de aceitação.",
        "",
        "## Comandos",
        "",
        "```bash",
        "python scripts/diagnosticar_matching_pbev_v45.py",
        "python scripts/diagnosticar_matching_pbev_v45.py --strict-target",
        "python -m pytest -q",
        "```",
        "",
        "O modo normal falha apenas diante de regressões inesperadas. O modo `--strict-target` também",
        "retorna erro enquanto qualquer lacuna conhecida da meta V45 continuar aberta.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(cases_path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service = PbevService(
        base_path=ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
        manifest_path=ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
    )
    cases = carregar_casos(cases_path)
    rows = [evaluate_case(service, case) for case in cases]
    summary = build_summary(rows)
    save_json_csv(rows, output_dir)
    save_summary(summary, output_dir)
    save_markdown(rows, summary, output_dir)
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico V45 do matching FIPE × PBEV/Inmetro.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--strict-target",
        action="store_true",
        help="Retorna erro também para lacunas conhecidas ainda abertas.",
    )
    args = parser.parse_args()

    rows, summary = run(args.input, args.output_dir)
    print(
        "Diagnóstico V45 concluído: "
        f"total={summary['casos_total']}; "
        f"protegidas_aprovadas={summary['regressoes_protegidas_aprovadas']}; "
        f"falhas_conhecidas={summary['falhas_conhecidas']}; "
        f"regressoes_inesperadas={summary['regressoes_inesperadas']}"
    )
    print(f"Saída: {args.output_dir}")

    if summary["regressoes_inesperadas"]:
        return 1
    if args.strict_target and summary["falhas_conhecidas"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
