from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class VeiculoSelecionado:
    tipo: str
    codigo_marca: str
    codigo_modelo: str
    codigo_ano: str
    codigo_fipe: str
    marca: str
    modelo: str
    ano_modelo: str
    ano_modelo_raw: str
    combustivel: str
    valor_atual: float
    horizonte_anos: int = 5
    referencia_fipe: str = ""
    mes_referencia: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "VeiculoSelecionado":
        return cls(
            tipo=str(payload.get("tipo", "auto") or "auto").strip().lower(),
            codigo_marca=str(payload.get("codigo_marca", "") or "").strip(),
            codigo_modelo=str(payload.get("codigo_modelo", "") or "").strip(),
            codigo_ano=str(payload.get("codigo_ano", "") or "").strip(),
            codigo_fipe=str(payload.get("codigo_fipe", "") or "").strip(),
            marca=str(payload.get("marca", "") or "").strip(),
            modelo=str(payload.get("modelo", "") or "").strip(),
            ano_modelo=str(payload.get("ano_modelo", "") or "").strip(),
            ano_modelo_raw=str(
                payload.get("ano_modelo_raw")
                or payload.get("ano_modelo_fipe")
                or payload.get("AnoModelo")
                or payload.get("modelYear")
                or payload.get("ano_modelo")
                or ""
            ).strip(),
            combustivel=str(payload.get("combustivel", "") or "").strip(),
            valor_atual=_parse_float(payload.get("valor_atual", 0)),
            horizonte_anos=max(1, min(20, int(_parse_float(payload.get("horizonte_anos", 5))))),
            referencia_fipe=str(payload.get("referencia_fipe") or payload.get("data_referencia_fipe") or payload.get("mes_referencia") or payload.get("MesReferencia") or "").strip(),
            mes_referencia=str(
                payload.get("mes_referencia")
                or payload.get("referencia_fipe")
                or payload.get("MesReferencia")
                or payload.get("referenceMonth")
                or ""
            ).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResumoDepreciacao:
    encontrado: bool
    status: str
    mensagem: str
    tipo_curva: str = ""
    origem_curva: str = ""
    confianca: str = ""
    valor_atual: float = 0.0
    valor_futuro: float = 0.0
    depreciacao_percentual: float = 0.0
    taxa_anual_percentual: float = 0.0
    horizonte_anos: int = 5
    pontos_historicos: int = 0
    janela_historica_meses: int = 0
    detalhes: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_float(valor: Any) -> float:
    try:
        txt = str(valor).strip().replace("R$", "").replace(" ", "")
        if not txt:
            return 0.0
        if "," in txt and "." in txt:
            if txt.rfind(",") > txt.rfind("."):
                txt = txt.replace(".", "").replace(",", ".")
            else:
                txt = txt.replace(",", "")
        elif "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        return float(txt)
    except Exception:
        return 0.0
