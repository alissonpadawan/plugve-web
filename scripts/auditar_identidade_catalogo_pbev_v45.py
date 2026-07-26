#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pbev_service import PbevService  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs" / "auditoria_matching_v45_etapa2"


def _texto_registro(registro: dict[str, Any]) -> str:
    return " ".join(
        str(registro.get(chave) or "")
        for chave in (
            "modelo_normalizado", "modelo", "versao_normalizada", "versao_corrigida", "versao",
            "motor_normalizado", "motor_corrigido", "motor", "transmissao_normalizada", "transmissao",
        )
    ).strip()


def run(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    service = PbevService(
        base_path=ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
        manifest_path=ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
    )
    cache = service.carregar_base_pbev()
    atributos = Counter()
    por_propulsao = Counter()
    por_marca = Counter()
    falsos_tokens: list[dict[str, Any]] = []
    utilizaveis = 0

    for registro in cache.registros:
        flags_ok, _ = service.validar_flags_autofill(registro)
        if not flags_ok or not service.montar_sugestao_consumo(registro):
            continue
        utilizaveis += 1
        texto = _texto_registro(registro)
        identidade = service.extrair_identidade_tecnica(texto, {
            "marca": registro.get("marca_normalizada") or registro.get("marca"),
            "modelo": registro.get("modelo_normalizado") or registro.get("modelo"),
            "versao": registro.get("versao_normalizada") or registro.get("versao_corrigida") or registro.get("versao"),
            "motor": registro.get("motor_normalizado") or registro.get("motor_corrigido") or registro.get("motor"),
            "transmissao": registro.get("transmissao_normalizada") or registro.get("transmissao"),
            "combustivel": registro.get("combustivel_normalizado") or registro.get("combustivel"),
            "tipo_propulsao": registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao"),
            "ano": registro.get("ano_tabela"),
        })
        fortes = service.extrair_tokens_fortes_modelo(texto)
        indevidos = sorted(token for token in fortes if service._token_composto_apenas_tecnico(token))
        if indevidos:
            falsos_tokens.append({
                "id_pbev": registro.get("id_pbev") or registro.get("id_pbev_preliminar"),
                "marca": registro.get("marca"),
                "modelo": registro.get("modelo"),
                "versao": registro.get("versao"),
                "tokens": indevidos,
            })
        for campo in ("cilindrada", "valvulas", "turbo", "transmissao", "marchas", "tracao", "carroceria", "my"):
            valor = identidade.get(campo)
            if valor not in (None, "", [], set()):
                atributos[campo] += 1
        if identidade.get("tokens_familia") or identidade.get("palavras_familia"):
            atributos["familia"] += 1
        if identidade.get("acabamentos"):
            atributos["acabamento"] += 1
        por_propulsao[str(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao") or "INDEFINIDO")] += 1
        por_marca[str(registro.get("marca_normalizada") or registro.get("marca") or "INDEFINIDA")] += 1

    config = service._carregar_aliases_automotivos()
    summary = {
        "etapa": "V45 Etapa 2 — auditoria estrutural do catálogo PBEV",
        "registros_base": len(cache.registros),
        "registros_utilizaveis_auditados": utilizaveis,
        "aliases_versao": config.get("versao") or config.get("version"),
        "falsos_tokens_comerciais_apenas_tecnicos": len(falsos_tokens),
        "aprovado": not falsos_tokens,
        "cobertura_atributos": dict(sorted(atributos.items())),
        "registros_por_propulsao": dict(sorted(por_propulsao.items())),
        "marcas_auditadas": len(por_marca),
        "exemplos_falha": falsos_tokens[:50],
        "observacao": (
            "Esta auditoria valida o parser sobre os registros utilizáveis da base PBEV. "
            "Ela não substitui a regressão ponta a ponta com nomenclaturas FIPE."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "auditoria_identidade_catalogo_pbev_v45.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Auditoria estrutural da identidade automotiva — V45 Etapa 2",
        "",
        f"- Registros na base: **{summary['registros_base']}**.",
        f"- Registros utilizáveis auditados: **{utilizaveis}**.",
        f"- Marcas auditadas: **{summary['marcas_auditadas']}**.",
        f"- Tokens comerciais formados apenas por componentes técnicos: **{len(falsos_tokens)}**.",
        f"- Resultado: **{'APROVADO' if summary['aprovado'] else 'FALHA'}**.",
        "",
        "## Limite desta verificação",
        "",
        summary["observacao"],
    ]
    (output_dir / "auditoria_identidade_catalogo_pbev_v45.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita o parser de identidade em toda a base PBEV utilizável.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = run(args.output_dir)
    print(
        f"Identidade PBEV: {summary['registros_utilizaveis_auditados']} registros; "
        f"falsos_tokens_tecnicos={summary['falsos_tokens_comerciais_apenas_tecnicos']}"
    )
    print(f"Saída: {args.output_dir}")
    return 0 if summary["aprovado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
