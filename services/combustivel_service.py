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


class PlanilhaANPInvalida(Exception):
    """Erro interno para formato de planilha ANP não reconhecido."""


def _normalizar(s: object) -> str:
    return normalizar_texto(s).upper()


def _escolher_aba_municipios(caminho: Path) -> str | int:
    """
    Prioriza a aba de municípios.

    A tabela mensal antiga abria corretamente na primeira aba. A tabela semanal nova
    vem com várias abas (CAPITAIS, MUNICIPIOS, ESTADOS, REGIOES, BRASIL), então o
    serviço precisa escolher MUNICIPIOS explicitamente.
    """
    try:
        xls = pd.ExcelFile(caminho)
    except Exception:
        raise

    for nome in xls.sheet_names:
        if "MUNICIP" in _normalizar(nome):
            return nome
    return 0


def _detectar_linha_cabecalho(caminho: Path, aba: str | int) -> int:
    """
    Detecta a linha real do cabeçalho da ANP.

    Formato antigo: cabeçalho após 16 linhas informativas.
    Formato semanal novo: cabeçalho na linha 10 da planilha, após texto institucional.
    """
    amostra = pd.read_excel(caminho, sheet_name=aba, header=None, nrows=40)
    for idx, linha in amostra.iterrows():
        valores_norm = [_normalizar(v) for v in linha.tolist() if pd.notna(v)]
        tem_estado = "ESTADO" in valores_norm
        tem_municipio = any(v.startswith("MUNIC") for v in valores_norm)
        tem_produto = "PRODUTO" in valores_norm
        tem_preco = any("PRECO MEDIO REVENDA" in v for v in valores_norm)
        if tem_estado and tem_municipio and tem_produto and tem_preco:
            return int(idx)
    raise PlanilhaANPInvalida("linha de cabeçalho da aba MUNICIPIOS não encontrada")


def _parse_preco_reais(valor: object) -> float | None:
    if pd.isna(valor):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if not texto:
        return None

    # Aceita tanto 5,32 quanto 5.32 e também 1.234,56, caso apareça.
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return None


def _identificar_colunas(df: pd.DataFrame) -> dict[str, object]:
    colunas: dict[str, object] = {
        "estado": None,
        "municipio": None,
        "produto": None,
        "preco": None,
        "periodo": None,
    }

    for c in df.columns:
        cname = _normalizar(c)
        if cname == "ESTADO":
            colunas["estado"] = c
        elif cname.startswith("MUNIC"):
            colunas["municipio"] = c
        elif cname == "PRODUTO":
            colunas["produto"] = c
        elif "PRECO MEDIO REVENDA" in cname:
            colunas["preco"] = c
        elif cname in {"MES", "MÊS", "DATA FINAL", "DATA INICIAL"}:
            # Preferir DATA FINAL na planilha semanal, pois representa o fim do período.
            if colunas["periodo"] is None or cname == "DATA FINAL":
                colunas["periodo"] = c

    if not all(colunas.values()):
        faltantes = [nome for nome, valor in colunas.items() if valor is None]
        raise PlanilhaANPInvalida(
            f"colunas obrigatórias não identificadas: {faltantes}. Colunas encontradas: {list(df.columns)}"
        )

    return colunas


@lru_cache(maxsize=1)
def carregar_df_gasolina() -> Optional[pd.DataFrame]:
    if not CAMINHO_ANP.exists():
        print("[ANP] Arquivo não encontrado:", CAMINHO_ANP)
        return None

    try:
        aba = _escolher_aba_municipios(CAMINHO_ANP)
        linha_cabecalho = _detectar_linha_cabecalho(CAMINHO_ANP, aba)
        df = pd.read_excel(CAMINHO_ANP, sheet_name=aba, header=linha_cabecalho)
        colunas = _identificar_colunas(df)
    except Exception as exc:
        print("[ANP] Erro ao abrir/interpretar planilha:", exc)
        return None

    col_estado = colunas["estado"]
    col_municipio = colunas["municipio"]
    col_produto = colunas["produto"]
    col_preco = colunas["preco"]
    col_periodo = colunas["periodo"]

    produto_norm = df[col_produto].map(_normalizar)
    df = df[produto_norm.str.contains("GASOLINA COMUM", na=False)].copy()

    df["ESTADO_NORM"] = df[col_estado].map(_normalizar)
    df["MUNIC_NORM"] = df[col_municipio].map(_normalizar)
    df["PRECO_REVENDA_NUM"] = df[col_preco].map(_parse_preco_reais)
    df["MES_RAW"] = df[col_periodo]
    df["PERIODO_DATA"] = pd.to_datetime(df[col_periodo], errors="coerce", dayfirst=True)
    df = df.dropna(subset=["PRECO_REVENDA_NUM"]).reset_index(drop=True)

    print(
        "[ANP] Planilha carregada.",
        f"Aba: {aba}.",
        f"Cabeçalho: linha {linha_cabecalho + 1}.",
        "Produto: GASOLINA COMUM.",
        "Linhas:",
        len(df),
    )
    return df


def _recorte_periodo_mais_recente(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if "PERIODO_DATA" in df.columns and df["PERIODO_DATA"].notna().any():
        periodo_max = df["PERIODO_DATA"].max()
        return df[df["PERIODO_DATA"] == periodo_max]

    if "MES_RAW" in df.columns and not df["MES_RAW"].empty:
        ultimo_periodo = df["MES_RAW"].iloc[-1]
        return df[df["MES_RAW"] == ultimo_periodo]

    return df


def obter_preco_gasolina(uf: str, municipio: str) -> Optional[float]:
    df = carregar_df_gasolina()
    if df is None or df.empty:
        return None

    uf = (uf or "").upper().strip()
    municipio_norm = _normalizar(municipio)
    nome_estado_norm = MAPA_UF_PARA_ESTADO.get(uf, "")

    if not municipio_norm:
        return None

    df_busca = df
    if nome_estado_norm:
        df_busca = df_busca[df_busca["ESTADO_NORM"] == nome_estado_norm]

    filtro_exato = df_busca["MUNIC_NORM"] == municipio_norm
    df_mun = df_busca.loc[filtro_exato]

    if df_mun.empty:
        filtro_contem = df_busca["MUNIC_NORM"].str.contains(municipio_norm, na=False, regex=False)
        df_mun = df_busca.loc[filtro_contem]

    if not df_mun.empty:
        df_mun_ult = _recorte_periodo_mais_recente(df_mun)
        preco = df_mun_ult["PRECO_REVENDA_NUM"].mean()
        return round(float(preco), 3) if pd.notna(preco) else None

    if nome_estado_norm:
        df_est = df[df["ESTADO_NORM"] == nome_estado_norm]
        if not df_est.empty:
            df_est_ult = _recorte_periodo_mais_recente(df_est)
            preco = df_est_ult["PRECO_REVENDA_NUM"].mean()
            return round(float(preco), 3) if pd.notna(preco) else None

    return None
