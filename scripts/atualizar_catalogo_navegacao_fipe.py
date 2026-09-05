from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PLUGVE_PREWARM_FIPE", "0")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from services.fipe_service import FipeService


def _ler(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") == "catalogo_navegacao_fipe_v1" and isinstance(data.get("marcas"), dict):
            return data
    except Exception:
        pass
    return {}


def _salvar_atomico(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _item_novo(service: FipeService, marca: str, modelo: dict, decisao_temporal: dict) -> dict:
    nome = str(modelo.get("nome") or "")
    codigo = str(modelo.get("codigo") or "")
    decisao = service._catalog_classifier().classify(marca, nome)
    return {
        "codigo": codigo,
        "nome": nome,
        "tem_zero_km": bool(decisao_temporal.get("tem_zero_km_temporal")),
        "tipo_plugve": decisao.tipo_plugve,
        "contextos": sorted(decisao.contexts),
        "origem_classificacao": f"manutencao_{decisao.source}",
        "confianca_classificacao": round(float(decisao.confidence), 4),
        "ano_minimo": decisao_temporal.get("ano_minimo_elegivel"),
        "ano_maximo": decisao_temporal.get("ano_maximo_encontrado"),
        "origem_temporal": "fipe_anos_exato_manutencao",
    }


def _montar_contextos(itens: list[dict]) -> dict[str, list[dict]]:
    dep = sorted(itens, key=lambda m: str(m.get("nome") or "").casefold())
    ve = [copy.deepcopy(m) for m in dep if "ve" in set(m.get("contextos") or [])]
    icev = [copy.deepcopy(m) for m in dep if "icev" in set(m.get("contextos") or [])]
    return {"depreciacao": dep, "ve": ve, "icev": icev}


def atualizar(service: FipeService, destino: Path, checkpoint: Path) -> dict:
    ativo = _ler(destino)
    if not ativo:
        raise RuntimeError("Catálogo de navegação ativo ausente ou inválido.")

    build = _ler(checkpoint)
    if not build or build.get("base_atualizado_em") != ativo.get("atualizado_em"):
        build = copy.deepcopy(ativo)
        build["modo"] = "precompilado_offline_em_atualizacao"
        build["base_atualizado_em"] = ativo.get("atualizado_em")
        build["marcas_concluidas_manutencao"] = []

    concluidas = set(map(str, build.get("marcas_concluidas_manutencao") or []))
    catalogo_v2 = service._ler_catalogo_elegibilidade_v2()
    bloqueados = service._ler_bloqueados()
    marcas = service.listar_marcas_canonicas_carros()

    for pos, marca in enumerate(marcas, start=1):
        codigo_marca = str(marca.get("codigo") or "")
        nome_marca = str(marca.get("nome") or "")
        if not codigo_marca or codigo_marca in concluidas:
            continue
        print(f"[{pos}/{len(marcas)}] {codigo_marca} {nome_marca}", flush=True)

        atual = service.listar_modelos_canonicos_carros(codigo_marca).get("modelos", [])
        entrada_ativa = (ativo.get("marcas") or {}).get(codigo_marca) or {}
        existentes = {
            str(m.get("codigo")): copy.deepcopy(m)
            for m in (((entrada_ativa.get("modelos") or {}).get("depreciacao")) or [])
            if isinstance(m, dict) and m.get("codigo") is not None
        }
        v2_marca = ((catalogo_v2.get("marcas") or {}).get(codigo_marca) or {}).get("modelos") or {}
        bloqueados_marca = (bloqueados.get(codigo_marca) or {}) if isinstance(bloqueados, dict) else {}
        novos_consultados = 0

        saida_modelos: list[dict] = []
        for modelo in atual:
            codigo_modelo = str(modelo.get("codigo") or "")
            if not codigo_modelo:
                continue
            if codigo_modelo in existentes:
                item = existentes[codigo_modelo]
                item["nome"] = str(modelo.get("nome") or item.get("nome") or "")
                saida_modelos.append(item)
                continue
            if codigo_modelo in bloqueados_marca:
                continue
            previa = v2_marca.get(codigo_modelo) if isinstance(v2_marca, dict) else None
            if isinstance(previa, dict) and previa.get("elegivel") is False:
                continue

            anos = service.listar_anos_canonicos_carros(codigo_marca, codigo_modelo)
            decisao_temporal = service._decisao_temporal_por_anos(
                anos, marca=nome_marca, modelo=str(modelo.get("nome") or "")
            )
            novos_consultados += 1
            if not isinstance(decisao_temporal, dict) or not decisao_temporal.get("elegivel_2012_ou_zero_km"):
                continue
            saida_modelos.append(_item_novo(service, nome_marca, modelo, decisao_temporal))

        por_contexto = _montar_contextos(saida_modelos)
        build.setdefault("marcas", {})[codigo_marca] = {
            "marca": nome_marca,
            "modelos": por_contexto,
            "contagens": {k: len(v) for k, v in por_contexto.items()},
        }
        concluidas.add(codigo_marca)
        build["marcas_concluidas_manutencao"] = sorted(concluidas, key=lambda x: int(x) if x.isdigit() else x)
        build["atualizado_em_manutencao"] = service._agora_iso()
        _salvar_atomico(checkpoint, build)
        print(f"  {len(saida_modelos)} elegíveis; {novos_consultados} códigos novos verificados.", flush=True)

    build["modo"] = "precompilado_offline"
    build["atualizado_em"] = service._agora_iso()
    build.pop("base_atualizado_em", None)
    build.pop("marcas_concluidas_manutencao", None)
    build.pop("atualizado_em_manutencao", None)
    build["contagens"] = {
        "marcas": len(build.get("marcas") or {}),
        "modelos_depreciacao": sum(len((((b or {}).get("modelos") or {}).get("depreciacao")) or []) for b in (build.get("marcas") or {}).values()),
        "modelos_ve": sum(len((((b or {}).get("modelos") or {}).get("ve")) or []) for b in (build.get("marcas") or {}).values()),
        "modelos_icev": sum(len((((b or {}).get("modelos") or {}).get("icev")) or []) for b in (build.get("marcas") or {}).values()),
    }
    return build


def main() -> int:
    app = create_app()
    with app.app_context():
        service = FipeService()
        destino = service._catalogo_navegacao_path()
        checkpoint = destino.with_suffix(destino.suffix + ".build")
        print(f"Catálogo ativo: {destino}")
        print(f"Checkpoint: {checkpoint}")
        payload = atualizar(service, destino, checkpoint)
        # Só publica quando todas as marcas terminarem. Em 429/timeout/exceção,
        # o catálogo ativo anterior permanece intacto e o .build guarda progresso.
        _salvar_atomico(destino, payload)
        checkpoint.unlink(missing_ok=True)
        service._catalogo_navegacao_signature = None
        service._catalogo_navegacao_cache = None
        print(json.dumps(payload.get("contagens", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
