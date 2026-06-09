from __future__ import annotations

import re
from typing import Any


def normalizar_texto(txt: Any) -> str:
    txt = "" if txt is None else str(txt)
    txt = txt.lower().strip()
    trocas = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for origem, destino in trocas.items():
        txt = txt.replace(origem, destino)
    txt = re.sub(r"[^a-z0-9\s\.\-/]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def parse_float_seguro(valor: Any, padrao: float = 0.0) -> float:
    try:
        txt = str(valor).strip().replace("R$", "").replace(" ", "")
        if not txt or txt.lower() in {"nan", "none"}:
            return float(padrao)
        if "," in txt and "." in txt:
            if txt.rfind(",") > txt.rfind("."):
                txt = txt.replace(".", "").replace(",", ".")
            else:
                txt = txt.replace(",", "")
        elif "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        return float(txt)
    except Exception:
        return float(padrao)


def parse_int_seguro(valor: Any, padrao: int = 0) -> int:
    try:
        return int(round(parse_float_seguro(valor, padrao)))
    except Exception:
        return int(padrao)


def valor_verdadeiro(valor: Any) -> bool:
    txt = str(valor or "").strip().lower()
    return txt in {"1", "sim", "true", "x", "ok", "pronto"}


def detectar_eletrico(combustivel: str, modelo: str = "") -> bool:
    texto = normalizar_texto(f"{combustivel} {modelo}")
    return any(palavra in texto for palavra in ["eletrico", "hibrido", "hybrid", "ev", "bev", "phev"])


def formatar_brl(valor: float) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"
