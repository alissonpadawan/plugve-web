from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from services.text_utils import normalizar_texto

BASE_DIR = Path(__file__).resolve().parents[1]
CAMINHO_ANP = BASE_DIR / "data" / "mensal-municipios-desde-jan2026.xlsx"

MAPA_UF_PARA_ESTADO = {
    "AC": "ACRE", "AL": "ALAGOAS", "AP": "AMAPA", "AM": "AMAZONAS", "BA": "BAHIA",
    "CE": "CEARA", "DF": "DISTRITO FEDERAL", "ES": "ESPIRITO SANTO", "GO": "GOIAS",
    "MA": "MARANHAO", "MT": "MATO GROSSO", "MS": "MATO GROSSO DO SUL", "MG": "MINAS GERAIS",
    "PA": "PARA", "PB": "PARAIBA", "PR": "PARANA", "PE": "PERNAMBUCO", "PI": "PIAUI",
    "RJ": "RIO DE JANEIRO", "RN": "RIO GRANDE DO NORTE", "RS": "RIO GRANDE DO SUL",
    "RO": "RONDONIA", "RR": "RORAIMA", "SC": "SANTA CATARINA", "SP": "SAO PAULO",
    "SE": "SERGIPE", "TO": "TOCANTINS",
}


def _normalizar(s: str) -> str:
    return normalizar_texto(s).upper()


@lru_cache(maxsize=1)
def carregar_df_gasolina() -> Optional[pd.DataFrame]:
    if not CAMINHO_ANP.exists():
        print("[ANP] Arquivo não encontrado:", CAMINHO_ANP)
        return None

    try:
        df = pd.read_excel(CAMINHO_ANP, skiprows=16)
    except Exception as exc:
        print("[ANP] Erro ao abrir planilha:", exc)
        return None

    col_estado = col_municipio = col_produto = col_preco = col_mes = None
    for c in df.columns:
        cname = _normalizar(c)
        if cname == "ESTADO":
            col_estado = c
        elif cname.startswith("MUNIC"):
            col_municipio = c
        elif cname == "PRODUTO":
            col_produto = c
        elif "PRECO MEDIO REVENDA" in cname:
            col_preco = c
        elif cname in {"MES", "MÊS"}:
            col_mes = c

    if not all([col_estado, col_municipio, col_produto, col_preco, col_mes]):
        print("[ANP] Colunas esperadas não identificadas:", list(df.columns))
        return None

    df = df[df[col_produto].astype(str).str.upper().str.contains("GASOLINA COMUM", na=False)].copy()
    df["ESTADO_NORM"] = df[col_estado].map(_normalizar)
    df["MUNIC_NORM"] = df[col_municipio].map(_normalizar)
    df["PRECO_REVENDA_NUM"] = (
        df[col_preco]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .str.replace(" ", "", regex=False)
    )
    df["PRECO_REVENDA_NUM"] = pd.to_numeric(df["PRECO_REVENDA_NUM"], errors="coerce")
    df["MES_RAW"] = df[col_mes]
    df = df.dropna(subset=["PRECO_REVENDA_NUM"]).reset_index(drop=True)
    print("[ANP] Planilha carregada. Linhas:", len(df))
    return df


def obter_preco_gasolina(uf: str, municipio: str) -> Optional[float]:
    df = carregar_df_gasolina()
    if df is None or df.empty:
        return None

    uf = (uf or "").upper().strip()
    municipio_norm = _normalizar(municipio)
    nome_estado_norm = MAPA_UF_PARA_ESTADO.get(uf, "")

    filtro_mun = df["MUNIC_NORM"].str.contains(municipio_norm, na=False)
    if nome_estado_norm:
        filtro_mun = filtro_mun & (df["ESTADO_NORM"] == nome_estado_norm)

    df_mun = df.loc[filtro_mun]
    if not df_mun.empty:
        ultimo_mes = df_mun["MES_RAW"].iloc[-1]
        df_mun_ult = df_mun[df_mun["MES_RAW"] == ultimo_mes]
        preco = df_mun_ult["PRECO_REVENDA_NUM"].mean()
        return round(float(preco), 3) if pd.notna(preco) else None

    if nome_estado_norm:
        df_est = df[df["ESTADO_NORM"] == nome_estado_norm]
        if not df_est.empty:
            ultimo_mes = df_est["MES_RAW"].iloc[-1]
            df_est_ult = df_est[df_est["MES_RAW"] == ultimo_mes]
            preco = df_est_ult["PRECO_REVENDA_NUM"].mean()
            return round(float(preco), 3) if pd.notna(preco) else None

    return None
