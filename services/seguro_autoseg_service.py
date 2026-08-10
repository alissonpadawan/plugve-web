from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
ARQUIVO_TAXAS_UF = BASE_DIR / "data" / "seguro" / "autoseg_taxas_uf_v1.csv"
ARQUIVO_TECNOLOGIA = BASE_DIR / "data" / "seguro" / "ipsa_tecnologia_v1.csv"

FONTE_UF = "AUTOSEG/SUSEP — referência regional por UF"
FONTE_TECNOLOGIA = "IPSA/TEx — comparativo por propulsão/combustível"
FONTE = f"{FONTE_UF} + {FONTE_TECNOLOGIA}"
DATA_BASE_UF = "1º semestre de 2020"
DATA_BASE_TECNOLOGIA = "abril de 2026"
DATA_BASE = f"UF: {DATA_BASE_UF}; tecnologia: {DATA_BASE_TECNOLOGIA}"
COBERTURA = "Automóvel/CASCO — prêmio médio / importância segurada média"
METODO = "taxa_uf_autoseg_vez_fator_relativo_ipsa_tecnologia"


@dataclass(frozen=True)
class SeguroAutosegEstimativa:
    valor_anual: float
    taxa_efetiva: float
    taxa_uf_base: float
    uf_solicitada: str
    uf_referencia: str
    premio_medio_referencia: float
    is_media_referencia: float
    tecnologia_solicitada: str
    tecnologia_referencia: str
    ipsa_tecnologia_percentual: float
    fator_tecnologia: float
    rotulo_tecnologia: str
    fonte: str = FONTE
    data_base: str = DATA_BASE
    cobertura_referencia: str = COBERTURA
    metodo: str = METODO
    confianca: str = "referencia_uf_tecnologia"

    def to_dict(self) -> dict[str, Any]:
        fallback_uf = self.uf_referencia == "BR" and self.uf_solicitada not in {"", "BR"}
        nivel_uf = "Brasil (fallback)" if fallback_uf else f"UF {self.uf_referencia}"
        return {
            "valor_anual": round(self.valor_anual, 2),
            "taxa_efetiva": round(self.taxa_efetiva * 100.0, 4),
            "taxa_uf_base": round(self.taxa_uf_base * 100.0, 4),
            "uf_solicitada": self.uf_solicitada,
            "uf_referencia": self.uf_referencia,
            "premio_medio_referencia": round(self.premio_medio_referencia, 2),
            "is_media_referencia": round(self.is_media_referencia, 2),
            "tecnologia_solicitada": self.tecnologia_solicitada,
            "tecnologia_referencia": self.tecnologia_referencia,
            "tecnologia_rotulo": self.rotulo_tecnologia,
            "ipsa_tecnologia_percentual": round(self.ipsa_tecnologia_percentual, 4),
            "fator_tecnologia": round(self.fator_tecnologia, 6),
            "fonte": self.fonte,
            "data_base": self.data_base,
            "cobertura_referencia": self.cobertura_referencia,
            "metodo": self.metodo,
            "nivel_agregacao": f"{nivel_uf} × tecnologia {self.rotulo_tecnologia}",
            "confianca": "fallback_brasil_tecnologia" if fallback_uf else self.confianca,
            "observacao": (
                "Estimativa estatística de referência. A taxa regional AUTOSEG/SUSEP é ajustada "
                "pela relação do IPSA/TEx da tecnologia em comparação à gasolina. "
                "Não representa cotação individual; valor editável pelo usuário."
            ),
        }


@lru_cache(maxsize=1)
def carregar_taxas_uf() -> dict[str, dict[str, Any]]:
    if not ARQUIVO_TAXAS_UF.exists():
        raise RuntimeError(f"Base de seguro não encontrada: {ARQUIVO_TAXAS_UF}")

    resultado: dict[str, dict[str, Any]] = {}
    with ARQUIVO_TAXAS_UF.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            uf = str(row.get("uf") or "").strip().upper()
            if not uf:
                continue
            premio = float(row.get("premio_medio") or 0.0)
            is_media = float(row.get("is_media") or 0.0)
            if premio <= 0 or is_media <= 0:
                continue

            taxa_calculada = premio / is_media
            resultado[uf] = {
                "estado": str(row.get("estado") or "").strip(),
                "premio_medio": premio,
                "is_media": is_media,
                "taxa": taxa_calculada,
                "periodo": str(row.get("periodo") or DATA_BASE_UF).strip(),
            }

    if "BR" not in resultado:
        raise RuntimeError("A base de seguro não contém a referência nacional BR.")
    return resultado


@lru_cache(maxsize=1)
def carregar_taxas_tecnologia() -> dict[str, dict[str, Any]]:
    if not ARQUIVO_TECNOLOGIA.exists():
        raise RuntimeError(f"Base de tecnologia do seguro não encontrada: {ARQUIVO_TECNOLOGIA}")

    resultado: dict[str, dict[str, Any]] = {}
    with ARQUIVO_TECNOLOGIA.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            tecnologia = str(row.get("tecnologia") or "").strip().lower()
            if not tecnologia:
                continue
            ipsa = float(row.get("ipsa_percentual") or 0.0)
            fator = float(row.get("fator_vs_gasolina") or 0.0)
            if ipsa <= 0 or fator <= 0:
                continue
            resultado[tecnologia] = {
                "ipsa_percentual": ipsa,
                "fator": fator,
                "rotulo": str(row.get("rotulo") or tecnologia.title()).strip(),
                "periodo": str(row.get("periodo") or DATA_BASE_TECNOLOGIA).strip(),
                "recorte": str(row.get("recorte") or "").strip(),
            }

    if "gasolina" not in resultado:
        raise RuntimeError("A base de tecnologia do seguro não contém a referência gasolina.")
    return resultado


def normalizar_tecnologia_seguro(tecnologia: Any) -> str:
    bruto = str(tecnologia or "").strip().lower()
    aliases = {
        "bev": "eletrico",
        "ev": "eletrico",
        "elétrico": "eletrico",
        "eletrico": "eletrico",
        "phev": "hibrido",
        "hev": "hibrido",
        "mhev": "hibrido",
        "híbrido": "hibrido",
        "hibrido": "hibrido",
        "diesel": "diesel",
        "gasolina": "gasolina",
        "flex": "gasolina",
        "etanol": "gasolina",
        "combustao": "gasolina",
        "combustão": "gasolina",
        "icev": "gasolina",
    }
    return aliases.get(bruto, bruto or "gasolina")


def estimar_seguro_autoseg_referencia(
    *,
    valor_fipe: float,
    uf: str,
    ano_modelo: Any = None,
    tecnologia: Any = "gasolina",
) -> SeguroAutosegEstimativa:
    """V1.1: referência regional AUTOSEG/SUSEP + ajuste relativo por tecnologia."""
    valor = max(0.0, float(valor_fipe or 0.0))
    if valor <= 0:
        raise ValueError("Valor FIPE inválido para estimativa de seguro.")

    uf_solicitada = str(uf or "").strip().upper()
    taxas_uf = carregar_taxas_uf()
    uf_referencia = uf_solicitada if uf_solicitada in taxas_uf else "BR"
    ref_uf = taxas_uf[uf_referencia]
    taxa_uf = float(ref_uf["taxa"])

    tecnologia_solicitada = normalizar_tecnologia_seguro(tecnologia)
    taxas_tec = carregar_taxas_tecnologia()
    tecnologia_referencia = tecnologia_solicitada if tecnologia_solicitada in taxas_tec else "gasolina"
    ref_tec = taxas_tec[tecnologia_referencia]
    fator_tecnologia = float(ref_tec["fator"])

    taxa_final = taxa_uf * fator_tecnologia

    return SeguroAutosegEstimativa(
        valor_anual=valor * taxa_final,
        taxa_efetiva=taxa_final,
        taxa_uf_base=taxa_uf,
        uf_solicitada=uf_solicitada,
        uf_referencia=uf_referencia,
        premio_medio_referencia=float(ref_uf["premio_medio"]),
        is_media_referencia=float(ref_uf["is_media"]),
        tecnologia_solicitada=tecnologia_solicitada,
        tecnologia_referencia=tecnologia_referencia,
        ipsa_tecnologia_percentual=float(ref_tec["ipsa_percentual"]),
        fator_tecnologia=fator_tecnologia,
        rotulo_tecnologia=str(ref_tec["rotulo"]),
        data_base=(
            f"UF: {str(ref_uf.get('periodo') or DATA_BASE_UF)}; "
            f"tecnologia: {str(ref_tec.get('periodo') or DATA_BASE_TECNOLOGIA)}"
        ),
    )
