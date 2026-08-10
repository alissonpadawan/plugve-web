from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
ARQUIVO_TAXAS_UF = BASE_DIR / "data" / "seguro" / "autoseg_taxas_uf_v1.csv"

FONTE = "AUTOSEG/SUSEP — consolidação regional por UF (Brasil Atuarial)"
DATA_BASE = "1º semestre de 2020"
COBERTURA = "Automóvel/CASCO — prêmio médio / importância segurada média"
METODO = "premio_medio_dividido_por_importancia_segurada_media"


@dataclass(frozen=True)
class SeguroAutosegEstimativa:
    valor_anual: float
    taxa_efetiva: float
    uf_solicitada: str
    uf_referencia: str
    premio_medio_referencia: float
    is_media_referencia: float
    fonte: str = FONTE
    data_base: str = DATA_BASE
    cobertura_referencia: str = COBERTURA
    metodo: str = METODO
    nivel_agregacao: str = "UF — automóvel"
    confianca: str = "referencia_uf"

    def to_dict(self) -> dict[str, Any]:
        fallback = self.uf_referencia == "BR" and self.uf_solicitada not in {"", "BR"}
        return {
            "valor_anual": round(self.valor_anual, 2),
            "taxa_efetiva": round(self.taxa_efetiva * 100.0, 4),
            "uf_solicitada": self.uf_solicitada,
            "uf_referencia": self.uf_referencia,
            "premio_medio_referencia": round(self.premio_medio_referencia, 2),
            "is_media_referencia": round(self.is_media_referencia, 2),
            "fonte": self.fonte,
            "data_base": self.data_base,
            "cobertura_referencia": self.cobertura_referencia,
            "metodo": self.metodo,
            "nivel_agregacao": "Brasil — automóvel (fallback)" if fallback else self.nivel_agregacao,
            "confianca": "fallback_brasil" if fallback else self.confianca,
            "observacao": (
                "Estimativa estatística de referência baseada na razão entre prêmio médio e "
                "importância segurada média. Não representa cotação individual; valor editável pelo usuário."
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
            taxa = float(row.get("taxa_percentual") or 0.0) / 100.0
            if premio <= 0 or is_media <= 0 or taxa <= 0:
                continue
            # Recalcula a razão a partir das duas grandezas para que o CSV não seja
            # uma fonte independente da fórmula metodológica.
            taxa_calculada = premio / is_media
            resultado[uf] = {
                "estado": str(row.get("estado") or "").strip(),
                "premio_medio": premio,
                "is_media": is_media,
                "taxa": taxa_calculada,
                "periodo": str(row.get("periodo") or DATA_BASE).strip(),
            }

    if "BR" not in resultado:
        raise RuntimeError("A base de seguro não contém a referência nacional BR.")
    return resultado


def estimar_seguro_autoseg_referencia(
    *,
    valor_fipe: float,
    uf: str,
    ano_modelo: Any = None,
) -> SeguroAutosegEstimativa:
    """Estima o prêmio anual usando somente a taxa observada da UF.

    `ano_modelo` é aceito no contrato para compatibilidade e futura evolução por
    modelo/ano, mas não altera a estimativa V1. Isso evita introduzir fatores não
    observados na base agregada disponível nesta rodada.
    """
    valor = max(0.0, float(valor_fipe or 0.0))
    if valor <= 0:
        raise ValueError("Valor FIPE inválido para estimativa de seguro.")

    uf_solicitada = str(uf or "").strip().upper()
    taxas = carregar_taxas_uf()
    uf_referencia = uf_solicitada if uf_solicitada in taxas else "BR"
    ref = taxas[uf_referencia]
    taxa = float(ref["taxa"])

    return SeguroAutosegEstimativa(
        valor_anual=valor * taxa,
        taxa_efetiva=taxa,
        uf_solicitada=uf_solicitada,
        uf_referencia=uf_referencia,
        premio_medio_referencia=float(ref["premio_medio"]),
        is_media_referencia=float(ref["is_media"]),
        data_base=str(ref.get("periodo") or DATA_BASE),
    )
