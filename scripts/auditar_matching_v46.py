from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Permite execução direta: python scripts/auditar_matching_v46.py
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pbev_service import PbevService  # noqa: E402


def _candidate_text(result: dict[str, Any]) -> str:
    candidate = result.get("candidato") or {}
    return " ".join(str(candidate.get(key) or "") for key in ("marca", "modelo", "versao")).upper()


def evaluate(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    expected = case.get("esperado") or {}
    failures: list[str] = []
    candidate = result.get("candidato") or {}
    candidate_text = _candidate_text(result)
    suggestions = result.get("sugestoes_consumo") or {}

    def check_equal(key: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            failures.append(f"{key}: esperado={wanted!r}; obtido={actual!r}")

    if "nivel_match" in expected:
        check_equal("nivel_match", result.get("nivel_match"), expected["nivel_match"])
    if "autopreencher" in expected:
        check_equal("autopreencher", result.get("autopreencher"), expected["autopreencher"])
    if expected.get("modelo_igual"):
        check_equal("modelo", str(candidate.get("modelo") or "").upper(), expected["modelo_igual"].upper())

    wanted = expected.get("modelo_contem") or expected.get("modelo_versao_contem")
    if wanted and wanted.upper() not in candidate_text:
        failures.append(f"candidato deveria conter {wanted!r}: {candidate_text!r}")
    for key in ("modelo_nao_contem", "candidato_nao_contem"):
        forbidden = expected.get(key)
        if forbidden and forbidden.upper() in candidate_text:
            failures.append(f"candidato não deveria conter {forbidden!r}: {candidate_text!r}")
    if expected.get("candidato_ausente") and candidate:
        failures.append(f"candidato deveria estar ausente: {candidate_text!r}")

    for key in (
        "gasolina_cidade_km_l",
        "etanol_cidade_km_l",
        "gasolina_diesel_cidade_km_l",
        "consumo_eletrico_kwh_km",
    ):
        if key in expected:
            actual = float(suggestions.get(key) or 0)
            wanted_value = float(expected[key])
            if abs(actual - wanted_value) > 1e-6:
                failures.append(f"{key}: esperado={wanted_value}; obtido={actual}")
    if expected.get("tipo_consumo"):
        check_equal("tipo_consumo", suggestions.get("tipo"), expected["tipo_consumo"])
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita a suíte real do matching multivisão FIPE × PBEV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "V46_RELATORIO_REGRESSAO_PACOTE_TESTE_01.json",
    )
    args = parser.parse_args()

    os.environ["PBEV_MATCHING_ENGINE"] = "v46"
    cases_path = ROOT / "data" / "pbev" / "casos_regressao_matching_v46.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    service = PbevService(
        base_path=ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
        manifest_path=ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
    )

    rows: list[dict[str, Any]] = []
    durations: list[float] = []
    for case in cases:
        started = time.perf_counter()
        result = service.sugerir_consumo(case["consulta"])
        elapsed_ms = (time.perf_counter() - started) * 1000
        durations.append(elapsed_ms)
        failures = evaluate(case, result)
        candidate = result.get("candidato") or {}
        rows.append({
            "id": case["id"],
            "origem_regressao": case.get("origem_regressao"),
            "ok": not failures,
            "falhas": failures,
            "tempo_ms": round(elapsed_ms, 3),
            "motor_matching": result.get("motor_matching"),
            "nivel_match": result.get("nivel_match"),
            "autopreencher": result.get("autopreencher"),
            "score": result.get("score"),
            "candidato": {
                "marca": candidate.get("marca"),
                "modelo": candidate.get("modelo"),
                "versao": candidate.get("versao"),
                "ano_tabela": candidate.get("ano_tabela"),
            } if candidate else None,
            "motivo": result.get("motivo"),
        })

    passed = sum(1 for row in rows if row["ok"])
    direct = sum(1 for row in rows if row.get("motor_matching") == "v46_multivisao")
    fallback = sum(1 for row in rows if str(row.get("motor_matching") or "").startswith("v44_fallback"))
    warm = durations[1:] if len(durations) > 1 else durations
    report = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "pacote": "V46 pacote de teste 01",
        "base": "V44 homologada",
        "casos": len(rows),
        "aprovados": passed,
        "reprovados": len(rows) - passed,
        "taxa_aprovacao": round(passed / len(rows), 6) if rows else 0,
        "decisoes_motor_multivisao": direct,
        "decisoes_fallback_v44": fallback,
        "latencia_ms": {
            "primeira_consulta_frio": round(durations[0], 3) if durations else None,
            "media_aquecida": round(statistics.fmean(warm), 3) if warm else None,
            "mediana_aquecida": round(statistics.median(warm), 3) if warm else None,
            "maxima_aquecida": round(max(warm), 3) if warm else None,
        },
        "resultados": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Casos: {len(rows)} | aprovados: {passed} | reprovados: {len(rows) - passed}")
    print(f"Motor multivisão: {direct} | fallback V44: {fallback}")
    print(f"Relatório: {args.output}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
