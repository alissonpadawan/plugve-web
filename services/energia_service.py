from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import json
import math
import os
import threading
import time

import pandas as pd
import requests
from urllib3.util import Timeout as Urllib3Timeout

from services.text_utils import normalizar_texto

BASE_DIR = Path(__file__).resolve().parents[1]
CAMINHO_MUNICIPIOS = BASE_DIR / "data" / "municipios.xlsx"

ANEEL_DATASTORE_URL = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search"
ANEEL_RESOURCE_ID = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
ANEEL_TARIFAS_PUBLICADAS_FILE = BASE_DIR / "data" / "aneel_tarifas_b1.json"
ANEEL_FILTROS_B1 = {
    "DscSubGrupo": "B1",
    "DscClasse": "Residencial",
    "DscModalidadeTarifaria": "Convencional",
    "DscSubClasse": "Residencial",
    "DscBaseTarifaria": "Tarifa de Aplicação",
    "DscDetalhe": "Não se aplica",
}


def _env_float(nome: str, padrao: float, minimo: float, maximo: float) -> float:
    try:
        valor = float(os.environ.get(nome, str(padrao)))
    except (TypeError, ValueError):
        valor = padrao
    return max(minimo, min(maximo, valor))


# Proteção operacional: a metodologia permanece a mesma da V46.04, mas a
# consulta externa precisa terminar antes do timeout de 30 s do Gunicorn.
ANEEL_TOTAL_BUDGET_SECONDS = _env_float("PLUGVE_ANEEL_TOTAL_BUDGET_SECONDS", 8.0, 2.0, 20.0)
ANEEL_CONNECT_TIMEOUT_SECONDS = _env_float("PLUGVE_ANEEL_CONNECT_TIMEOUT_SECONDS", 2.0, 0.5, 5.0)
ANEEL_READ_TIMEOUT_SECONDS = _env_float("PLUGVE_ANEEL_READ_TIMEOUT_SECONDS", 4.0, 0.5, 10.0)
ANEEL_CACHE_TTL_SECONDS = _env_float("PLUGVE_ANEEL_CACHE_TTL_SECONDS", 21600.0, 60.0, 604800.0)
ANEEL_STALE_MAX_AGE_SECONDS = _env_float("PLUGVE_ANEEL_STALE_MAX_AGE_SECONDS", 2592000.0, 3600.0, 31536000.0)
ANEEL_FAILURE_COOLDOWN_SECONDS = _env_float("PLUGVE_ANEEL_FAILURE_COOLDOWN_SECONDS", 60.0, 5.0, 600.0)

_DEFAULT_PERSISTENT_DIR = Path("/var/data/plugve") if Path("/var/data").exists() else BASE_DIR / "data" / "_runtime"
ANEEL_CACHE_FILE = (
    Path(os.environ.get("PLUGVE_PERSISTENT_DIR", str(_DEFAULT_PERSISTENT_DIR)))
    / "aneel_cache"
    / "tarifas_b1.json"
)

_ANEEL_CACHE_LOCK = threading.RLock()
_ANEEL_CACHE_CARREGADO = False
_ANEEL_CACHE_MEMORIA: dict[str, Any] = {}
_ANEEL_FALHA_ATE: dict[str, float] = {}

MAPA_SIGAGENTE_EXATO = {
    "AME": "Âmbar Amazonas",
    "BOA VISTA": "Âmbar Roraima",
    "ENEL SP": "ELETROPAULO",
    "FORCEL": "PACTO ENERGIA PR",
    "CPFL SANTA CRUZ": "CPFL Santa Cruz",
    "NEOENERGIA BRASILIA": "Neoenergia Brasília",
    "NEOENERGIA PE": "Neoenergia PE",
    "CERACA": "Ceraçá",
    "CERIPA": "CERIPa",
    "EQUATORIAL GO": "Equatorial GO",
    "EQUATORIAL GOIAS": "Equatorial GO",
    "EQUATORIAL GOIÁS": "Equatorial GO",
}

def _normalizar(s: Any) -> str:
    return normalizar_texto(s).upper()


def _carregar_cache_aneel() -> None:
    global _ANEEL_CACHE_CARREGADO, _ANEEL_CACHE_MEMORIA
    with _ANEEL_CACHE_LOCK:
        if _ANEEL_CACHE_CARREGADO:
            return
        _ANEEL_CACHE_CARREGADO = True
        try:
            bruto = json.loads(ANEEL_CACHE_FILE.read_text(encoding="utf-8-sig"))
            tarifas = bruto.get("tarifas", {}) if isinstance(bruto, dict) else {}
            _ANEEL_CACHE_MEMORIA = tarifas if isinstance(tarifas, dict) else {}
        except FileNotFoundError:
            _ANEEL_CACHE_MEMORIA = {}
        except Exception as exc:
            print("[ANEEL] Cache persistente inválido; seguindo sem cache:", exc)
            _ANEEL_CACHE_MEMORIA = {}


def _salvar_cache_aneel() -> None:
    with _ANEEL_CACHE_LOCK:
        try:
            ANEEL_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporario = ANEEL_CACHE_FILE.with_suffix(".tmp")
            conteudo = {
                "schema_version": 2,
                "atualizado_em": datetime.now().isoformat(timespec="seconds"),
                "descricao": "Componentes oficiais ANEEL B1; tributos são recalculados por UF em cada consulta.",
                "tarifas": _ANEEL_CACHE_MEMORIA,
            }
            temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(ANEEL_CACHE_FILE)
        except Exception as exc:
            print("[ANEEL] Não foi possível salvar o cache persistente:", exc)


def _obter_cache_aneel(sig: str, hoje: date, *, permitir_antigo: bool) -> Optional[dict[str, Any]]:
    _carregar_cache_aneel()
    chave = _normalizar(sig)
    with _ANEEL_CACHE_LOCK:
        entrada = _ANEEL_CACHE_MEMORIA.get(chave)
        if not isinstance(entrada, dict):
            return None
        dados = entrada.get("dados")
        salvo_em = entrada.get("salvo_em")
        if not isinstance(dados, dict):
            return None
        try:
            idade = max(0.0, time.time() - float(salvo_em))
        except (TypeError, ValueError):
            return None
        limite = ANEEL_STALE_MAX_AGE_SECONDS if permitir_antigo else ANEEL_CACHE_TTL_SECONDS
        if idade > limite:
            return None
        obrigatorios = {"tarifa_base_kwh", "tusd_kwh", "te_kwh", "sigagente"}
        if not obrigatorios.issubset(dados):
            return None
        inicio = _parse_data_aneel(dados.get("inicio_vig"))
        fim = _parse_data_aneel(dados.get("fim_vig"))
        if not _tarifa_vigente_em(inicio, fim, hoje):
            return None
        if _normalizar(dados.get("base_tarifaria")) != _normalizar(ANEEL_FILTROS_B1["DscBaseTarifaria"]):
            return None
        if _normalizar(dados.get("detalhe")) != _normalizar(ANEEL_FILTROS_B1["DscDetalhe"]):
            return None
        copia = dict(dados)
        copia["_cache_status"] = "stale" if idade > ANEEL_CACHE_TTL_SECONDS else "fresh"
        copia["_cache_salvo_em"] = float(salvo_em)
        return copia


def _registrar_cache_aneel(sig: str, dados: dict[str, Any]) -> None:
    _carregar_cache_aneel()
    chave = _normalizar(sig)
    # Persistir apenas componentes oficiais da ANEEL. ICMS/PIS/COFINS não
    # entram no cache porque são reaplicados pela planilha para cada UF.
    campos = (
        "sigagente", "tarifa_base_kwh", "tusd_kwh", "te_kwh",
        "inicio_vig", "fim_vig", "base_tarifaria", "detalhe",
    )
    persistivel = {campo: dados.get(campo) for campo in campos}
    with _ANEEL_CACHE_LOCK:
        _ANEEL_CACHE_MEMORIA[chave] = {"salvo_em": time.time(), "dados": persistivel}
    _salvar_cache_aneel()


def _aneel_em_cooldown(sig: str) -> bool:
    with _ANEEL_CACHE_LOCK:
        return time.monotonic() < _ANEEL_FALHA_ATE.get(_normalizar(sig), 0.0)


def _registrar_falha_aneel(sig: str) -> None:
    with _ANEEL_CACHE_LOCK:
        _ANEEL_FALHA_ATE[_normalizar(sig)] = time.monotonic() + ANEEL_FAILURE_COOLDOWN_SECONDS


def _limpar_falha_aneel(sig: str) -> None:
    with _ANEEL_CACHE_LOCK:
        _ANEEL_FALHA_ATE.pop(_normalizar(sig), None)


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


def _parse_data_aneel(v: Any) -> date | None:
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


def _data_referencia_aneel() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def _tarifa_vigente_em(inicio: date | None, fim: date | None, hoje: date) -> bool:
    return inicio is not None and fim is not None and inicio <= hoje <= fim


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



def _aneel_datastore_search(
    payload: dict[str, Any],
    *,
    deadline: float | None = None,
) -> dict[str, Any] | None:
    """Executa a mesma consulta CKAN da V46.04 com tempo total limitado.

    POST continua sendo a chamada principal. GET permanece como compatibilidade,
    mas só é tentado se ainda houver orçamento. A seleção de registros e a
    metodologia tarifária não são alteradas por esta proteção.
    """
    deadline = deadline or (time.monotonic() + ANEEL_TOTAL_BUDGET_SECONDS)

    for metodo in ("POST", "GET"):
        restante = deadline - time.monotonic()
        if restante <= 0.35:
            break

        connect_timeout = min(ANEEL_CONNECT_TIMEOUT_SECONDS, max(0.2, restante * 0.25))
        read_timeout = min(ANEEL_READ_TIMEOUT_SECONDS, max(0.25, restante - connect_timeout - 0.1))
        timeout = Urllib3Timeout(
            total=max(0.5, restante),
            connect=connect_timeout,
            read=read_timeout,
        )

        try:
            if metodo == "POST":
                resp = requests.post(ANEEL_DATASTORE_URL, json=payload, timeout=timeout)
            else:
                params = dict(payload)
                if isinstance(params.get("filters"), dict):
                    params["filters"] = json.dumps(params["filters"], ensure_ascii=False)
                resp = requests.get(ANEEL_DATASTORE_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                print(f"[ANEEL] datastore_search {metodo} sem success:", data)
                return None
            return data
        except Exception as exc:
            print(f"[ANEEL] Erro no datastore_search {metodo}:", exc)

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


def _selecionar_tarifa_vigente(
    records: list[dict[str, Any]], sig: str, hoje: date,
) -> dict[str, Any] | None:
    filtros = {campo: _normalizar(valor) for campo, valor in {**ANEEL_FILTROS_B1, "SigAgente": sig}.items()}
    candidatos = []
    for rec in records:
        if any(_normalizar(rec.get(campo)) != valor for campo, valor in filtros.items()):
            continue

        inicio = _parse_data_aneel(rec.get("DatInicioVigencia"))
        fim = _parse_data_aneel(rec.get("DatFimVigencia"))
        if not _tarifa_vigente_em(inicio, fim, hoje):
            continue

        unidade = str(rec.get("DscUnidadeTerciaria") or "").strip().upper()
        tusd = _parse_valor_monetario(rec.get("VlrTUSD"))
        te = _parse_valor_monetario(rec.get("VlrTE"))
        total = tusd + te
        if unidade not in {"MWH", "KWH"} or not math.isfinite(total) or total <= 0:
            continue

        divisor = 1000.0 if unidade == "MWH" else 1.0
        candidatos.append(((inicio, fim), {
            "sigagente": rec["SigAgente"],
            "tarifa_base_kwh": round(total / divisor, 5),
            "tusd_kwh": round(tusd / divisor, 5),
            "te_kwh": round(te / divisor, 5),
            "inicio_vig": str(inicio),
            "fim_vig": str(fim),
            "base_tarifaria": rec["DscBaseTarifaria"],
            "detalhe": rec["DscDetalhe"],
        }))

    escolhido = max(candidatos, key=lambda item: item[0], default=None)
    return escolhido[1] if escolhido else None


@lru_cache(maxsize=1)
def _carregar_tarifas_publicadas_aneel() -> list[dict[str, Any]]:
    try:
        with ANEEL_TARIFAS_PUBLICADAS_FILE.open(encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError) as exc:
        print(f"[ANEEL] Base tarifária publicada indisponível: {exc}")
        return []
    registros = dados.get("registros") if isinstance(dados, dict) else None
    return registros if isinstance(registros, list) else []


def _buscar_tarifa_publicada(sig: str, sig_alternativo: str, hoje: date) -> dict[str, Any] | None:
    registros = _carregar_tarifas_publicadas_aneel()
    tarifa = _selecionar_tarifa_vigente(registros, sig, hoje)
    if tarifa is None and _normalizar(sig) != _normalizar(sig_alternativo):
        tarifa = _selecionar_tarifa_vigente(registros, sig_alternativo, hoje)
    if tarifa is not None:
        tarifa["_cache_status"] = "publicada"
    return tarifa


def _buscar_tarifa_aneel(sig: str, sig_alternativo: str, hoje: date) -> dict[str, Any] | None:
    deadline = time.monotonic() + ANEEL_TOTAL_BUDGET_SECONDS
    payload = {
        "resource_id": ANEEL_RESOURCE_ID,
        "limit": 500,
        "sort": "DatInicioVigencia desc",
    }

    for nome in dict.fromkeys((sig, sig_alternativo)):
        consulta = {**payload, "filters": {**ANEEL_FILTROS_B1, "SigAgente": nome}}
        data = _aneel_datastore_search(consulta, deadline=deadline)
        if data is None:
            return None
        tarifa = _selecionar_tarifa_vigente(data.get("result", {}).get("records", []), nome, hoje)
        if tarifa is not None:
            return tarifa

    # A busca textual é limitada à classe B1 e continua exigindo a mesma distribuidora.
    if (deadline - time.monotonic()) <= 0.75:
        return None
    consulta = {**payload, "filters": ANEEL_FILTROS_B1, "q": sig_alternativo}
    data = _aneel_datastore_search(consulta, deadline=deadline)
    records = data.get("result", {}).get("records", []) if data else []
    return _selecionar_tarifa_vigente(records, sig_alternativo, hoje)


def obter_tarifa_energia_por_distribuidora(nome_distribuidora: str) -> Optional[dict[str, Any]]:
    """Obtém os componentes da tarifa B1 residencial convencional em vigor."""
    sig = (nome_distribuidora or "").strip()
    if not sig:
        return None

    hoje = _data_referencia_aneel()
    # A chave anterior preserva a leitura dos registros válidos já gravados no Render.
    sig_alternativo = mapear_para_sigagente(sig)
    cache_recente = _obter_cache_aneel(sig_alternativo, hoje, permitir_antigo=False)
    if cache_recente is not None:
        print(f"[ANEEL] Tarifa vigente em cache recente para {sig}.")
        return cache_recente

    if not _aneel_em_cooldown(sig_alternativo):
        resultado = _buscar_tarifa_aneel(sig, sig_alternativo, hoje)
        if resultado is not None:
            print(f"[ANEEL] Tarifa vigente para {resultado['sigagente']} desde {resultado['inicio_vig']}.")
            _registrar_cache_aneel(sig_alternativo, resultado)
            _limpar_falha_aneel(sig_alternativo)
            return resultado
        _registrar_falha_aneel(sig_alternativo)
        print(f"[ANEEL] Nenhuma tarifa vigente retornada pela consulta online para {sig}.")

    cache_anterior = _obter_cache_aneel(sig_alternativo, hoje, permitir_antigo=True)
    publicada = _buscar_tarifa_publicada(sig, sig_alternativo, hoje)
    return max(
        (tarifa for tarifa in (cache_anterior, publicada) if tarifa is not None),
        key=lambda tarifa: tarifa["inicio_vig"],
        default=None,
    )


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
            "fonte_oficial": False,
            "mensagem": "Não achei a distribuidora na tabela local. Ajuste manualmente.",
        }

    dados_aneel = obter_tarifa_energia_por_distribuidora(dist)
    if dados_aneel is None:
        return {
            "tarifa_kwh": None,
            "tarifa_base_kwh": None,
            "distribuidora": dist,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": None,
            "fonte_oficial": False,
            "mensagem": (
                "Tarifa vigente da ANEEL indisponível para esta distribuidora. "
                "Você pode informar o preço da sua conta ou tentar novamente."
            ),
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
    cache_status = dados_aneel.get("_cache_status")
    if cache_status == "publicada":
        mensagem = (
            f"Tarifa vigente publicada pela ANEEL para {dist}, com impostos de {uf} "
            f"recalculados pela planilha. Vigência: {dados_aneel['inicio_vig']} até {dados_aneel['fim_vig']}."
        )
    elif cache_status == "stale":
        mensagem = (
            f"Últimos componentes oficiais ANEEL disponíveis para {dist}, com impostos de {uf} "
            f"recalculados pela planilha. Vigência: {dados_aneel['inicio_vig']} até {dados_aneel['fim_vig']}."
        )
    else:
        mensagem = (
            f"Tarifa B1 Residencial ({dist}) com impostos de {uf}. "
            f"Vigência ANEEL: {dados_aneel['inicio_vig']} até {dados_aneel['fim_vig']}."
        )
    return {
        "tarifa_kwh": round(tarifa_total, 5),
        "tarifa_base_kwh": round(base_kwh, 5),
        "distribuidora": dist,
        "vigencia_inicio": dados_aneel["inicio_vig"],
        "vigencia_fim": dados_aneel["fim_vig"],
        "detalhe": detalhe,
        "fonte_oficial": True,
        "mensagem": mensagem,
    }
