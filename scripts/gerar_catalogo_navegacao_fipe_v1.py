from __future__ import annotations

import argparse
import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fipe_catalog_classifier import FipeCatalogPropulsionClassifier
from services.tipo_veiculo_service import classificar_tipo_veiculo, tipo_permitido_no_contexto


def _norm(texto: Any) -> str:
    value = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


BRAND_ALIASES = {
    "chevrolet": "gm chevrolet",
    "volkswagen": "vw volkswagen",
}

# A análise de famílias registrou uma anomalia cadastral conhecida envolvendo
# marca_id=189. Estes IDs são Aston Martin e não podem herdar a marca BYD.
MODEL_BRAND_OVERRIDES = {
    "6906": "aston martin",
    "10560": "aston martin",
    "10561": "aston martin",
    "6907": "aston martin",
    "6341": "aston martin",
    "6909": "aston martin",
    "10642": "aston martin",
    "6343": "aston martin",
    "6345": "aston martin",
    "10183": "aston martin",
    "6342": "aston martin",
    "6908": "aston martin",
    "6346": "aston martin",
}

# Regra já homologada no site: Haval H6 PHEV35 pertence ao lado VE.
MODEL_PROPULSION_OVERRIDES = {
    "11794": ({"ve"}, "PHEV", "regra_haval_h6_phev35"),
}

EXPLICIT_PROPULSION = {
    "BEV": ({"ve"}, "EV_PURO"),
    "PHEV": ({"ve"}, "PHEV"),
    "HEV": ({"icev"}, "HEV_NAO_PLUGIN"),
    "MHEV": ({"icev"}, "HEV_NAO_PLUGIN"),
    "FLEX_GASOLINA": ({"icev"}, "COMBUSTAO"),
    "DIESEL": ({"icev"}, "COMBUSTAO"),
}

# Dois registros da varredura 02/09 ficaram sem anos por HTTP 500, mas foram
# confirmados posteriormente como RAV4 híbridos com anos-modelo 2019/2020.
# A exceção fica explícita e auditável; não existe fallback por nome no runtime.
TEMPORAL_MANUAL_CONFIRMED = {
    "10056": {"origem": "revisao_manual_confirmada", "observacao": "RAV4 HEV com ano-modelo >= 2012"},
    "10058": {"origem": "revisao_manual_confirmada", "observacao": "RAV4 HEV com ano-modelo >= 2012"},
}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_rows(source: Path) -> list[dict[str, str]]:
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as zf:
            with zf.open("mapa_familias_pais_curve.csv") as raw:
                return list(csv.DictReader(io.TextIOWrapper(raw, "utf-8-sig", newline=""), delimiter=";"))
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def _class_from_cached_v1(cached: dict, brand_id: str, model_id: str) -> dict | None:
    entry = (((cached.get("modelos") or {}).get(brand_id) or {}).get(model_id))
    if not isinstance(entry, dict) or not isinstance(entry.get("contextos"), list) or not entry.get("contextos"):
        return None
    return {
        "contextos": sorted({str(x) for x in entry.get("contextos") if str(x) in {"ve", "icev"}}),
        "tipo_plugve": str(entry.get("tipo_plugve") or "INDEFINIDO"),
        "origem_classificacao": str(entry.get("origem_classificacao") or "catalogo_v1_render"),
        "confianca_classificacao": entry.get("confianca_classificacao"),
        "score_pbev": entry.get("score_pbev"),
        "margem_pbev": entry.get("margem_pbev"),
    }


def build(source: Path, v2_seed: Path, render_cache: Path, destination: Path) -> dict:
    rows = _load_rows(source)
    v2 = _read_json(v2_seed, {})
    render_v1 = _read_json(render_cache / "catalogo_elegibilidade_fipe_v1.json", {})
    render_zero = _read_json(render_cache / "modelos_zero_km.json", {})

    brand_by_norm: dict[str, tuple[str, str]] = {}
    model_identity_v2: dict[str, tuple[str, str, str]] = {}
    for brand_id, brand in (v2.get("marcas") or {}).items():
        brand_name = str((brand or {}).get("marca") or "").strip()
        if brand_name:
            brand_by_norm[_norm(brand_name)] = (str(brand_id), brand_name)
        for model_id, model in ((brand or {}).get("modelos") or {}).items():
            model_identity_v2[str(model_id)] = (
                str(brand_id), brand_name, str((model or {}).get("modelo") or "").strip()
            )

    for alias, target in BRAND_ALIASES.items():
        if target in brand_by_norm:
            brand_by_norm[alias] = brand_by_norm[target]

    zero_ids = {
        str(model_id)
        for brand in (render_zero or {}).values()
        if isinstance(brand, dict)
        for model_id in brand
    }

    classifier = FipeCatalogPropulsionClassifier()
    brands: dict[str, dict] = {}
    excluded: list[dict] = []
    sources = Counter()

    for row in rows:
        model_id = str(row.get("modelo_id") or "").strip()
        csv_brand = str(row.get("marca") or "").strip()
        csv_model = str(row.get("modelo") or "").strip()

        # Quando o ID já existe no catálogo temporal anterior, a identidade FIPE
        # do próprio site vence. Isso também corrige a anomalia conhecida de
        # marca_id=189 no arquivo de agrupamento.
        identity = model_identity_v2.get(model_id)
        override_brand = MODEL_BRAND_OVERRIDES.get(model_id)
        if identity:
            brand_id, brand_name, model_name_v2 = identity
            model_name = model_name_v2 or csv_model
        else:
            key = override_brand or BRAND_ALIASES.get(_norm(csv_brand), _norm(csv_brand))
            mapped = brand_by_norm.get(key)
            if not mapped:
                excluded.append({"modelo_id": model_id, "marca": csv_brand, "modelo": csv_model, "motivo": "marca_sem_codigo_fipe"})
                continue
            brand_id, brand_name = mapped
            model_name = csv_model

        if not brand_name or not model_name:
            excluded.append({"modelo_id": model_id, "marca": brand_name or csv_brand, "modelo": model_name, "motivo": "identidade_incompleta"})
            continue

        zero_km = str(row.get("zero_km") or "").strip().upper() == "SIM" or model_id in zero_ids
        max_year_raw = str(row.get("maior_ano") or "").strip()
        min_year_raw = str(row.get("menor_ano") or "").strip()
        max_year = int(max_year_raw) if max_year_raw.isdigit() else None
        min_year = int(min_year_raw) if min_year_raw.isdigit() else None
        temporal_manual = TEMPORAL_MANUAL_CONFIRMED.get(model_id)
        eligible = bool(zero_km or (max_year is not None and max_year >= 2012) or temporal_manual)
        if not eligible:
            continue

        prop = str(row.get("propulsao_combustivel") or "").strip().upper()
        override_prop = MODEL_PROPULSION_OVERRIDES.get(model_id)
        explicit = EXPLICIT_PROPULSION.get(prop)
        if override_prop:
            contexts, tipo, origem = override_prop
            classification = {
                "contextos": sorted(contexts),
                "tipo_plugve": tipo,
                "origem_classificacao": origem,
                "confianca_classificacao": 1.0,
                "score_pbev": 0.0,
                "margem_pbev": 0.0,
            }
            sources["override_homologado"] += 1
        elif explicit:
            # A varredura recente contém a propulsão explicitamente estruturada.
            # Ela vence classificações antigas do cache (ex.: PHEV19/PHEV34).
            contexts, tipo = explicit
            classification = {
                "contextos": sorted(contexts),
                "tipo_plugve": tipo,
                "origem_classificacao": "mapa_familias_propulsao_explicita",
                "confianca_classificacao": 1.0,
                "score_pbev": 0.0,
                "margem_pbev": 0.0,
            }
            sources["mapa_explicito"] += 1
        else:
            classification = _class_from_cached_v1(render_v1, brand_id, model_id)
            if classification:
                sources["render_v1"] += 1
            elif prop == "COMBUSTAO_NAO_ESPECIFICADO":
                # Para a grande massa sem combustível explícito, preserva as regras
                # textuais/por marca já existentes no site sem acionar matching PBEV
                # pesado durante a geração. Casos com evidência VE/PHEV no próprio
                # nome/marca continuam indo ao lado VE; os demais permanecem ICEV.
                tipo = classificar_tipo_veiculo(model_name, marca=brand_name)
                if tipo_permitido_no_contexto("ve", tipo):
                    contexts = {"ve"}
                else:
                    contexts = {"icev"}
                classification = {
                    "contextos": sorted(contexts),
                    "tipo_plugve": tipo,
                    "origem_classificacao": "precompilado_classificacao_textual_atual",
                    "confianca_classificacao": 0.9,
                    "score_pbev": 0.0,
                    "margem_pbev": 0.0,
                }
                sources["classificacao_textual_atual"] += 1
            else:
                # Híbrido não especificado e qualquer caso realmente ambíguo usam
                # o mesmo classificador PBEV atual, mas somente na construção offline.
                decision = classifier.classify(brand_name, model_name)
                classification = decision.as_dict()
                classification["origem_classificacao"] = f"precompilado_{classification.get('origem_classificacao') or 'classificador_atual'}"
                sources["classificador_atual"] += 1

        contexts = [c for c in classification.get("contextos", []) if c in {"ve", "icev"}]
        if not contexts:
            # Segurança conservadora: o modelo continua na Depreciação, mas não
            # entra em um dos lados da Simular até nova manutenção offline.
            contexts = []

        item = {
            "codigo": model_id,
            "nome": model_name,
            "tem_zero_km": bool(zero_km),
            "tipo_plugve": classification.get("tipo_plugve"),
            "contextos": contexts,
            "origem_classificacao": classification.get("origem_classificacao"),
            "confianca_classificacao": classification.get("confianca_classificacao"),
            "ano_minimo": min_year,
            "ano_maximo": max_year,
            "origem_temporal": (
                "modelos_zero_km_render" if model_id in zero_ids and not max_year
                else str((temporal_manual or {}).get("origem") or "mapa_familias_pais_curve_20260902")
            ),
        }

        brand_entry = brands.setdefault(brand_id, {
            "marca": brand_name,
            "modelos": {"depreciacao": [], "ve": [], "icev": []},
        })
        brand_entry["modelos"]["depreciacao"].append(dict(item))
        for ctx in contexts:
            brand_entry["modelos"][ctx].append(dict(item))

    for brand in brands.values():
        for ctx, models in brand["modelos"].items():
            # IDs são a identidade; dedup defensivo e ordem textual estável.
            unique = {str(m["codigo"]): m for m in models}
            brand["modelos"][ctx] = sorted(unique.values(), key=lambda m: str(m.get("nome") or "").casefold())
        brand["contagens"] = {ctx: len(models) for ctx, models in brand["modelos"].items()}

    payload = {
        "schema_version": "catalogo_navegacao_fipe_v1",
        "modo": "precompilado_offline",
        "descricao": "Catálogo rápido para Simular e Depreciação; Fipe+ permanece integral via API FIPE.",
        "origem": {
            "mapa": source.name,
            "mapa_data": "2026-09-02",
            "cache_render": "fipe_cache real recuperado do Persistent Disk",
            "regra_temporal": "Zero km ou algum ano-modelo >= 2012",
        },
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "marcas": dict(sorted(brands.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0])),
        "contagens": {
            "marcas": len(brands),
            "modelos_depreciacao": sum(len(b["modelos"]["depreciacao"]) for b in brands.values()),
            "modelos_ve": sum(len(b["modelos"]["ve"]) for b in brands.values()),
            "modelos_icev": sum(len(b["modelos"]["icev"]) for b in brands.values()),
            "classificacao_fontes": dict(sources),
            "excluidos_identidade": len(excluded),
        },
        "excecoes_nao_publicadas": excluded,
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(destination)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera o catálogo pré-compilado de navegação FIPE da CurVE.")
    parser.add_argument("--source", required=True, help="ZIP da análise de famílias ou mapa_familias_pais_curve.csv")
    parser.add_argument("--render-cache", required=True, help="Diretório fipe_cache recuperado do Persistent Disk")
    parser.add_argument("--output", default=str(ROOT / "data" / "fipe_cache" / "catalogo_navegacao_fipe_v1.json"))
    args = parser.parse_args()
    payload = build(
        Path(args.source),
        ROOT / "data" / "fipe_cache" / "catalogo_elegibilidade_fipe_v2.json",
        Path(args.render_cache),
        Path(args.output),
    )
    print(json.dumps(payload["contagens"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
