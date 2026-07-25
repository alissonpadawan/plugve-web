#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pbev_service import PbevService  # noqa: E402


def _texto_candidato(resultado: dict[str, Any]) -> str:
    candidato = resultado.get("candidato") or {}
    return " ".join(str(candidato.get(k) or "") for k in ("modelo", "versao")).upper().strip()


def _valor_consumo(resultado: dict[str, Any], campo: str) -> Any:
    return (resultado.get("sugestoes_consumo") or {}).get(campo)


def validar_expectativa(resultado: dict[str, Any], esperado: dict[str, Any]) -> list[str]:
    erros: list[str] = []
    candidato = resultado.get("candidato") or {}
    texto_candidato = _texto_candidato(resultado)
    checks_diretos = ("nivel_match", "autopreencher", "criterio_match", "cobertura_pbev", "ano_tabela_pbev")
    for chave in checks_diretos:
        if chave in esperado and resultado.get(chave) != esperado[chave]:
            erros.append(f"{chave}: esperado={esperado[chave]!r}, obtido={resultado.get(chave)!r}")
    if "modelo_igual" in esperado and str(candidato.get("modelo") or "").upper() != str(esperado["modelo_igual"]).upper():
        erros.append(f"modelo_igual: esperado={esperado['modelo_igual']!r}, obtido={candidato.get('modelo')!r}")
    if "modelo_contem" in esperado and str(esperado["modelo_contem"]).upper() not in str(candidato.get("modelo") or "").upper():
        erros.append(f"modelo_contem: {esperado['modelo_contem']!r} não está em {candidato.get('modelo')!r}")
    if "modelo_versao_contem" in esperado and str(esperado["modelo_versao_contem"]).upper() not in texto_candidato:
        erros.append(f"modelo_versao_contem: {esperado['modelo_versao_contem']!r} não está em {texto_candidato!r}")
    if "modelo_nao_contem" in esperado and str(esperado["modelo_nao_contem"]).upper() in texto_candidato:
        erros.append(f"modelo_nao_contem: {esperado['modelo_nao_contem']!r} apareceu em {texto_candidato!r}")
    if "tipo_consumo" in esperado and _valor_consumo(resultado, "tipo") != esperado["tipo_consumo"]:
        erros.append(f"tipo_consumo: esperado={esperado['tipo_consumo']!r}, obtido={_valor_consumo(resultado, 'tipo')!r}")
    for campo in (
        "gasolina_cidade_km_l", "etanol_cidade_km_l", "diesel_cidade_km_l",
        "gasolina_diesel_cidade_km_l", "consumo_eletrico_kwh_km",
    ):
        if campo in esperado:
            obtido = _valor_consumo(resultado, campo)
            if obtido is None or abs(float(obtido) - float(esperado[campo])) > 1e-6:
                erros.append(f"{campo}: esperado={esperado[campo]!r}, obtido={obtido!r}")
    return erros


def validar_invariantes(resultado: dict[str, Any]) -> list[str]:
    """Detecta falhas gerais mesmo quando o caso não traz expectativa manual."""
    erros: list[str] = []
    diagnostico = resultado.get("diagnostico") or {}
    candidatos = ((resultado.get("debug") or {}).get("candidatos_top") or [])

    if not resultado.get("autopreencher"):
        cobertura_forte = [
            c for c in candidatos
            if c.get("flags_ok")
            and c.get("fuel_ok")
            and c.get("tem_sugestao_consumo")
            and c.get("ano_compativel_fipe_pbev")
            and c.get("tecnica_suficiente_para_consumo")
            and float(c.get("modelo_score") or 0) >= 30
            and not c.get("token_forte_divergente")
            and not c.get("familia_textual_divergente")
        ]
        if cobertura_forte and not diagnostico.get("ambiguidade_proxima"):
            erros.append("há candidato PBEV tecnicamente suficiente e não ambíguo, mas o consumo não foi autopreenchido")

    if resultado.get("autopreencher"):
        if not resultado.get("sugestoes_consumo"):
            erros.append("autopreencher=true sem sugestão de consumo")
        if diagnostico.get("ambiguidade_proxima"):
            erros.append("autopreencher=true com ambiguidade técnica ainda aberta")
        if candidatos:
            top = candidatos[0]
            if top.get("token_forte_divergente") or top.get("familia_textual_divergente"):
                erros.append("autopreenchimento selecionou candidato com família/modelo divergente")

    criterio = resultado.get("criterio_match")
    if criterio == "conservador_por_familia":
        sugestao = resultado.get("sugestoes_consumo") or {}
        if not sugestao.get("criterio_conservador_versoes_compativeis"):
            erros.append("critério conservador sem memória explícita das versões/família consideradas")

    return erros


def carregar_casos(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("O arquivo JSON deve conter uma lista de casos.")
        return data
    if path.suffix.lower() == ".csv":
        casos: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for idx, row in enumerate(csv.DictReader(f), 1):
                consulta = {k: v for k, v in row.items() if k not in {"id"} and v not in (None, "")}
                for campo in ("ano",):
                    if campo in consulta:
                        try:
                            consulta[campo] = int(consulta[campo])
                        except ValueError:
                            pass
                casos.append({"id": row.get("id") or f"linha_{idx}", "consulta": consulta, "esperado": {}})
        return casos
    raise ValueError("Formato aceito: JSON ou CSV.")


def consulta_sintetica_pbev(registro: dict[str, Any]) -> dict[str, Any]:
    ano = int(registro.get("ano_tabela") or 0)
    marca = registro.get("marca_normalizada") or registro.get("marca")
    modelo = " ".join(str(registro.get(k) or "") for k in ("modelo", "versao", "motor", "transmissao")).strip()
    combustivel = registro.get("combustivel_normalizado") or registro.get("combustivel")
    propulsao = registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao")
    return {
        "prefixo": "ve" if str(propulsao).upper() in {"ELETRICO", "PLUG_IN"} else "icev",
        "marca": marca,
        "modelo": modelo,
        "texto_modelo": modelo,
        "ano": ano,
        "ano_codigo": f"{ano}-1" if ano else "",
        "texto_ano": f"{ano} {combustivel}" if ano else str(combustivel or ""),
        "combustivel": combustivel,
        "tipo_veiculo": propulsao,
    }


def executar_self_audit(service: PbevService, *, limite: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    cache = service.carregar_base_pbev()
    vistos: set[str] = set()
    linhas: list[dict[str, Any]] = []
    for registro in cache.registros:
        ok_flags, _ = service.validar_flags_autofill(registro)
        if not ok_flags or not service.montar_sugestao_consumo(registro):
            continue
        chave = str(registro.get("chave_tecnica_normalizada") or registro.get("id_pbev_preliminar") or "")
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        if offset > 0:
            offset -= 1
            continue
        consulta = consulta_sintetica_pbev(registro)
        resultado = service.sugerir_consumo(consulta)
        texto_esperado = " ".join(str(registro.get(k) or "") for k in ("modelo", "versao"))
        texto_obtido = _texto_candidato(resultado)
        esperado_fortes = service.extrair_tokens_fortes_modelo(texto_esperado)
        obtido_fortes = service.extrair_tokens_fortes_modelo(texto_obtido)
        palavras_esperadas = service._palavras_familia_modelo(texto_esperado)
        palavras_obtidas = service._palavras_familia_modelo(texto_obtido)
        norm_esperado = service.normalizar_aliases_automotivos(registro.get("modelo"))
        norm_obtido = service.normalizar_aliases_automotivos(texto_obtido)
        familia_ok = (
            bool(esperado_fortes & obtido_fortes)
            if esperado_fortes
            else bool(palavras_esperadas & palavras_obtidas) or bool(norm_esperado and norm_esperado in norm_obtido)
        )
        passou = bool(resultado.get("autopreencher") and familia_ok)
        linhas.append({
            "id": chave,
            "passou": passou,
            "nivel_match": resultado.get("nivel_match"),
            "criterio_match": resultado.get("criterio_match"),
            "marca": consulta.get("marca"),
            "modelo_consulta": consulta.get("modelo"),
            "candidato": _texto_candidato(resultado),
            "motivo": resultado.get("motivo"),
        })
        if limite and len(linhas) >= limite:
            break
    return linhas


def salvar_resultados(linhas: Iterable[dict[str, Any]], destino_json: Path, destino_csv: Path) -> None:
    dados = list(linhas)
    destino_json.parent.mkdir(parents=True, exist_ok=True)
    destino_json.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    campos = sorted({k for linha in dados for k in linha.keys()}) if dados else ["id", "passou"]
    with destino_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(dados)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita o matching FIPE × PBEV/Inmetro.")
    parser.add_argument("--input", type=Path, default=ROOT / "data/pbev/casos_regressao_matching_v42.json")
    parser.add_argument("--self-audit", action="store_true", help="Audita registros válidos da própria base PBEV.")
    parser.add_argument("--limit", type=int, default=None, help="Limita o self-audit para execução rápida.")
    parser.add_argument("--offset", type=int, default=0, help="Pula N registros válidos únicos antes do self-audit; útil para execução em lotes.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/_runtime")
    args = parser.parse_args()

    service = PbevService(
        base_path=ROOT / "data/pbev/pbev_base_saneada_v1.json",
        manifest_path=ROOT / "data/pbev/pbev_manifest_validacao_v1.json",
    )

    linhas: list[dict[str, Any]] = []
    falhas = 0
    for caso in carregar_casos(args.input):
        resultado = service.sugerir_consumo(caso.get("consulta") or {})
        erros = validar_expectativa(resultado, caso.get("esperado") or {})
        erros.extend(validar_invariantes(resultado))
        passou = not erros
        falhas += 0 if passou else 1
        linhas.append({
            "id": caso.get("id"),
            "passou": passou,
            "nivel_match": resultado.get("nivel_match"),
            "autopreencher": resultado.get("autopreencher"),
            "criterio_match": resultado.get("criterio_match"),
            "cobertura_pbev": resultado.get("cobertura_pbev"),
            "candidato": _texto_candidato(resultado),
            "erros": " | ".join(erros),
            "motivo": resultado.get("motivo"),
        })

    if args.self_audit:
        self_linhas = executar_self_audit(service, limite=args.limit, offset=max(0, args.offset))
        falhas += sum(1 for linha in self_linhas if not linha["passou"])
        linhas.extend({"id": f"self::{linha['id']}", **linha} for linha in self_linhas)

    destino_json = args.output_dir / "auditoria_matching_pbev_v42.json"
    destino_csv = args.output_dir / "auditoria_matching_pbev_v42.csv"
    salvar_resultados(linhas, destino_json, destino_csv)

    aprovados = sum(1 for linha in linhas if linha.get("passou"))
    print(f"Auditoria concluída: {aprovados}/{len(linhas)} aprovados; falhas={falhas}")
    print(f"JSON: {destino_json}")
    print(f"CSV:  {destino_csv}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
