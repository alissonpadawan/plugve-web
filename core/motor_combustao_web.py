from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from math import isnan, isinf
from statistics import median
from typing import Any

from core.modelos import VeiculoSelecionado
from services.text_utils import normalizar_texto, parse_float_seguro


class CalculoCombustaoInvalido(ValueError):
    """Erro controlado com auditoria do histórico analisado."""

    def __init__(self, mensagem: str, auditoria: dict[str, Any] | None = None) -> None:
        super().__init__(mensagem)
        self.auditoria = auditoria or {}


@dataclass
class ResultadoCalculoCombustaoWeb:
    status: str
    mensagem: str
    veiculo_titulo: str
    valor_atual: float
    valor_futuro: float
    depreciacao_percentual: float
    taxa_anual_percentual: float
    taxa_mensal_percentual: float
    pontos_historicos: int
    janela_historica_meses: int
    periodo_inicial: str
    periodo_final: str
    confianca: str
    origem_curva: str
    tipo_match: str
    historico_utilizado: list[dict[str, Any]]
    auditoria_historico: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calcular_curva_combustao_por_historico(
    *,
    veiculo: VeiculoSelecionado,
    historico: list[dict[str, Any]],
) -> ResultadoCalculoCombustaoWeb:
    pontos = _normalizar_historico(historico)
    titulo = " ".join([x for x in [veiculo.marca, veiculo.modelo, str(veiculo.ano_modelo)] if str(x).strip()])

    if len(pontos) < 3:
        auditoria = _montar_auditoria_basica(pontos, veiculo)
        raise CalculoCombustaoInvalido(
            "Histórico insuficiente para calcular curva de combustão. São necessários pelo menos 3 pontos históricos compatíveis.",
            auditoria,
        )

    pontos.sort(key=lambda x: x["data_ref"])
    janela = _diferenca_meses(pontos[0]["data_referencia"], pontos[-1]["data_referencia"])
    auditoria = _montar_auditoria_basica(pontos, veiculo)

    if janela < 6:
        raise CalculoCombustaoInvalido(
            "Janela histórica insuficiente para calcular curva de combustão. São necessários pelo menos 6 meses de histórico compatível.",
            auditoria,
        )

    if _eh_zero_km(veiculo):
        raise CalculoCombustaoInvalido(
            "Seleção zero km detectada. O histórico do código 32000 mede variação de preço de tabela do veículo novo, não depreciação real. Para zero km, a próxima etapa deve usar proxy/família ou um ano usado equivalente.",
            auditoria,
        )

    taxas_queda = []
    taxas_todos_intervalos = []
    subidas = 0
    quedas = 0
    estaveis = 0

    for anterior, atual in zip(pontos[:-1], pontos[1:]):
        meses = _diferenca_meses(anterior["data_referencia"], atual["data_referencia"])
        taxa = _taxa_mensal(anterior["valor_fipe"], atual["valor_fipe"], meses)
        if taxa is None:
            continue
        taxas_todos_intervalos.append(taxa)
        if atual["valor_fipe"] < anterior["valor_fipe"]:
            quedas += 1
            taxas_queda.append(taxa)
        elif atual["valor_fipe"] > anterior["valor_fipe"]:
            subidas += 1
        else:
            estaveis += 1

    taxa_total = _taxa_mensal(pontos[0]["valor_fipe"], pontos[-1]["valor_fipe"], janela)
    taxa_total = float(taxa_total or 0.0)

    # A série FIPE pode ter meses com alta por reajuste de mercado. Para não zerar a curva
    # por causa dessas altas, usamos a mediana dos intervalos de queda quando houver queda
    # suficiente. Caso contrário, usamos a taxa total. Se ambas forem zero, bloqueia.
    if len(taxas_queda) >= max(2, int(len(pontos) * 0.20)):
        taxa_mensal_pct = median(taxas_queda)
        metodo_taxa = "mediana_intervalos_de_queda"
    elif taxa_total > 0:
        taxa_mensal_pct = taxa_total
        metodo_taxa = "taxa_total_periodo"
    elif taxas_todos_intervalos:
        taxa_mensal_pct = max(0.0, median(taxas_todos_intervalos))
        metodo_taxa = "mediana_intervalos_todos"
    else:
        taxa_mensal_pct = 0.0
        metodo_taxa = "indisponivel"

    taxa_mensal_pct = max(0.0, float(taxa_mensal_pct))
    taxa_anual_pct = (1.0 - ((1.0 - taxa_mensal_pct / 100.0) ** 12)) * 100.0

    auditoria.update({
        "metodo_taxa": metodo_taxa,
        "taxa_total_periodo_percentual_mes": round(taxa_total, 5),
        "taxa_mensal_calculada_percentual": round(taxa_mensal_pct, 5),
        "taxa_anual_calculada_percentual": round(taxa_anual_pct, 2),
        "intervalos_queda": quedas,
        "intervalos_alta": subidas,
        "intervalos_estaveis": estaveis,
        "status_serie": _classificar_tendencia(pontos),
    })

    if taxa_anual_pct <= 0.05:
        raise CalculoCombustaoInvalido(
            "A curva foi bloqueada porque a taxa calculada ficou praticamente zero. Isso normalmente indica série de preço de veículo novo, série sem queda real ou necessidade de proxy/família. Nenhuma curva foi salva.",
            auditoria,
        )

    horizonte_meses = int(veiculo.horizonte_anos) * 12
    fator = (1.0 - taxa_mensal_pct / 100.0) ** horizonte_meses
    valor_atual = float(veiculo.valor_atual or pontos[-1]["valor_fipe"])
    valor_futuro = max(0.0, valor_atual * fator)
    depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0

    confianca = _classificar_confianca(len(pontos), janela)

    return ResultadoCalculoCombustaoWeb(
        status="calculado",
        mensagem="Curva de combustão calculada a partir do histórico FIPE sob demanda.",
        veiculo_titulo=titulo,
        valor_atual=round(valor_atual, 2),
        valor_futuro=round(valor_futuro, 2),
        depreciacao_percentual=round(max(0.0, depreciacao_pct), 2),
        taxa_anual_percentual=round(max(0.0, taxa_anual_pct), 2),
        taxa_mensal_percentual=round(max(0.0, taxa_mensal_pct), 5),
        pontos_historicos=len(pontos),
        janela_historica_meses=janela,
        periodo_inicial=pontos[0]["data_referencia"],
        periodo_final=pontos[-1]["data_referencia"],
        confianca=confianca,
        origem_curva="cálculo sob demanda combustão",
        tipo_match="historico_fipe_sob_demanda",
        historico_utilizado=[
            {"data_referencia": p["data_referencia"], "valor_fipe": p["valor_fipe"]}
            for p in pontos
        ],
        auditoria_historico=auditoria,
    )


def _montar_auditoria_basica(pontos: list[dict[str, Any]], veiculo: VeiculoSelecionado) -> dict[str, Any]:
    if not pontos:
        return {
            "pontos_historicos": 0,
            "mensagem_auditoria": "Nenhum ponto histórico válido encontrado.",
            "ano_modelo": veiculo.ano_modelo,
            "codigo_ano": veiculo.codigo_ano,
        }

    pontos = sorted(pontos, key=lambda x: x["data_ref"])
    primeiro = pontos[0]
    ultimo = pontos[-1]
    janela = _diferenca_meses(primeiro["data_referencia"], ultimo["data_referencia"])
    variacao_abs = ultimo["valor_fipe"] - primeiro["valor_fipe"]
    variacao_pct = (variacao_abs / primeiro["valor_fipe"] * 100.0) if primeiro["valor_fipe"] > 0 else 0.0

    return {
        "pontos_historicos": len(pontos),
        "janela_historica_meses": janela,
        "periodo_inicial": primeiro["data_referencia"],
        "periodo_final": ultimo["data_referencia"],
        "primeiro_valor": round(primeiro["valor_fipe"], 2),
        "ultimo_valor": round(ultimo["valor_fipe"], 2),
        "menor_valor": round(min(p["valor_fipe"] for p in pontos), 2),
        "maior_valor": round(max(p["valor_fipe"] for p in pontos), 2),
        "variacao_total_reais": round(variacao_abs, 2),
        "variacao_total_percentual": round(variacao_pct, 2),
        "ano_modelo": veiculo.ano_modelo,
        "codigo_ano": veiculo.codigo_ano,
        "zero_km_detectado": _eh_zero_km(veiculo),
    }


def _normalizar_historico(historico: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    vistos = set()
    for row in historico:
        data_ref = _extrair_data(row)
        valor = _extrair_valor(row)
        if not data_ref or valor <= 0:
            continue
        chave = data_ref
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append({
            "data_referencia": data_ref,
            "data_ref": datetime.strptime(data_ref, "%Y-%m"),
            "valor_fipe": float(valor),
        })
    return saida


def _extrair_data(row: dict[str, Any]) -> str:
    for chave in ["data_referencia", "mes_referencia", "data_ref", "referencia"]:
        valor = str(row.get(chave, "") or "").strip()[:7]
        if _data_valida(valor):
            return valor
    return ""


def _extrair_valor(row: dict[str, Any]) -> float:
    for chave in ["valor_fipe", "preco_fipe", "valor", "preco", "valor_nominal"]:
        valor = parse_float_seguro(row.get(chave), 0.0)
        if valor > 0:
            return valor
    return 0.0


def _data_valida(data_ref: str) -> bool:
    try:
        datetime.strptime(str(data_ref), "%Y-%m")
        return True
    except Exception:
        return False


def _diferenca_meses(data_inicial: str, data_final: str) -> int:
    d0 = datetime.strptime(data_inicial, "%Y-%m")
    d1 = datetime.strptime(data_final, "%Y-%m")
    return max(0, (d1.year - d0.year) * 12 + (d1.month - d0.month))


def _taxa_mensal(v0: float, v1: float, meses: int) -> float | None:
    if v0 <= 0 or v1 <= 0 or meses <= 0:
        return None
    razao = float(v1) / float(v0)
    if razao <= 0:
        return None
    taxa = (1.0 - (razao ** (1.0 / meses))) * 100.0
    if isnan(taxa) or isinf(taxa):
        return None
    return max(0.0, taxa)


def _classificar_confianca(pontos: int, janela_meses: int) -> str:
    if pontos >= 24 and janela_meses >= 24:
        return "ALTA"
    if pontos >= 18 and janela_meses >= 18:
        return "MEDIA"
    if pontos >= 8 and janela_meses >= 12:
        return "BAIXA"
    return "EXPLORATORIA"


def _classificar_tendencia(pontos: list[dict[str, Any]]) -> str:
    if len(pontos) < 2:
        return "INSUFICIENTE"
    primeiro = float(pontos[0]["valor_fipe"])
    ultimo = float(pontos[-1]["valor_fipe"])
    if ultimo < primeiro:
        return "QUEDA_TOTAL"
    if ultimo > primeiro:
        return "ALTA_TOTAL"
    return "ESTAVEL_TOTAL"


def _eh_zero_km(veiculo: VeiculoSelecionado) -> bool:
    return str(veiculo.ano_modelo).strip() == "32000" or str(veiculo.codigo_ano).strip().startswith("32000")


def texto_chave_historico(row: dict[str, Any]) -> str:
    partes = []
    for chave in ["codigo_fipe", "CodigoFipe", "marca", "brand", "modelo", "model", "titulo", "veiculo"]:
        valor = row.get(chave)
        if valor:
            partes.append(str(valor))
    return normalizar_texto(" ".join(partes))
