from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pbev_service import PbevService


def candidate_text(result: dict[str, Any]) -> str:
    c = result.get("candidato") or {}
    return " ".join(str(c.get(k) or "") for k in ("marca", "modelo", "versao", "motor", "transmissao")).upper()


def validate(result: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("nivel_match", "autopreencher"):
        if key in expected and result.get(key) != expected[key]:
            errors.append(f"{key}: esperado={expected[key]!r}, obtido={result.get(key)!r}")
    if result.get("requer_confirmacao") or result.get("opcoes_confirmacao"):
        errors.append("fluxo de confirmação manual ainda ativo")
    if expected.get("candidato_ausente"):
        if result.get("candidato") is not None:
            errors.append("candidato deveria permanecer ausente")
        return errors
    text = candidate_text(result)
    if expected.get("modelo_igual"):
        model = str((result.get("candidato") or {}).get("modelo") or "").upper()
        if model != expected["modelo_igual"].upper():
            errors.append(f"modelo_igual: esperado={expected['modelo_igual']!r}, obtido={model!r}")
    if expected.get("modelo_versao_contem") and expected["modelo_versao_contem"].upper() not in text:
        errors.append(f"modelo_versao_contem: {expected['modelo_versao_contem']!r} não apareceu")
    if expected.get("candidato_nao_contem") and expected["candidato_nao_contem"].upper() in text:
        errors.append(f"candidato_nao_contem: {expected['candidato_nao_contem']!r} apareceu")
    suggestion = result.get("sugestoes_consumo") or {}
    if expected.get("tipo_consumo") and str(suggestion.get("tipo") or "").lower() != expected["tipo_consumo"].lower():
        errors.append(f"tipo_consumo: esperado={expected['tipo_consumo']!r}, obtido={suggestion.get('tipo')!r}")
    for key in ("gasolina_cidade_km_l", "etanol_cidade_km_l", "gasolina_diesel_cidade_km_l", "consumo_eletrico_kwh_km"):
        if key in expected:
            got = suggestion.get(key)
            if got is None or abs(float(got) - float(expected[key])) > 0.00001:
                errors.append(f"{key}: esperado={expected[key]!r}, obtido={got!r}")
    return errors


def run(cases_path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service = PbevService()
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = service.sugerir_consumo(dict(case["consulta"]))
        errors = validate(result, case["esperado"])
        c = result.get("candidato") or {}
        s = result.get("sugestoes_consumo") or {}
        rows.append({
            "id": case["id"],
            "aprovado": not errors,
            "erros": errors,
            "nivel_match": result.get("nivel_match"),
            "autopreencher": result.get("autopreencher"),
            "criterio_match": result.get("criterio_match"),
            "id_pbev": c.get("id_pbev"),
            "ano_tabela_pbev": c.get("ano_tabela"),
            "candidato": candidate_text(result),
            "tipo_consumo": s.get("tipo"),
            "gasolina_cidade_km_l": s.get("gasolina_cidade_km_l"),
            "etanol_cidade_km_l": s.get("etanol_cidade_km_l"),
            "gasolina_diesel_cidade_km_l": s.get("gasolina_diesel_cidade_km_l"),
            "consumo_eletrico_kwh_km": s.get("consumo_eletrico_kwh_km"),
            "requer_confirmacao": result.get("requer_confirmacao"),
            "opcoes_confirmacao": len(result.get("opcoes_confirmacao") or []),
        })
    summary = {
        "motor": "V2",
        "casos_total": len(rows),
        "casos_aprovados": sum(1 for r in rows if r["aprovado"]),
        "falhas": sum(1 for r in rows if not r["aprovado"]),
        "autofills": sum(1 for r in rows if r["autopreencher"]),
        "confirmacoes_manuais": sum(1 for r in rows if r["requer_confirmacao"] or r["opcoes_confirmacao"]),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "regressoes_reais_matching_v2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "resumo_regressoes_reais_matching_v2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = [
        "# Regressões reais — Motor PBEV V2", "",
        f"- Casos: **{summary['casos_total']}**",
        f"- Aprovados: **{summary['casos_aprovados']}**",
        f"- Falhas: **{summary['falhas']}**",
        f"- Autofills corretos esperados: **{summary['autofills']}**",
        f"- Confirmações manuais: **{summary['confirmacoes_manuais']}**", "",
    ]
    for row in rows:
        md.append(f"- {'✅' if row['aprovado'] else '❌'} `{row['id']}` — {row['nivel_match']} / autofill={row['autopreencher']} / {row['candidato'] or 'sem candidato'}")
        for error in row["erros"]:
            md.append(f"  - {error}")
    (output_dir / "regressoes_reais_matching_v2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "data" / "pbev" / "casos_regressao_matching_v2.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "auditoria_matching_v2")
    args = parser.parse_args()
    _, summary = run(args.cases, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["falhas"] == 0 else 1)


if __name__ == "__main__":
    main()
