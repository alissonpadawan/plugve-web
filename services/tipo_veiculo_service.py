from __future__ import annotations

import re
import unicodedata
from typing import Iterable


TIPO_EV_PURO = "EV_PURO"
TIPO_PHEV = "PHEV"
TIPO_HEV = "HEV_NAO_PLUGIN"
TIPO_COMBUSTAO = "COMBUSTAO"

CONTEXTOS_VE = {"ve", "ev", "eletrico", "elétrico", "electric", "phev", "plugin", "plug-in"}
CONTEXTOS_ICEV = {"icev", "combustao", "combustão", "termico", "térmico", "atual"}
CONTEXTOS_DEPRECIACAO = {"depreciacao", "depreciação", "depreciation", "historico", "histórico"}
CONTEXTOS_AUTO = {"", "auto", "todos", "all", "qualquer"}

# Marcas que, no mercado brasileiro/FIPE, podem ter elétricos puros ou híbridos plug-in.
# Esta lista serve apenas para filtrar o primeiro select de marcas sem varrer a FIPE.
# O filtro fino continua sendo feito pelo nome do modelo/ano/combustível.
MARCAS_VE_PLUGIN_CANDIDATAS = {
    "AUDI",
    "BMW",
    "BYD",
    "CAOA CHANGAN",
    "CAOA CHERY",
    "CAOA CHERY CHERY",
    "CHERY",
    "CHEVROLET",
    "GM CHEVROLET",
    "CITROEN",
    "D2D MOTORS",
    "FIAT",
    "FORD",
    "GWM",
    "HYUNDAI",
    "JAC",
    "JAC MOTORS",
    "JAGUAR",
    "KIA",
    "LAND ROVER",
    "LEXUS",
    "MERCEDES BENZ",
    "MERCEDES-BENZ",
    "MINI",
    "MITSUBISHI",
    "NISSAN",
    "PEUGEOT",
    "PORSCHE",
    "RENAULT",
    "SERES",
    "SMART",
    "TESLA",
    "VOLVO",
    "VW VOLKSWAGEN",
    "VOLKSWAGEN",
}

# Marcas que devem sair da aba de combustão porque o catálogo PlugVE trata como
# elétrico/plugin no contexto atual. Mantemos a lista curta para não esconder
# marcas com híbridos comuns ou versões a combustão.
MARCAS_APENAS_VE_PLUGIN = {
    "BYD",
    "TESLA",
}


def normalizar_texto(valor: object) -> str:
    texto = str(valor or "").strip().upper()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = texto.replace("/", " ").replace("_", " ")
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def contexto_fipe(valor: object = "", tipo: object = "") -> str:
    bruto = normalizar_texto(valor or tipo).lower()
    if bruto in {normalizar_texto(x).lower() for x in CONTEXTOS_VE}:
        return "ve"
    if bruto in {normalizar_texto(x).lower() for x in CONTEXTOS_ICEV}:
        return "icev"
    if bruto in {normalizar_texto(x).lower() for x in CONTEXTOS_DEPRECIACAO}:
        return "depreciacao"
    if bruto in {normalizar_texto(x).lower() for x in CONTEXTOS_AUTO}:
        return ""
    return ""


def _tem_regex(texto: str, padroes: Iterable[str]) -> bool:
    return any(re.search(p, texto, flags=re.IGNORECASE) for p in padroes)


def _marca_norm(marca: object) -> str:
    return normalizar_texto(marca)


def marca_ev_plugin_candidata(nome_marca: object, extras: Iterable[str] | None = None) -> bool:
    marca = _marca_norm(nome_marca)
    if not marca:
        return False
    candidatos = set(MARCAS_VE_PLUGIN_CANDIDATAS)
    if extras:
        candidatos.update(_marca_norm(x) for x in extras if x)
    return marca in candidatos


def marca_apenas_ve_plugin(nome_marca: object) -> bool:
    return _marca_norm(nome_marca) in MARCAS_APENAS_VE_PLUGIN


def marca_permitida_no_contexto(nome_marca: object, contexto: object = "", extras_ve: Iterable[str] | None = None) -> bool:
    ctx = contexto_fipe(contexto)
    if not ctx:
        return True
    if ctx == "ve":
        return marca_ev_plugin_candidata(nome_marca, extras=extras_ve)
    if ctx == "icev":
        return not marca_apenas_ve_plugin(nome_marca)
    if ctx == "depreciacao":
        return True
    return True


def classificar_tipo_veiculo(modelo: object = "", combustivel: object = "", codigo_ano: object = "", marca: object = "") -> str:
    marca_norm = _marca_norm(marca)
    texto = normalizar_texto(f"{marca or ''} {modelo or ''} {combustivel or ''} {codigo_ano or ''}")

    # BYD e Tesla são tratados como elétrico/plugin no catálogo atual do PlugVE,
    # evitando que apareçam no bloco de combustão do TCO.
    if marca_norm == "BYD":
        if _tem_regex(texto, [r"\bDM\s*I\b", r"\bDMI\b", r"\bPHEV\b", r"\bPLUG\s*IN\b", r"\bPLUGIN\b"]):
            return TIPO_PHEV
        return TIPO_EV_PURO
    if marca_norm == "TESLA":
        return TIPO_EV_PURO
    if marca_norm == "VOLVO" and _tem_regex(texto, [r"\bT8\b"]):
        return TIPO_PHEV

    padroes_plugin = [
        r"\bPHEV\b",
        r"\bPLUG\s*IN\b",
        r"\bPLUGIN\b",
        r"\bPLUG-IN\b",
        r"HIBRID[OA]\s+PLUGIN",
        r"HIBRID[OA]\s+PLUG\s*IN",
        r"HYBRID\s+PLUGIN",
        r"HYBRID\s+PLUG\s*IN",
        r"\bDM\s*I\b",
        r"\bDMI\b",
        r"\bE\s+HYBRID\b",
        r"\bEHIBRID\b",
        r"\bTFSI\s*E\b",
        r"\bTFSIE\b",
        r"\bRECHARGE\b",
        r"\b330E\b", r"\b530E\b", r"\b545E\b", r"\b740E\b", r"\b745E\b",
        r"\bC\s*300E\b", r"\bE\s*300E\b", r"\bS\s*580E\b", r"\bGLC\s*300E\b", r"\bGLE\s*350E\b",
        r"\b225XE\b", r"\bX1\s+XDRIVE\s*25E\b", r"\bX3\s+XDRIVE\s*30E\b",
        r"\bX5\s+XDRIVE\s*(40E|45E|50E)\b",
    ]
    if _tem_regex(texto, padroes_plugin):
        return TIPO_PHEV

    padroes_eletrico = [
        r"\bELETRIC[OA]\b",
        r"\bELECTRIC\b",
        r"\bBEV\b",
        r"\bEV\b",
        r"\bE\s+TRON\b",
        r"\bETRON\b",
        r"\bE\s+TECH\b",
        r"\bBATERIA\b",
        r"\bZERO\s+EMISSAO\b",
        r"\bI\s*EV\b",
        r"\bIEV\b",
        r"\bID\s*4\b",
        r"\bID\s*3\b",
        r"\b500E\b",
        r"\bE\s*2008\b",
        r"\bE\s*208\b",
        r"\bE\s*C4\b",
        r"\bEQA\b", r"\bEQB\b", r"\bEQC\b", r"\bEQE\b", r"\bEQS\b",
        r"\bI3\b", r"\bI4\b", r"\bI7\b", r"\bIX\b", r"\bIX1\b", r"\bIX3\b",
        r"\bLEAF\b",
        r"\bZOE\b",
        r"\bBOLT\b",
        r"\bTAYCAN\b",
        r"\bDOLPHIN\b", r"\bSEAL\b", r"\bYUAN\b", r"\bTAN\b", r"\bHAN\b",
        r"\bORA\b",
    ]
    if _tem_regex(texto, padroes_eletrico):
        return TIPO_EV_PURO

    padroes_hibrido = [
        r"\bHIBRID[OA]\b",
        r"\bHYBRID\b",
        r"\bHEV\b",
        r"\bMHEV\b",
        r"\bMILD\s+HYBRID\b",
        r"\bE\s+HEV\b",
    ]
    if _tem_regex(texto, padroes_hibrido):
        return TIPO_HEV

    return TIPO_COMBUSTAO


def tipo_permitido_no_contexto(contexto: object, tipo_veiculo: object) -> bool:
    ctx = contexto_fipe(contexto)
    tipo = str(tipo_veiculo or "").upper()
    if not ctx:
        return True
    if ctx == "ve":
        return tipo in {TIPO_EV_PURO, TIPO_PHEV}
    if ctx == "icev":
        return tipo in {TIPO_COMBUSTAO, TIPO_HEV}
    if ctx == "depreciacao":
        return True
    return True
