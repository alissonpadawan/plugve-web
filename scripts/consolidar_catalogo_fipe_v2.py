from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# O consolidador é uma manutenção de catálogo, não um start normal do site.
# Evita aquecimentos paralelos enquanto a rotina usa a cota FIPE de forma controlada.
os.environ.setdefault("PLUGVE_PREWARM_FIPE", "0")

from app import create_app
from services.fipe_service import FipeService


def _normalizar_mes(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


def resolver_referencia(service: FipeService, override: str | None) -> str:
    if override:
        return str(override).strip()
    try:
        refs = service.listar_referencias()
        for ref in refs:
            mes = _normalizar_mes(ref.get("month"))
            if "2026" in mes and ("jun" in mes or "june" in mes):
                return str(ref.get("code"))
    except Exception:
        pass
    # Referência mensal identificada no ciclo da varredura de junho/2026.
    return "334"


def _decisao_exata(service: FipeService, codigo_marca: str, modelo: dict, nome_marca: str) -> dict:
    codigo_modelo = str(modelo.get("codigo") or "")
    anos = service.listar_anos_canonicos_carros(codigo_marca, codigo_modelo)
    decisao = service._decisao_temporal_por_anos(anos, marca=nome_marca, modelo=str(modelo.get("nome") or ""))
    if not isinstance(decisao, dict):
        raise RuntimeError(f"FIPE não retornou anos suficientes para {nome_marca} / {modelo.get('nome')} ({codigo_modelo}).")
    return {
        "elegivel": bool(decisao.get("elegivel_2012_ou_zero_km")),
        "tem_zero_km": bool(decisao.get("tem_zero_km_temporal")),
        "origem": "fipe_anos_exato_delta",
        "modelo": str(modelo.get("nome") or ""),
        "ano_minimo_elegivel": decisao.get("ano_minimo_elegivel"),
        "ano_maximo_encontrado": decisao.get("ano_maximo_encontrado"),
    }


def _payload_valido(payload: object) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == "catalogo_elegibilidade_fipe_v2"
        and isinstance(payload.get("marcas"), dict)
    )


def _ler_payload(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if _payload_valido(payload) else None
    except Exception:
        return None


def _salvar_checkpoint(path: Path, payload: dict) -> None:
    """Salva progresso fora do catálogo ativo.

    O site nunca lê o arquivo .build. Assim uma execução interrompida/429 não
    publica uma allowlist parcial. Ao executar novamente, a rotina retoma as
    marcas já concluídas.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _base_de_trabalho(destino: Path, checkpoint: Path, referencia: str, service: FipeService) -> dict:
    # Preferência: checkpoint da execução interrompida; depois catálogo ativo.
    # O catálogo ativo pode ser o baseline legacy ou uma allowlist exata anterior.
    base = _ler_payload(checkpoint) or _ler_payload(destino) or {}
    marcas = dict(base.get("marcas") or {}) if isinstance(base, dict) else {}
    return {
        "schema_version": "catalogo_elegibilidade_fipe_v2",
        "modo": "allowlist_exata_em_consolidacao",
        "referencia_varredura": str(referencia),
        "marcas": marcas,
        "atualizado_em": service._agora_iso(),
    }


def construir(service: FipeService, referencia: str, *, destino: Path, checkpoint: Path) -> dict:
    varridas = service._ler_marcas_varridas()
    marcas_bloqueadas = service._ler_marcas_bloqueadas()
    bloqueados = service._ler_bloqueados()
    zero_km = service._ler_modelos_zero_km()
    marcas_atuais = {str(m.get("codigo")): m for m in service.listar_marcas_canonicas_carros()}

    codigos_marcas = sorted(
        set(marcas_atuais) | set(varridas) | set(marcas_bloqueadas),
        key=lambda x: int(x) if str(x).isdigit() else str(x),
    )
    saida = _base_de_trabalho(destino, checkpoint, referencia, service)

    for pos, codigo_marca in enumerate(codigos_marcas, start=1):
        marca_atual = marcas_atuais.get(codigo_marca) or {}
        entrada_varredura = varridas.get(codigo_marca) if isinstance(varridas.get(codigo_marca), dict) else {}
        entrada_bloqueada = marcas_bloqueadas.get(codigo_marca) if isinstance(marcas_bloqueadas.get(codigo_marca), dict) else {}
        nome_marca = str(marca_atual.get("nome") or entrada_varredura.get("marca") or entrada_bloqueada.get("marca") or "")
        anterior = saida.get("marcas", {}).get(codigo_marca)
        anterior = anterior if isinstance(anterior, dict) else {}
        decisoes_anteriores = anterior.get("modelos") if isinstance(anterior.get("modelos"), dict) else {}
        print(f"[{pos}/{len(codigos_marcas)}] {codigo_marca} {nome_marca}", flush=True)

        if codigo_marca in marcas_bloqueadas:
            saida["marcas"][codigo_marca] = {
                "marca": nome_marca,
                "status": "bloqueada",
                "modelos": {},
                "origem": "varredura_render",
            }
            saida["atualizado_em"] = service._agora_iso()
            _salvar_checkpoint(checkpoint, saida)
            continue

        modelos_atuais = service.listar_modelos_canonicos_carros(codigo_marca).get("modelos", [])
        atuais_por_id = {str(m.get("codigo")): m for m in modelos_atuais if m.get("codigo") is not None}
        ids_atuais = set(atuais_por_id)

        # Se a marca já foi consolidada exatamente e a API não mudou seus códigos,
        # não há motivo para consultar histórico nem anos novamente.
        if anterior.get("status") == "completo" and set(decisoes_anteriores) == ids_atuais:
            print(f"  já consolidada ({len(ids_atuais)} modelos); sem alteração na FIPE.", flush=True)
            continue

        bloqueados_marca = bloqueados.get(codigo_marca, {}) if isinstance(bloqueados.get(codigo_marca), dict) else {}
        zero_marca = zero_km.get(codigo_marca, {}) if isinstance(zero_km.get(codigo_marca), dict) else {}

        # Em uma manutenção futura, uma allowlist completa anterior é a melhor
        # referência: preserva decisões já comprovadas e verifica somente códigos novos.
        baseline_exato_anterior = anterior.get("status") == "completo"
        baseline_ids: set[str] = set()
        baseline_confiavel = False
        if not baseline_exato_anterior and codigo_marca in varridas:
            try:
                historicos = service.listar_modelos_referencia(codigo_marca, referencia).get("modelos", [])
                baseline_ids = {str(m.get("codigo")) for m in historicos if m.get("codigo") is not None}
                esperado = int(entrada_varredura.get("modelos_validos") or 0) + int(entrada_varredura.get("modelos_bloqueados") or 0)
                baseline_confiavel = bool(baseline_ids) and (esperado <= 0 or len(baseline_ids) == esperado)
                if not baseline_confiavel:
                    print(
                        f"  referência {referencia} não reproduziu o total da varredura "
                        f"(esperado={esperado}, encontrado={len(baseline_ids)}); verificando a marca inteira por anos.",
                        flush=True,
                    )
            except Exception as exc:
                print(f"  histórico indisponível ({exc}); verificando a marca inteira por anos.", flush=True)

        decisoes: dict[str, dict] = {}
        for codigo_modelo, modelo in atuais_por_id.items():
            # Decisão exata de catálogo completo anterior: reaproveita sem nova chamada.
            previa = decisoes_anteriores.get(codigo_modelo)
            if baseline_exato_anterior and isinstance(previa, dict) and isinstance(previa.get("elegivel"), bool):
                decisao = dict(previa)
                decisao["modelo"] = str(modelo.get("nome") or decisao.get("modelo") or "")
                decisoes[codigo_modelo] = decisao
                continue

            if codigo_modelo in bloqueados_marca:
                e = bloqueados_marca[codigo_modelo]
                decisoes[codigo_modelo] = {
                    "elegivel": False,
                    "origem": "modelos_bloqueados",
                    "modelo": str((e or {}).get("modelo") or modelo.get("nome") or ""),
                    "motivo": str((e or {}).get("motivo") or "sem_ano_2012_ou_zero_km"),
                }
                continue
            if codigo_modelo in zero_marca:
                e = zero_marca[codigo_modelo]
                decisoes[codigo_modelo] = {
                    "elegivel": True,
                    "tem_zero_km": True,
                    "origem": "modelos_zero_km",
                    "modelo": str((e or {}).get("modelo") or modelo.get("nome") or ""),
                }
                continue
            if baseline_confiavel and codigo_modelo in baseline_ids:
                # A varredura histórica percorreu todos os modelos daquela referência;
                # se o código não está na denylist, ele foi aprovado.
                decisoes[codigo_modelo] = {
                    "elegivel": True,
                    "origem": "varredura_render_jun2026",
                    "modelo": str(modelo.get("nome") or ""),
                }
                continue

            # Código que não existia no baseline (ou marca cujo histórico não pôde
            # ser reconciliado): decisão exata pelo endpoint de anos atual.
            decisoes[codigo_modelo] = _decisao_exata(service, codigo_marca, modelo, nome_marca)

        saida["marcas"][codigo_marca] = {
            "marca": nome_marca,
            "status": "completo",
            "modelos": decisoes,
            "origem": (
                "allowlist_anterior+delta_fipe_exato"
                if baseline_exato_anterior
                else "varredura_render+delta_fipe_exato"
                if baseline_confiavel
                else "fipe_anos_exato_completo"
            ),
            "modelos_atuais": len(atuais_por_id),
            "modelos_elegiveis": sum(1 for x in decisoes.values() if x.get("elegivel") is True),
            "modelos_inelegiveis": sum(1 for x in decisoes.values() if x.get("elegivel") is False),
        }
        saida["atualizado_em"] = service._agora_iso()
        _salvar_checkpoint(checkpoint, saida)

    saida["modo"] = "allowlist_exata"
    saida["atualizado_em"] = service._agora_iso()
    _salvar_checkpoint(checkpoint, saida)
    return saida


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolida o catálogo temporal FIPE v2 fora da interação do usuário.")
    parser.add_argument("--reference", default=None, help="Código da referência FIPE da varredura histórica (ex.: 334).")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        service = FipeService()
        referencia = resolver_referencia(service, args.reference)
        destino = service._catalogo_elegibilidade_v2_path()
        temporario = destino.with_suffix(destino.suffix + ".build")
        print(f"Referência-base: {referencia}")
        print(f"Destino: {destino}")
        print(f"Checkpoint: {temporario}")
        payload = construir(service, referencia, destino=destino, checkpoint=temporario)
        # Publicação atômica: somente um catálogo 100% consolidado substitui o ativo.
        temporario.replace(destino)
        service._invalidar_filtered_model_cache()
        total = sum(len((m or {}).get("modelos", {})) for m in payload.get("marcas", {}).values())
        elegiveis = sum(
            1
            for m in payload.get("marcas", {}).values()
            for e in (m or {}).get("modelos", {}).values()
            if isinstance(e, dict) and e.get("elegivel") is True
        )
        print(f"Catálogo concluído: {len(payload.get('marcas', {}))} marcas, {total} modelos, {elegiveis} elegíveis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
