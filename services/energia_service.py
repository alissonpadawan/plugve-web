from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from services.text_utils import normalizar_texto

BASE_DIR = Path(__file__).resolve().parents[1]
CAMINHO_MUNICIPIOS = BASE_DIR / "data" / "municipios.xlsx"

ANEEL_DATASTORE_URL = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search"
ANEEL_RESOURCE_ID = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"

MAPA_SIGAGENTE_EXATO = {
    "CPFL SANTA CRUZ": "CPFL Santa Cruz",
    "NEOENERGIA BRASILIA": "Neoenergia Brasília",
    "NEOENERGIA PE": "Neoenergia PE",
    "CERACA": "Ceraçá",
    "CERIPA": "CERIPa",
    "EQUATORIAL GO": "Equatorial GO",
    "EQUATORIAL GOIAS": "Equatorial GO",
    "EQUATORIAL GOIÁS": "Equatorial GO",
}

# Fallback controlado para não deixar a calculadora travar quando a API da ANEEL falhar.
# Estes valores são apenas estimativas iniciais por UF, usados somente se a consulta online não retornar.
TARIFA_FALLBACK_UF = {
    "AC": 0.95, "AL": 0.88, "AP": 0.78, "AM": 0.88, "BA": 0.91,
    "CE": 0.86, "DF": 0.84, "ES": 0.82, "GO": 0.86, "MA": 0.83,
    "MT": 0.89, "MS": 0.84, "MG": 0.90, "PA": 0.93, "PB": 0.84,
    "PR": 0.82, "PE": 0.87, "PI": 0.86, "RJ": 0.98, "RN": 0.86,
    "RS": 0.88, "RO": 0.85, "RR": 0.78, "SC": 0.78, "SP": 0.82,
    "SE": 0.88, "TO": 0.83,
}


def _normalizar(s: Any) -> str:
    return normalizar_texto(s).upper()


def _conv(num: Any) -> float:
    try:
        return float(str(num).replace(",", "."))
    except Exception:
        return 0.0


def _parse_valor_monetario(v: Any) -> float:
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0


def _parse_data_aneel(v: Any):
    if not v:
        return None
    s = str(v).strip()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    try:
        return datetime.strptime(s[:10], "%d/%m/%Y").date()
    except Exception:
        return None


@lru_cache(maxsize=1)
def carregar_df_municipios() -> Optional[pd.DataFrame]:
    if not CAMINHO_MUNICIPIOS.exists():
        print("[MUNICIPIOS] Arquivo não encontrado:", CAMINHO_MUNICIPIOS)
        return None
    try:
        df = pd.read_excel(CAMINHO_MUNICIPIOS)
    except Exception as exc:
        print("[MUNICIPIOS] Erro ao abrir planilha:", exc)
        return None

    col_dist = col_mun = col_uf = None
    for c in df.columns:
        c_norm = _normalizar(c)
        if c_norm == "DISTRIBUIDORA":
            col_dist = c
        elif c_norm == "MUNICIPIO":
            col_mun = c
        elif c_norm in {"ESTADO", "UF"}:
            col_uf = c

    if col_dist is None and "Distribuidora" in df.columns:
        col_dist = "Distribuidora"
    if col_mun is None:
        if "Município" in df.columns:
            col_mun = "Município"
        elif "Municipio" in df.columns:
            col_mun = "Municipio"
    if col_uf is None and "Estado" in df.columns:
        col_uf = "Estado"

    if not all([col_dist, col_mun, col_uf]):
        print("[MUNICIPIOS] Colunas esperadas não encontradas:", list(df.columns))
        return None

    df["UF"] = df[col_uf].astype(str).str.upper().str.strip()
    df["MunicipioNorm"] = df[col_mun].astype(str).map(_normalizar)
    df["DistribuidoraRaw"] = df[col_dist].astype(str).str.strip()
    print("[MUNICIPIOS] Planilha carregada. Linhas:", len(df))
    return df


def obter_distribuidora_por_municipio(uf: str, municipio: str) -> Optional[str]:
    df = carregar_df_municipios()
    if df is None:
        return None
    uf = (uf or "").upper().strip()
    municipio_norm = _normalizar(municipio)
    df_uf = df[df["UF"] == uf]
    if df_uf.empty:
        return None

    df_mun = df_uf[df_uf["MunicipioNorm"] == municipio_norm]
    if df_mun.empty:
        df_mun = df_uf[df_uf["MunicipioNorm"].str.contains(municipio_norm, na=False)]
    if df_mun.empty:
        return None
    return str(df_mun.iloc[0]["DistribuidoraRaw"]).strip()


@lru_cache(maxsize=1)
def carregar_impostos_uf() -> dict[str, dict[str, float]]:
    if not CAMINHO_MUNICIPIOS.exists():
        return {}
    try:
        df = pd.read_excel(CAMINHO_MUNICIPIOS)
    except Exception:
        return {}

    col_alvo = None
    for c in df.columns:
        if _normalizar(c) == _normalizar("estado,icms,pis,cofins"):
            col_alvo = c
            break
    if col_alvo is None:
        return {}

    mapa: dict[str, dict[str, float]] = {}
    for v in df[col_alvo].dropna().astype(str).tolist():
        parts = [p.strip() for p in v.split(",")]
        if len(parts) < 4:
            continue
        uf = parts[0].upper()
        if uf == "ESTADO":
            continue
        mapa[uf] = {"icms": _conv(parts[1]), "pis": _conv(parts[2]), "cofins": _conv(parts[3])}
    return mapa


def obter_impostos_por_uf(uf: str) -> dict[str, float]:
    return carregar_impostos_uf().get((uf or "").upper().strip(), {"icms": 0.0, "pis": 0.0, "cofins": 0.0})


def mapear_para_sigagente(nome_distribuidora: str) -> str:
    if not nome_distribuidora:
        return ""
    base = _normalizar(nome_distribuidora)
    return MAPA_SIGAGENTE_EXATO.get(base, base)



def _aneel_datastore_search(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Consulta o CKAN da ANEEL usando datastore_search.

    Motivo: o endpoint datastore_search_sql retornava erro 400 em algumas consultas.
    O datastore_search com payload JSON evita montar SQL manual e é mais estável.
    """
    try:
        resp = requests.post(ANEEL_DATASTORE_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            print("[ANEEL] datastore_search sem success:", data)
            return None
        return data
    except Exception as exc:
        print("[ANEEL] Erro no datastore_search POST:", exc)

    # Fallback com GET, caso algum ambiente bloqueie POST.
    try:
        import json
        params = dict(payload)
        if isinstance(params.get("filters"), dict):
            params["filters"] = json.dumps(params["filters"], ensure_ascii=False)
        resp = requests.get(ANEEL_DATASTORE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            print("[ANEEL] datastore_search GET sem success:", data)
            return None
        return data
    except Exception as exc:
        print("[ANEEL] Erro no datastore_search GET:", exc)
        return None


def sugerir_sigagente_aneel(sig_digitado: str, limit: int = 25) -> list[str]:
    s = (sig_digitado or "").strip()
    if not s:
        return []

    payload = {
        "resource_id": ANEEL_RESOURCE_ID,
        "limit": int(limit),
        "q": s,
    }
    data = _aneel_datastore_search(payload)
    if not data:
        return []

    out = []
    for rec in data.get("result", {}).get("records", []):
        sig = rec.get("SigAgente")
        if sig:
            out.append(str(sig).strip())

    unicos = []
    vistos = set()
    for x in out:
        if x not in vistos:
            unicos.append(x)
            vistos.add(x)
    return unicos


def _filtrar_registros_aneel(records: list[dict[str, Any]], sig: str) -> list[dict[str, Any]]:
    def n(valor: Any) -> str:
        return _normalizar(valor)

    sig_norm = n(sig)
    saida = []
    for rec in records:
        if n(rec.get("SigAgente")) != sig_norm:
            continue
        if n(rec.get("DscSubGrupo")) != "B1":
            continue
        if n(rec.get("DscClasse")) != "RESIDENCIAL":
            continue
        if n(rec.get("DscModalidadeTarifaria")) != "CONVENCIONAL":
            continue
        if n(rec.get("DscSubClasse")) != "RESIDENCIAL":
            continue
        saida.append(rec)
    return saida


def obter_tarifa_energia_por_distribuidora(nome_distribuidora: str) -> Optional[dict[str, Any]]:
    """
    Consulta a tarifa residencial B1 na base aberta da ANEEL usando datastore_search.

    Retorna TUSD + TE em R$/kWh. Depois, a função obter_tarifa_energia aplica
    ICMS, PIS e COFINS da planilha municipios.xlsx.
    """
    sig = mapear_para_sigagente(nome_distribuidora)
    if not sig:
        return None

    payload = {
        "resource_id": ANEEL_RESOURCE_ID,
        "limit": 500,
        "filters": {
            "SigAgente": sig,
            "DscSubGrupo": "B1",
            "DscClasse": "Residencial",
            "DscModalidadeTarifaria": "Convencional",
            "DscSubClasse": "Residencial",
        },
    }

    data = _aneel_datastore_search(payload)
    records = data.get("result", {}).get("records", []) if data else []

    # Fallback: alguns CKANs são sensíveis a acento/caixa em filters.
    # Se não vier nada, busca textual pelo agente e filtra em Python.
    if not records:
        payload_q = {
            "resource_id": ANEEL_RESOURCE_ID,
            "limit": 5000,
            "q": sig,
        }
        data_q = _aneel_datastore_search(payload_q)
        records_q = data_q.get("result", {}).get("records", []) if data_q else []
        records = _filtrar_registros_aneel(records_q, sig)

    if not records:
        sugestoes = sugerir_sigagente_aneel(sig)
        if sugestoes:
            print(f"[ANEEL] Sem registros exatos para {sig}. Sugestões:", sugestoes)
        else:
            print(f"[ANEEL] Sem registros para {sig}.")
        return None

    def n(valor: Any) -> str:
        return _normalizar(valor)

    bases_preferidas = {"TARIFA DE APLICACAO", "BASE ECONOMICA"}
    filtrados = [r for r in records if n(r.get("DscBaseTarifaria")) in bases_preferidas]
    if not filtrados:
        filtrados = records

    def prioridade_base(r):
        base = n(r.get("DscBaseTarifaria"))
        if base == "TARIFA DE APLICACAO":
            return 0
        if base == "BASE ECONOMICA":
            return 1
        return 2

    def prioridade_detalhe(r):
        det = n(r.get("DscDetalhe"))
        return 0 if det == "NAO SE APLICA" else 1

    hoje = date.today()
    candidatos = []
    for rec in filtrados:
        unidade = str(rec.get("DscUnidadeTerciaria") or "").strip().upper()
        tusd = _parse_valor_monetario(rec.get("VlrTUSD"))
        te = _parse_valor_monetario(rec.get("VlrTE"))
        if tusd <= 0 and te <= 0:
            continue
        if unidade not in {"MWH", "KWH"}:
            continue

        di = _parse_data_aneel(rec.get("DatInicioVigencia"))
        df = _parse_data_aneel(rec.get("DatFimVigencia"))
        vigente = (di <= hoje <= df) if di and df else ((di <= hoje) if di and not df else False)
        total = tusd + te
        candidatos.append((not vigente, prioridade_base(rec), prioridade_detalhe(rec), -total, rec))

    if not candidatos:
        print(f"[ANEEL] Registros encontrados para {sig}, mas nenhum candidato válido em kWh/MWh.")
        return None

    candidatos.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    rec = candidatos[0][4]

    tusd = _parse_valor_monetario(rec.get("VlrTUSD"))
    te = _parse_valor_monetario(rec.get("VlrTE"))
    unidade = str(rec.get("DscUnidadeTerciaria") or "").strip().upper()
    total = tusd + te

    if unidade == "MWH":
        tarifa_base_kwh = total / 1000.0
        tusd_kwh = tusd / 1000.0
        te_kwh = te / 1000.0
    else:
        tarifa_base_kwh = total
        tusd_kwh = tusd
        te_kwh = te

    inicio_vig = _parse_data_aneel(rec.get("DatInicioVigencia"))
    fim_vig = _parse_data_aneel(rec.get("DatFimVigencia"))

    print(
        f"[ANEEL] OK datastore_search SigAgente={sig} Base={rec.get('DscBaseTarifaria')} "
        f"Detalhe={rec.get('DscDetalhe')} TUSD={tusd} TE={te} unidade={unidade}"
    )

    return {
        "sigagente": sig,
        "tarifa_base_kwh": round(tarifa_base_kwh, 5),
        "tusd_kwh": round(tusd_kwh, 5),
        "te_kwh": round(te_kwh, 5),
        "inicio_vig": str(inicio_vig) if inicio_vig else None,
        "fim_vig": str(fim_vig) if fim_vig else None,
        "base_tarifaria": rec.get("DscBaseTarifaria"),
        "detalhe": rec.get("DscDetalhe"),
    }

def calcular_tarifa_com_impostos(tarifa_base_kwh: float, uf: str) -> dict[str, float]:
    imp = obter_impostos_por_uf(uf)
    icms = float(imp.get("icms", 0.0))
    pis = float(imp.get("pis", 0.0))
    cofins = float(imp.get("cofins", 0.0))
    fator = 1.0 + (icms / 100.0) + (pis / 100.0) + (cofins / 100.0)
    return {
        "icms_pct": icms,
        "pis_pct": pis,
        "cofins_pct": cofins,
        "icms_kwh": round(tarifa_base_kwh * (icms / 100.0), 5),
        "pis_kwh": round(tarifa_base_kwh * (pis / 100.0), 5),
        "cofins_kwh": round(tarifa_base_kwh * (cofins / 100.0), 5),
        "tarifa_total_kwh": round(tarifa_base_kwh * fator, 5),
    }


def obter_tarifa_energia(uf: str, municipio: str) -> dict[str, Any]:
    uf = (uf or "").upper().strip()
    municipio = municipio or ""
    dist = obter_distribuidora_por_municipio(uf, municipio)
    if not dist:
        return {
            "tarifa_kwh": None,
            "tarifa_base_kwh": None,
            "distribuidora": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": None,
            "mensagem": "Não achei a distribuidora na tabela local. Ajuste manualmente.",
        }

    dados_aneel = obter_tarifa_energia_por_distribuidora(dist)
    if dados_aneel is None:
        tarifa_fallback = TARIFA_FALLBACK_UF.get(uf)
        if tarifa_fallback is None:
            return {
                "tarifa_kwh": None,
                "tarifa_base_kwh": None,
                "distribuidora": dist,
                "vigencia_inicio": None,
                "vigencia_fim": None,
                "detalhe": None,
                "mensagem": "Não consegui consultar a ANEEL e não há estimativa local para esta UF. Ajuste manualmente.",
            }
        return {
            "tarifa_kwh": round(float(tarifa_fallback), 5),
            "tarifa_base_kwh": round(float(tarifa_fallback), 5),
            "distribuidora": dist,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": {
                "tusd_kwh": 0,
                "te_kwh": 0,
                "icms_kwh": 0,
                "pis_kwh": 0,
                "cofins_kwh": 0,
                "icms_pct": 0,
                "pis_pct": 0,
                "cofins_pct": 0,
                "base_tarifaria": "Estimativa local",
                "sigagente": mapear_para_sigagente(dist),
                "detalhe_aneel": "Fallback usado porque a consulta ANEEL falhou",
            },
            "mensagem": f"Tarifa preenchida por estimativa local para {uf}, pois a consulta ANEEL não retornou. Ajuste manualmente se necessário.",
        }

    base_kwh = float(dados_aneel["tarifa_base_kwh"])
    impostos = calcular_tarifa_com_impostos(base_kwh, uf)
    tarifa_total = float(impostos["tarifa_total_kwh"])
    detalhe = {
        "tusd_kwh": dados_aneel["tusd_kwh"],
        "te_kwh": dados_aneel["te_kwh"],
        "icms_kwh": impostos["icms_kwh"],
        "pis_kwh": impostos["pis_kwh"],
        "cofins_kwh": impostos["cofins_kwh"],
        "icms_pct": impostos["icms_pct"],
        "pis_pct": impostos["pis_pct"],
        "cofins_pct": impostos["cofins_pct"],
        "base_tarifaria": dados_aneel["base_tarifaria"],
        "sigagente": dados_aneel["sigagente"],
        "detalhe_aneel": dados_aneel.get("detalhe"),
    }
    return {
        "tarifa_kwh": round(tarifa_total, 5),
        "tarifa_base_kwh": round(base_kwh, 5),
        "distribuidora": dist,
        "vigencia_inicio": dados_aneel["inicio_vig"],
        "vigencia_fim": dados_aneel["fim_vig"],
        "detalhe": detalhe,
        "mensagem": f"Tarifa B1 Residencial ({dist}) com impostos. Vigência ANEEL: {dados_aneel['inicio_vig']} até {dados_aneel['fim_vig']}.",
    }
