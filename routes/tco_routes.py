# Módulo TCO integrado a partir da calculadora original.
# Mantido separado do app.py principal para preservar modularidade.
# ============================================================
# 0) IMPORTS E APP
# ============================================================
from flask import Blueprint, render_template, request, flash, jsonify, redirect, url_for
import plotly.graph_objs as go
import plotly.io as pio
import os
from pathlib import Path
from datetime import datetime, date
import requests
import pandas as pd
import unicodedata
from functools import lru_cache

from services.fipe_service import FipeService, FipeApiError

tco_bp = Blueprint("tco", __name__)

# ============================================================
# 1) CAMINHOS DE ARQUIVOS (PASTA /data)
# ============================================================
BASE_DIR = str(Path(__file__).resolve().parents[1])
CAMINHO_ANP = os.path.join(BASE_DIR, "data", "mensal-municipios-desde-jan2026.xlsx")
CAMINHO_MUNICIPIOS = os.path.join(BASE_DIR, "data", "municipios.xlsx")

# ============================================================
# 2) HELPERS (FUNÇÕES PEQUENAS)
# ============================================================

# 2.1) Converter número com vírgula/ponto
SEGURO_PADRAO_PERCENTUAL = 0.047

def conv(num):
    try:
        txt = str(num if num is not None else "").strip().replace("R$", "").replace("%", "")
        if not txt:
            return 0.0
        # Formato brasileiro: 6.191,92 -> 6191.92
        if "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        return float(txt)
    except (TypeError, ValueError):
        return 0.0

def seguro_padrao(preco: float) -> float:
    return max(0.0, float(preco or 0.0) * SEGURO_PADRAO_PERCENTUAL)

def seguro_formulario_ou_padrao(dados_form, campo: str, preco: float) -> float:
    valor = conv(dados_form.get(campo, 0))
    return valor if valor > 0 else seguro_padrao(preco)

# 2.2) Normalizar texto (remove acento, upper, trim)
def normalizar(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().upper()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return s

# 2.3) Parse monetário vindo da ANEEL (string com vírgula)
def _parse_valor_monetario(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0

# 2.4) Parse data (aceita "YYYY-MM-DD" ou "DD/MM/YYYY")
def _parse_data_aneel(v):
    if not v:
        return None
    s = str(v).strip()
    # tenta yyyy-mm-dd
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    # tenta dd/mm/yyyy
    try:
        return datetime.strptime(s[:10], "%d/%m/%Y").date()
    except Exception:
        return None

# ============================================================
# 3) ROTAS BÁSICAS (HOME/SOBRE/CONTATO)
# ============================================================
@tco_bp.route("/home")
def home():
    return redirect(url_for("tco.simular"))

@tco_bp.route("/sobre")
def sobre():
    return render_template("sobre.html")

@tco_bp.route("/contato")
def contato():
    return render_template("contato.html")

# ============================================================
# 4) CÁLCULO TCO + NOVOS CENÁRIOS DE COMPARAÇÃO
# ============================================================

# 4.1) Função original mantida
def calcular_tco_completo(dados_form):
    modelo_ve = dados_form.get("modelo_ve", "VE")
    modelo_icev = dados_form.get("modelo_icev", "ICEV")

    preco_ve = conv(dados_form.get("preco_ve", 0))
    preco_icev = conv(dados_form.get("preco_icev", 0))

    consumo_ve = conv(dados_form.get("consumo_ve", 0))
    consumo_icev = conv(dados_form.get("consumo_icev", 1))  # km/l

    energia_inicial = conv(dados_form.get("energia", 0))
    combustivel_inicial = conv(dados_form.get("combustivel", 0))

    aumento_energia = conv(dados_form.get("aumento_energia", "0")) / 100.0
    aumento_combustivel = conv(dados_form.get("aumento_combustivel", "0")) / 100.0

    manut_ve = conv(dados_form.get("manut_ve", 0))
    manut_icev = conv(dados_form.get("manut_icev", 0))

    isencao_ipva_ve = "isencao_ipva_ve" in dados_form
    if isencao_ipva_ve:
        ipva_ve = 0.0
    else:
        ipva_ve = conv(dados_form.get("ipva_ve", 0))

    ipva_icev = conv(dados_form.get("ipva_icev", 0))

    seguro_ve = seguro_formulario_ou_padrao(dados_form, "seguro_ve", preco_ve)
    seguro_icev = seguro_formulario_ou_padrao(dados_form, "seguro_icev", preco_icev)

    depreciacao_ve = conv(dados_form.get("depreciacao_ve", 0)) / 100.0
    depreciacao_icev = conv(dados_form.get("depreciacao_icev", 0)) / 100.0

    anos = int(dados_form.get("anos", 1))
    km_ano = int(dados_form.get("km_ano", 0))

    tco_ve, tco_icev = preco_ve, preco_icev
    preco_ve_atual, preco_icev_atual = preco_ve, preco_icev

    anos_lista = []
    tco_ve_lista = []
    tco_icev_lista = []

    tco_ve_s = preco_ve
    tco_icev_s = preco_icev
    tco_ve_lista_s = []
    tco_icev_lista_s = []

    energia_anual = energia_inicial
    combustivel_anual = combustivel_inicial

    for ano in range(1, anos + 1):
        if ano > 1:
            energia_anual *= 1 + aumento_energia
            combustivel_anual *= 1 + aumento_combustivel

        preco_ve_atual *= 1 - depreciacao_ve
        preco_icev_atual *= 1 - depreciacao_icev

        custo_anual_ve = (km_ano * consumo_ve * energia_anual) + manut_ve + ipva_ve + seguro_ve
        custo_anual_icev = (km_ano / consumo_icev * combustivel_anual) + manut_icev + ipva_icev + seguro_icev

        tco_ve += custo_anual_ve
        tco_icev += custo_anual_icev

        tco_ve_lista.append(tco_ve - preco_ve_atual)
        tco_icev_lista.append(tco_icev - preco_icev_atual)

        tco_ve_s += custo_anual_ve
        tco_icev_s += custo_anual_icev
        tco_ve_lista_s.append(tco_ve_s)
        tco_icev_lista_s.append(tco_icev_s)

        anos_lista.append(f"Ano {ano}")

    total_km = anos * km_ano if anos > 0 else 1

    custo_km_ve = (tco_ve - preco_ve_atual) / total_km
    custo_km_icev = (tco_icev - preco_icev_atual) / total_km

    custo_km_ve_s = (tco_ve_s - preco_ve) / total_km
    custo_km_icev_s = (tco_icev_s - preco_icev) / total_km

    return {
        "modelo_ve": modelo_ve,
        "modelo_icev": modelo_icev,
        "tco_ve_final": tco_ve - preco_ve_atual,
        "tco_icev_final": tco_icev - preco_icev_atual,
        "custo_km_ve": custo_km_ve,
        "custo_km_icev": custo_km_icev,
        "tco_ve_final_s": tco_ve_s - preco_ve,
        "tco_icev_final_s": tco_icev_s - preco_icev,
        "custo_km_ve_s": custo_km_ve_s,
        "custo_km_icev_s": custo_km_icev_s,
        "anos_lista": anos_lista,
        "tco_ve_lista": tco_ve_lista,
        "tco_icev_lista": tco_icev_lista,
        "tco_ve_lista_s": tco_ve_lista_s,
        "tco_icev_lista_s": tco_icev_lista_s,
    }


# 4.2) Helpers visuais e numéricos
CORES_GRAFICOS = ["#2563EB", "#16A34A", "#F97316", "#7C3AED"]


def real_format(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percentual_format(valor):
    return f"{float(valor or 0) * 100:.2f}%".replace(".", ",")


def taxa_relativa(valor: float, base: float) -> float:
    try:
        valor = float(valor or 0)
        base = float(base or 0)
        return valor / base if base > 0 and valor > 0 else 0.0
    except Exception:
        return 0.0


def inteiro_form(dados_form, campo: str, padrao: int = 0) -> int:
    try:
        return int(round(conv(dados_form.get(campo, padrao))))
    except Exception:
        return padrao


def financiamento_ativo_form(dados_form, prefixo: str) -> bool:
    valor = str(dados_form.get(f"fin_{prefixo}_ativo", "")).strip().lower()
    return valor in {"1", "true", "on", "sim", "yes"}


def calcular_financiamento_form(dados_form, prefixo: str, preco: float) -> dict:
    """
    Calcula financiamento pelo sistema Price.
    No TCO, entra como custo financeiro somente o juro pago no horizonte,
    para não contar o preço do veículo duas vezes quando já há depreciação/valor de revenda.
    """
    preco = max(0.0, float(preco or 0.0))
    ativo = financiamento_ativo_form(dados_form, prefixo)
    entrada = max(0.0, conv(dados_form.get(f"fin_{prefixo}_entrada", 0)))
    entrada_pct = max(0.0, conv(dados_form.get(f"fin_{prefixo}_entrada_pct", 0)) / 100.0)
    if entrada <= 0 and entrada_pct > 0:
        entrada = preco * min(entrada_pct, 1.0)
    taxa_mensal = max(0.0, conv(dados_form.get(f"fin_{prefixo}_juros_mensal", 0)) / 100.0)
    meses = max(0, inteiro_form(dados_form, f"fin_{prefixo}_meses", 0))
    custos = max(0.0, conv(dados_form.get(f"fin_{prefixo}_custos", 0)))

    principal = max(0.0, preco + custos - entrada)
    if not ativo or meses <= 0 or principal <= 0:
        return {
            "ativo": False,
            "entrada": 0.0,
            "entrada_pct": 0.0,
            "principal": 0.0,
            "taxa_mensal": 0.0,
            "meses": 0,
            "custos": 0.0,
            "parcela": 0.0,
            "total_parcelas": 0.0,
            "total_pago": 0.0,
            "juros_total": 0.0,
        }

    if taxa_mensal > 0:
        fator = (1 + taxa_mensal) ** meses
        parcela = principal * (taxa_mensal * fator) / (fator - 1)
    else:
        parcela = principal / meses

    total_parcelas = parcela * meses
    juros_total = max(0.0, total_parcelas - principal)
    total_pago = entrada + total_parcelas

    return {
        "ativo": True,
        "entrada": entrada,
        "principal": principal,
        "taxa_mensal": taxa_mensal,
        "meses": meses,
        "custos": custos,
        "parcela": parcela,
        "total_parcelas": total_parcelas,
        "total_pago": total_pago,
        "juros_total": juros_total,
    }


def juros_financiamento_por_ano(financiamento: dict, anos: int) -> list:
    if not financiamento or not financiamento.get("ativo"):
        return [0.0] * max(0, int(anos or 0))

    anos = max(0, int(anos or 0))
    principal = max(0.0, float(financiamento.get("principal", 0.0) or 0.0))
    taxa = max(0.0, float(financiamento.get("taxa_mensal", 0.0) or 0.0))
    meses = max(0, int(financiamento.get("meses", 0) or 0))
    parcela = max(0.0, float(financiamento.get("parcela", 0.0) or 0.0))

    juros_anuais = [0.0] * anos
    saldo = principal
    if principal <= 0 or meses <= 0 or parcela <= 0:
        return juros_anuais

    for mes in range(1, min(meses, anos * 12) + 1):
        juros_mes = saldo * taxa if taxa > 0 else 0.0
        amortizacao = parcela - juros_mes if taxa > 0 else parcela
        if amortizacao < 0:
            amortizacao = 0.0
        saldo = max(0.0, saldo - amortizacao)
        ano_idx = (mes - 1) // 12
        if 0 <= ano_idx < anos:
            juros_anuais[ano_idx] += juros_mes
        if saldo <= 0:
            break

    return juros_anuais


def nome_curto(nome: str, limite: int = 36) -> str:
    nome = str(nome or "Veículo").strip()
    return nome if len(nome) <= limite else nome[: limite - 1].rstrip() + "…"


# 4.3) Layout padrão dos gráficos
def obter_layout_web(titulo: str = ""):
    return {
        "title": {"text": titulo, "x": 0.02, "xanchor": "left", "font": {"size": 18, "color": "#0F172A"}},
        "template": "plotly_white",
        "height": 430,
        "autosize": True,
        "font": {"family": "Inter, Arial, sans-serif", "size": 12, "color": "#334155"},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.04, "xanchor": "left", "x": 0},
        "margin": {"l": 70, "r": 30, "t": 78, "b": 70},
        "hovermode": "x unified",
        "paper_bgcolor": "#FFFFFF",
        "plot_bgcolor": "#FFFFFF",
    }


def html_grafico(fig):
    fig.update_xaxes(showgrid=True, gridcolor="#E5E7EB", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#E5E7EB", zeroline=False)
    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        config={"displayModeBar": False, "responsive": True, "locale": "pt-BR"},
    )


# 4.4) Projeção genérica de um veículo
# Regra V26: energia e combustível sobem a.a.; IPVA e seguro acompanham o valor de mercado do veículo.
def calcular_projecao_veiculo(veiculo, comum):
    nome = veiculo.get("nome", "Veículo")
    tipo = veiculo.get("tipo", "icev")  # ve ou icev

    preco = max(0.0, float(veiculo.get("preco", 0) or 0))
    consumo = max(0.0, float(veiculo.get("consumo", 0) or 0))
    manut = max(0.0, float(veiculo.get("manut", 0) or 0))
    ipva_inicial = max(0.0, float(veiculo.get("ipva", 0) or 0))
    seguro_inicial = max(0.0, float(veiculo.get("seguro", 0) or 0))
    depreciacao = max(0.0, min(float(veiculo.get("depreciacao", 0) or 0), 0.95))
    financiamento = veiculo.get("financiamento") or {}

    energia_inicial = max(0.0, float(comum.get("energia", 0) or 0))
    combustivel_inicial = max(0.0, float(comum.get("combustivel", 0) or 0))
    aumento_energia = float(comum.get("aumento_energia", 0) or 0)
    aumento_combustivel = float(comum.get("aumento_combustivel", 0) or 0)
    anos = max(1, int(comum.get("anos", 1) or 1))
    km_ano = max(0, int(comum.get("km_ano", 0) or 0))

    taxa_ipva = taxa_relativa(ipva_inicial, preco)
    taxa_seguro = taxa_relativa(seguro_inicial, preco)

    valor_mercado = preco
    gasto_operacional_acumulado = 0.0

    anos_lista = []
    anos_eixo = ["Hoje"]
    tco_lista = []
    tco_lista_s = []
    valor_mercado_lista = [valor_mercado]
    depreciacao_acumulada_lista = [0.0]
    gasto_operacional_lista = []
    custo_uso_lista = []
    ipva_lista = []
    seguro_lista = []
    manut_lista = []
    preco_energia_lista = []
    preco_combustivel_lista = []
    financiamento_juros_lista = []
    financiamento_juros_anuais = juros_financiamento_por_ano(financiamento, anos)

    for ano in range(1, anos + 1):
        energia_ano = energia_inicial * ((1 + aumento_energia) ** (ano - 1))
        combustivel_ano = combustivel_inicial * ((1 + aumento_combustivel) ** (ano - 1))

        # IPVA e seguro do ano usam o valor de mercado vigente no início do ano.
        ipva_ano = valor_mercado * taxa_ipva
        seguro_ano = valor_mercado * taxa_seguro

        if tipo == "ve":
            custo_uso = km_ano * consumo * energia_ano
        else:
            custo_uso = (km_ano / consumo * combustivel_ano) if consumo > 0 else 0.0

        juros_financiamento_ano = financiamento_juros_anuais[ano - 1] if ano - 1 < len(financiamento_juros_anuais) else 0.0
        custo_anual = custo_uso + manut + ipva_ano + seguro_ano + juros_financiamento_ano
        gasto_operacional_acumulado += custo_anual

        # Valor estimado de revenda ao fim do ano.
        valor_mercado = valor_mercado * (1 - depreciacao)
        perda_depreciacao = max(0.0, preco - valor_mercado)
        tco_com_depreciacao = gasto_operacional_acumulado + perda_depreciacao

        anos_lista.append(f"Ano {ano}")
        anos_eixo.append(f"Ano {ano}")
        tco_lista.append(tco_com_depreciacao)
        tco_lista_s.append(gasto_operacional_acumulado)
        valor_mercado_lista.append(valor_mercado)
        depreciacao_acumulada_lista.append(perda_depreciacao)
        gasto_operacional_lista.append(gasto_operacional_acumulado)
        custo_uso_lista.append(custo_uso)
        ipva_lista.append(ipva_ano)
        seguro_lista.append(seguro_ano)
        manut_lista.append(manut)
        preco_energia_lista.append(energia_ano)
        preco_combustivel_lista.append(combustivel_ano)
        financiamento_juros_lista.append(juros_financiamento_ano)

    total_km = anos * km_ano if anos > 0 and km_ano > 0 else 1
    valor_revenda_final = valor_mercado_lista[-1]
    perda_depreciacao_final = max(0.0, preco - valor_revenda_final)
    gasto_operacional_final = gasto_operacional_lista[-1] if gasto_operacional_lista else 0.0
    tco_final = tco_lista[-1] if tco_lista else 0.0
    tco_final_s = tco_lista_s[-1] if tco_lista_s else 0.0
    juros_financiamento_horizonte = sum(financiamento_juros_lista)

    return {
        "nome": nome,
        "nome_curto": nome_curto(nome),
        "tipo": tipo,
        "preco_inicial": preco,
        "taxa_depreciacao": depreciacao,
        "taxa_ipva": taxa_ipva,
        "taxa_seguro": taxa_seguro,
        "valor_revenda_final": valor_revenda_final,
        "perda_depreciacao_final": perda_depreciacao_final,
        "gasto_operacional_final": gasto_operacional_final,
        "financiamento": financiamento,
        "juros_financiamento_horizonte": juros_financiamento_horizonte,
        "anos_lista": anos_lista,
        "anos_eixo": anos_eixo,
        "tco_final": tco_final,
        "tco_final_s": tco_final_s,
        "custo_km": tco_final / total_km,
        "custo_km_s": tco_final_s / total_km,
        "tco_lista": tco_lista,
        "tco_lista_s": tco_lista_s,
        "valor_mercado_lista": valor_mercado_lista,
        "depreciacao_acumulada_lista": depreciacao_acumulada_lista,
        "gasto_operacional_lista": gasto_operacional_lista,
        "custo_uso_lista": custo_uso_lista,
        "ipva_lista": ipva_lista,
        "seguro_lista": seguro_lista,
        "manut_lista": manut_lista,
        "preco_energia_lista": preco_energia_lista,
        "preco_combustivel_lista": preco_combustivel_lista,
        "financiamento_juros_lista": financiamento_juros_lista,
    }


# 4.5) Gera gráficos de comparação entre 2 veículos
def gerar_graficos_dupla(v1, v2):
    cor1, cor2 = CORES_GRAFICOS[0], CORES_GRAFICOS[1]

    fig_tco = go.Figure()
    fig_tco.add_trace(go.Scatter(
        x=v1["anos_lista"], y=v1["tco_lista"], mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v1["nome"]] * len(v1["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>TCO: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_tco.add_trace(go.Scatter(
        x=v2["anos_lista"], y=v2["tco_lista"], mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v2["nome"]] * len(v2["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>TCO: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_tco.update_layout(**obter_layout_web("TCO acumulado com depreciação"), yaxis_title="Custo acumulado (R$)")

    fig_gastos = go.Figure()
    fig_gastos.add_trace(go.Scatter(
        x=v1["anos_lista"], y=v1["tco_lista_s"], mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v1["nome"]] * len(v1["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>Gasto operacional: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_gastos.add_trace(go.Scatter(
        x=v2["anos_lista"], y=v2["tco_lista_s"], mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v2["nome"]] * len(v2["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>Gasto operacional: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_gastos.update_layout(**obter_layout_web("Gastos acumulados de uso e financiamento"), yaxis_title="Gasto acumulado (R$)")

    fig_custo_km = go.Figure()
    fig_custo_km.add_trace(go.Bar(
        y=[v1["nome_curto"], v2["nome_curto"]],
        x=[v1["custo_km"], v2["custo_km"]],
        orientation="h",
        text=[real_format(v1["custo_km"]), real_format(v2["custo_km"])],
        textposition="outside",
        marker={"color": [cor1, cor2], "line": {"color": "#FFFFFF", "width": 1}},
        customdata=[v1["nome"], v2["nome"]],
        hovertemplate="%{customdata}<br>Custo por km: R$ %{x:,.2f}<extra></extra>",
    ))
    fig_custo_km.update_layout(**obter_layout_web("Custo por quilômetro rodado"), xaxis_title="R$/km", yaxis_title="")
    fig_custo_km.update_yaxes(autorange="reversed")

    fig_revenda = go.Figure()
    fig_revenda.add_trace(go.Scatter(
        x=v1["anos_eixo"], y=v1["valor_mercado_lista"], mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        fill="tozeroy", fillcolor="rgba(37, 99, 235, 0.10)",
        customdata=[v1["nome"]] * len(v1["anos_eixo"]),
        hovertemplate="%{customdata}<br>%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_revenda.add_trace(go.Scatter(
        x=v2["anos_eixo"], y=v2["valor_mercado_lista"], mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        fill="tozeroy", fillcolor="rgba(22, 163, 74, 0.10)",
        customdata=[v2["nome"]] * len(v2["anos_eixo"]),
        hovertemplate="%{customdata}<br>%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_revenda.update_layout(**obter_layout_web("Valor estimado de revenda"), yaxis_title="Valor de mercado (R$)")

    def grafico_depreciacao_individual(v, cor):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=v["anos_eixo"], y=v["valor_mercado_lista"], mode="lines+markers", name="Valor de revenda",
            line={"color": cor, "width": 3, "shape": "spline"}, marker={"size": 8},
            fill="tozeroy", fillcolor="rgba(37, 99, 235, 0.10)",
            hovertemplate="%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(**obter_layout_web(f"Depreciação — {nome_curto(v['nome'], 42)}"), yaxis_title="Valor de mercado (R$)")
        return html_grafico(fig)

    return {
        "grafico": html_grafico(fig_tco),
        "grafico_sem_depreciacao": html_grafico(fig_gastos),
        "grafico_custo_km": html_grafico(fig_custo_km),
        "grafico_revenda_comparativo": html_grafico(fig_revenda),
        "grafico_depreciacao_v1": grafico_depreciacao_individual(v1, cor1),
        "grafico_depreciacao_v2": grafico_depreciacao_individual(v2, cor2),
    }


# 4.6) Empacota 1 comparação pronta para renderização
def montar_bloco_resultado(titulo, v1, v2):
    graficos = gerar_graficos_dupla(v1, v2)
    vencedor = v1 if v1["tco_final"] <= v2["tco_final"] else v2
    outro = v2 if vencedor is v1 else v1
    economia = max(0.0, outro["tco_final"] - vencedor["tco_final"])

    def resumo(v):
        return {
            "nome": v["nome"],
            "nome_curto": v["nome_curto"],
            "tco_final": real_format(v["tco_final"]),
            "custo_km": real_format(v["custo_km"]),
            "tco_final_s": real_format(v["tco_final_s"]),
            "custo_km_s": real_format(v["custo_km_s"]),
            "preco_inicial": real_format(v["preco_inicial"]),
            "gasto_operacional": real_format(v["gasto_operacional_final"]),
            "perda_depreciacao": real_format(v["perda_depreciacao_final"]),
            "valor_revenda": real_format(v["valor_revenda_final"]),
            "taxa_depreciacao": percentual_format(v["taxa_depreciacao"]),
            "taxa_ipva": percentual_format(v["taxa_ipva"]),
            "taxa_seguro": percentual_format(v["taxa_seguro"]),
            "financiamento_ativo": bool((v.get("financiamento") or {}).get("ativo")),
            "valor_financiado": real_format((v.get("financiamento") or {}).get("principal", 0)),
            "entrada_financiamento": real_format((v.get("financiamento") or {}).get("entrada", 0)),
            "parcela_financiamento": real_format((v.get("financiamento") or {}).get("parcela", 0)),
            "prazo_financiamento": int((v.get("financiamento") or {}).get("meses", 0) or 0),
            "taxa_financiamento": percentual_format((v.get("financiamento") or {}).get("taxa_mensal", 0)),
            "total_financiamento": real_format((v.get("financiamento") or {}).get("total_pago", 0)),
            "juros_financiamento_total": real_format((v.get("financiamento") or {}).get("juros_total", 0)),
            "juros_financiamento_horizonte": real_format(v.get("juros_financiamento_horizonte", 0)),
        }

    resumo_v1 = resumo(v1)
    resumo_v2 = resumo(v2)

    return {
        "titulo": titulo,
        "vencedor_nome": vencedor["nome"],
        "economia": real_format(economia),
        "detalhes": [resumo_v1, resumo_v2],
        "resumo_com": [
            {"nome": resumo_v1["nome"], "tco_final": resumo_v1["tco_final"], "custo_km": resumo_v1["custo_km"]},
            {"nome": resumo_v2["nome"], "tco_final": resumo_v2["tco_final"], "custo_km": resumo_v2["custo_km"]},
        ],
        "resumo_sem": [
            {"nome": resumo_v1["nome"], "tco_final": resumo_v1["tco_final_s"], "custo_km": resumo_v1["custo_km_s"]},
            {"nome": resumo_v2["nome"], "tco_final": resumo_v2["tco_final_s"], "custo_km": resumo_v2["custo_km_s"]},
        ],
        "grafico": graficos["grafico"],
        "grafico_sem_depreciacao": graficos["grafico_sem_depreciacao"],
        "grafico_custo_km": graficos["grafico_custo_km"],
        "grafico_revenda_comparativo": graficos["grafico_revenda_comparativo"],
        "grafico_depreciacao_v1": graficos["grafico_depreciacao_v1"],
        "grafico_depreciacao_v2": graficos["grafico_depreciacao_v2"],
    }


# 4.7) Conversor antigo mantido apenas por compatibilidade interna.
def montar_bloco_resultado_cenario_original(dados_calculados):
    return {
        "titulo": "Comparação direta entre os dois carros selecionados",
        "vencedor_nome": "",
        "economia": real_format(0),
        "detalhes": [],
        "resumo_com": [
            {"nome": dados_calculados["modelo_ve"], "tco_final": real_format(dados_calculados["tco_ve_final"]), "custo_km": real_format(dados_calculados["custo_km_ve"])},
            {"nome": dados_calculados["modelo_icev"], "tco_final": real_format(dados_calculados["tco_icev_final"]), "custo_km": real_format(dados_calculados["custo_km_icev"])},
        ],
        "resumo_sem": [
            {"nome": dados_calculados["modelo_ve"], "tco_final": real_format(dados_calculados["tco_ve_final_s"]), "custo_km": real_format(dados_calculados["custo_km_ve_s"])},
            {"nome": dados_calculados["modelo_icev"], "tco_final": real_format(dados_calculados["tco_icev_final_s"]), "custo_km": real_format(dados_calculados["custo_km_icev_s"])},
        ],
        "grafico": "",
        "grafico_sem_depreciacao": "",
        "grafico_custo_km": "",
        "grafico_revenda_comparativo": "",
        "grafico_depreciacao_v1": "",
        "grafico_depreciacao_v2": "",
    }


# 4.8) Parâmetros comuns da simulação
def extrair_parametros_comuns(dados_form):
    return {
        "energia": conv(dados_form.get("energia", 0)),
        "combustivel": conv(dados_form.get("combustivel", 0)),
        "aumento_energia": conv(dados_form.get("aumento_energia", "0")) / 100.0,
        "aumento_combustivel": conv(dados_form.get("aumento_combustivel", "0")) / 100.0,
        "anos": int(dados_form.get("anos", 1)),
        "km_ano": int(dados_form.get("km_ano", 0)),
    }


# 4.9) Monta veículo elétrico futuro
def montar_veiculo_ve(dados_form):
    ipva_ve = 0.0 if "isencao_ipva_ve" in dados_form else conv(dados_form.get("ipva_ve", 0))

    preco = conv(dados_form.get("preco_ve", 0))
    return {
        "nome": dados_form.get("modelo_ve", "Veículo elétrico"),
        "tipo": "ve",
        "preco": preco,
        "consumo": conv(dados_form.get("consumo_ve", 0)),
        "manut": conv(dados_form.get("manut_ve", 0)),
        "ipva": ipva_ve,
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_ve", preco),
        "depreciacao": conv(dados_form.get("depreciacao_ve", 0)) / 100.0,
        "financiamento": calcular_financiamento_form(dados_form, "ve", preco),
    }


# 4.10) Monta veículo a combustão futuro
def montar_veiculo_icev(dados_form):
    preco = conv(dados_form.get("preco_icev", 0))
    return {
        "nome": dados_form.get("modelo_icev", "Veículo a combustão"),
        "tipo": "icev",
        "preco": preco,
        "consumo": conv(dados_form.get("consumo_icev", 1)),
        "manut": conv(dados_form.get("manut_icev", 0)),
        "ipva": conv(dados_form.get("ipva_icev", 0)),
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_icev", preco),
        "depreciacao": conv(dados_form.get("depreciacao_icev", 0)) / 100.0,
        "financiamento": calcular_financiamento_form(dados_form, "icev", preco),
    }


# 4.11) Monta carro atual
def montar_veiculo_atual(dados_form):
    preco = conv(dados_form.get("preco_atual", 0))
    return {
        "nome": dados_form.get("modelo_atual", "Meu carro atual"),
        "tipo": "icev",
        "preco": preco,
        "consumo": conv(dados_form.get("consumo_atual", 1)),
        "manut": conv(dados_form.get("manut_atual", 0)),
        "ipva": conv(dados_form.get("ipva_atual", 0)),
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_atual", preco),
        "depreciacao": conv(dados_form.get("depreciacao_atual", 0)) / 100.0,
        "financiamento": calcular_financiamento_form(dados_form, "atual", preco),
    }


# ============================================================
# 5) ROTA PRINCIPAL /SIMULAR (AGORA COM TIPOS DE COMPARAÇÃO)
# ============================================================
@tco_bp.route("/simular", methods=["GET", "POST"])
def simular():
    resultado_final = {}

    if request.method == "POST":
        tipo_comparacao = request.form.get("tipo_comparacao", "dois_carros_novos")

        try:
            comparacoes = []

            # ----------------------------------------------------
            # CENÁRIO 1) Comparar dois carros
            # ----------------------------------------------------
            if tipo_comparacao == "dois_carros_novos":
                comum = extrair_parametros_comuns(request.form)

                carro_eletrico = montar_veiculo_ve(request.form)
                carro_combustao = montar_veiculo_icev(request.form)

                proj_eletrico = calcular_projecao_veiculo(carro_eletrico, comum)
                proj_combustao = calcular_projecao_veiculo(carro_combustao, comum)

                comparacoes.append(
                    montar_bloco_resultado(
                        "Comparação direta entre os dois carros selecionados",
                        proj_eletrico,
                        proj_combustao,
                    )
                )

            # ----------------------------------------------------
            # CENÁRIO 2) Trocar meu carro atual por um elétrico
            # ----------------------------------------------------
            elif tipo_comparacao == "trocar_por_eletrico":
                comum = extrair_parametros_comuns(request.form)

                carro_atual = montar_veiculo_atual(request.form)
                carro_eletrico = montar_veiculo_ve(request.form)

                proj_atual = calcular_projecao_veiculo(carro_atual, comum)
                proj_eletrico = calcular_projecao_veiculo(carro_eletrico, comum)

                comparacoes.append(
                    montar_bloco_resultado(
                        "Comparação: meu carro atual vs carro elétrico",
                        proj_atual,
                        proj_eletrico,
                    )
                )

            # ----------------------------------------------------
            # CENÁRIO 3) Trocar meu carro atual e comparar
            #           elétrico OU outro combustão
            # ----------------------------------------------------
            elif tipo_comparacao == "trocar_e_comparar_opcoes":
                comum = extrair_parametros_comuns(request.form)

                carro_atual = montar_veiculo_atual(request.form)
                carro_eletrico = montar_veiculo_ve(request.form)
                outro_combustao = montar_veiculo_icev(request.form)

                proj_atual_1 = calcular_projecao_veiculo(carro_atual, comum)
                proj_eletrico = calcular_projecao_veiculo(carro_eletrico, comum)

                proj_atual_2 = calcular_projecao_veiculo(carro_atual, comum)
                proj_combustao = calcular_projecao_veiculo(outro_combustao, comum)

                comparacoes.append(
                    montar_bloco_resultado(
                        "Comparação 1: meu carro atual vs carro elétrico",
                        proj_atual_1,
                        proj_eletrico,
                    )
                )

                comparacoes.append(
                    montar_bloco_resultado(
                        "Comparação 2: meu carro atual vs outro carro a combustão",
                        proj_atual_2,
                        proj_combustao,
                    )
                )

            resultado_final = {
                "tipo_comparacao": tipo_comparacao,
                "comparacoes": comparacoes,
                "form_values": request.form.to_dict(flat=True),
            }

        except Exception as e:
            print("Erro ao processar simulação:", e)
            flash(
                f"Erro ao processar os dados: {e}. Verifique se todos os campos estão preenchidos corretamente.",
                "danger",
            )

    return render_template("simular.html", resultado=resultado_final)


# ============================================================
# 6) GASOLINA (ANP) - PREÇO MÉDIO POR MUNICÍPIO/ESTADO
# ============================================================

# 6.1) Mapa UF -> Nome Estado na ANP
MAPA_UF_PARA_ESTADO = {
    "AC": "ACRE", "AL": "ALAGOAS", "AP": "AMAPA", "AM": "AMAZONAS", "BA": "BAHIA",
    "CE": "CEARA", "DF": "DISTRITO FEDERAL", "ES": "ESPIRITO SANTO", "GO": "GOIAS",
    "MA": "MARANHAO", "MT": "MATO GROSSO", "MS": "MATO GROSSO DO SUL", "MG": "MINAS GERAIS",
    "PA": "PARA", "PB": "PARAIBA", "PR": "PARANA", "PE": "PERNAMBUCO", "PI": "PIAUI",
    "RJ": "RIO DE JANEIRO", "RN": "RIO GRANDE DO NORTE", "RS": "RIO GRANDE DO SUL",
    "RO": "RONDONIA", "RR": "RORAIMA", "SC": "SANTA CATARINA", "SP": "SAO PAULO",
    "SE": "SERGIPE", "TO": "TOCANTINS",
}

# 6.2) Carrega ANP 1x
@lru_cache(maxsize=1)
def carregar_df_gasolina():
    try:
        df = pd.read_excel(CAMINHO_ANP, skiprows=16)
    except FileNotFoundError:
        print("ARQUIVO ANP NÃO ENCONTRADO:", CAMINHO_ANP)
        return None

    col_estado = None
    col_municipio = None
    col_produto = None
    col_preco = None
    col_mes = None

    for c in df.columns:
        cname = normalizar(c)
        if cname == "ESTADO":
            col_estado = c
        elif cname.startswith("MUNIC"):
            col_municipio = c
        elif cname == "PRODUTO":
            col_produto = c
        elif "PRECO MEDIO REVENDA" in cname:
            col_preco = c
        elif cname in ("MES", "MÊS"):
            col_mes = c

    if not all([col_estado, col_municipio, col_produto, col_preco, col_mes]):
        print("Nao foi possivel identificar todas as colunas na planilha ANP.")
        print("Colunas encontradas:", list(df.columns))
        return None

    df = df[df[col_produto].astype(str).str.upper().str.contains("GASOLINA COMUM")].copy()

    df["ESTADO_NORM"] = df[col_estado].map(normalizar)
    df["MUNIC_NORM"] = df[col_municipio].map(normalizar)

    df["PRECO_REVENDA_NUM"] = (
        df[col_preco].astype(str)
        .str.replace(",", ".", regex=False)
        .str.replace(" ", "", regex=False)
    )
    df["PRECO_REVENDA_NUM"] = pd.to_numeric(df["PRECO_REVENDA_NUM"], errors="coerce")

    df["MES_RAW"] = df[col_mes]
    df = df.reset_index(drop=True)

    print("Planilha ANP carregada. Linhas:", len(df))
    return df

# 6.3) Preço gasolina: município -> fallback estado
def obter_preco_gasolina(uf: str, municipio: str):
    df = carregar_df_gasolina()
    if df is None:
        return None

    uf = (uf or "").upper().strip()
    municipio_norm = normalizar(municipio)
    nome_estado_norm = MAPA_UF_PARA_ESTADO.get(uf, "")

    filtro_mun = df["MUNIC_NORM"].str.contains(municipio_norm, na=False)
    if nome_estado_norm:
        filtro_mun = filtro_mun & (df["ESTADO_NORM"] == nome_estado_norm)

    df_mun = df.loc[filtro_mun]

    if not df_mun.empty:
        ultimo_mes = df_mun["MES_RAW"].iloc[-1]
        df_mun_ult = df_mun[df_mun["MES_RAW"] == ultimo_mes]
        preco = df_mun_ult["PRECO_REVENDA_NUM"].mean()
        print(f"[ANP] Encontrado municipio {municipio_norm} / {uf} no mes {ultimo_mes}: {preco}")
        return round(float(preco), 3) if pd.notna(preco) else None

    if nome_estado_norm:
        df_est = df[df["ESTADO_NORM"] == nome_estado_norm]
        if not df_est.empty:
            ultimo_mes_est = df_est["MES_RAW"].iloc[-1]
            df_est_ult = df_est[df_est["MES_RAW"] == ultimo_mes_est]
            preco_est = df_est_ult["PRECO_REVENDA_NUM"].mean()
            print(f"[ANP] Usando media do estado {nome_estado_norm} no mes {ultimo_mes_est}: {preco_est}")
            return round(float(preco_est), 3) if pd.notna(preco_est) else None

    print(f"[ANP] Nao foi possivel achar preco para {municipio_norm}/{uf}")
    return None

# 6.4) Endpoint gasolina
@tco_bp.route("/preco_combustivel")
def preco_combustivel():
    uf = (request.args.get("uf", "") or "").upper()
    municipio = request.args.get("municipio", "") or ""

    if not uf or not municipio:
        return jsonify({"erro": "UF e município são obrigatórios"}), 400

    try:
        preco = obter_preco_gasolina(uf, municipio)
        return jsonify({"preco": preco, "uf": uf, "municipio": municipio})
    except Exception as e:
        print("Erro ao calcular preço de combustível:", e)
        return jsonify({"erro": "Falha ao calcular preço de combustível"}), 500

# ============================================================
# 7) MUNICÍPIOS -> DISTRIBUIDORA + IMPOSTOS (TABELA LOCAL)
# ============================================================

# 7.1) Carrega municipios.xlsx 1x
@lru_cache(maxsize=1)
def carregar_df_municipios():
    """
    Lê a planilha municipios.xlsx.
    Esperado:
      A: Distribuidora
      B: Município
      C: Estado
      G: estado,icms,pis,cofins
    """
    try:
        df = pd.read_excel(CAMINHO_MUNICIPIOS)
    except FileNotFoundError:
        print("ARQUIVO municipios.xlsx NÃO ENCONTRADO:", CAMINHO_MUNICIPIOS)
        return None

    col_dist = None
    col_mun = None
    col_uf = None

    for c in df.columns:
        c_norm = normalizar(c)
        if c_norm == "DISTRIBUIDORA":
            col_dist = c
        elif c_norm == "MUNICIPIO":
            col_mun = c
        elif c_norm in ("ESTADO", "UF"):
            col_uf = c

    # fallback direto pelos nomes comuns
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
        print("[MUNICIPIOS] Não achei as colunas esperadas.")
        print("[MUNICIPIOS] Colunas encontradas:", list(df.columns))
        return None

    df["UF"] = df[col_uf].astype(str).str.upper().str.strip()
    df["MunicipioNorm"] = df[col_mun].astype(str).map(normalizar)
    df["DistribuidoraRaw"] = df[col_dist].astype(str).str.strip()

    print("Planilha de municípios carregada. Linhas:", len(df))
    return df


# 7.2) Descobre distribuidora pelo município
def obter_distribuidora_por_municipio(uf: str, municipio: str):
    df = carregar_df_municipios()
    if df is None:
        return None

    uf = (uf or "").upper().strip()
    municipio_norm = normalizar(municipio)

    df_uf = df[df["UF"] == uf]
    if df_uf.empty:
        print(f"[MUNICIPIOS] Nenhuma linha para UF {uf}")
        return None

    # tentativa exata
    df_mun = df_uf[df_uf["MunicipioNorm"] == municipio_norm]

    # fallback aproximado
    if df_mun.empty:
        df_mun = df_uf[df_uf["MunicipioNorm"].str.contains(municipio_norm, na=False)]

    if df_mun.empty:
        print(f"[MUNICIPIOS] Nao encontrado municipio {municipio} / {uf}")
        return None

    dist = df_mun.iloc[0]["DistribuidoraRaw"]
    print(f"[MUNICIPIOS] {municipio}/{uf} -> distribuidora '{dist}'")
    return dist


# 7.3) Carrega impostos (ICMS/PIS/COFINS) da COLUNA G
@lru_cache(maxsize=1)
def carregar_impostos_uf():
    try:
        df = pd.read_excel(CAMINHO_MUNICIPIOS)
    except Exception as e:
        print("[IMPOSTOS] Não consegui abrir municipios.xlsx:", e)
        return {}

    col_alvo = None
    for c in df.columns:
        if normalizar(c) == normalizar("estado,icms,pis,cofins"):
            col_alvo = c
            break

    if col_alvo is None:
        print("[IMPOSTOS] Não achei a coluna 'estado,icms,pis,cofins' no sheet principal.")
        print("[IMPOSTOS] Colunas encontradas:", list(df.columns))
        return {}

    mapa = {}

    for v in df[col_alvo].dropna().astype(str).tolist():
        v = v.strip()

        # pula cabeçalho repetido
        if normalizar(v) == normalizar("estado,icms,pis,cofins"):
            continue

        parts = [p.strip() for p in v.split(",")]
        if len(parts) < 4:
            continue

        uf = parts[0].upper()
        icms = conv(parts[1])
        pis = conv(parts[2])
        cofins = conv(parts[3])

        if uf:
            mapa[uf] = {
                "icms": icms,
                "pis": pis,
                "cofins": cofins
            }

    print(f"[IMPOSTOS] Carregado da coluna '{col_alvo}' -> {len(mapa)} UFs")
    return mapa


# 7.4) Busca impostos por UF
def obter_impostos_por_uf(uf: str):
    uf = (uf or "").upper().strip()
    mapa = carregar_impostos_uf()
    return mapa.get(uf, {"icms": 0.0, "pis": 0.0, "cofins": 0.0})

# ============================================================
# 8) ANEEL (TUSD/TE) + VIGÊNCIA + TARIFA FINAL COM IMPOSTOS
#    (agora usando o nome EXATO da planilha / ANEEL)
# ============================================================

from datetime import date
import re

# 8.1) Config ANEEL
ANEEL_SQL_BASE_URL = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search_sql"
ANEEL_RESOURCE_ID = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"

# 8.2) Nome da distribuidora -> SigAgente
# Agora sua planilha já está igual à ANEEL.
# Então NÃO vamos mais fazer de/para.
def mapear_para_sigagente(nome_distribuidora: str) -> str:
    if not nome_distribuidora:
        return ""
    return str(nome_distribuidora).strip()


# 8.3) Nome da distribuidora -> SigAgente
# Agora a planilha já está quase igual à ANEEL.
# Regra:
#   - usa UPPER/sem acento para a maioria
#   - mantém poucos casos especiais exatamente como a ANEEL usa
MAPA_SIGAGENTE_EXATO = {
    "CPFL SANTA CRUZ": "CPFL Santa Cruz",
    "NEOENERGIA BRASILIA": "Neoenergia Brasília",
    "NEOENERGIA PE": "Neoenergia PE",
    "CERACA": "Ceraçá",
    "CERIPA": "CERIPa",
}

def mapear_para_sigagente(nome_distribuidora: str) -> str:
    if not nome_distribuidora:
        return ""

    base = normalizar(nome_distribuidora)

    # casos especiais que a ANEEL não guarda em UPPER puro
    if base in MAPA_SIGAGENTE_EXATO:
        return MAPA_SIGAGENTE_EXATO[base]

    # regra geral: exatamente como a ANEEL costuma devolver
    return base

# 8.4) Sugestões de SigAgente (caso ainda falhe algum nome)
def sugerir_sigagente_aneel(sig_digitado: str, limit: int = 25):
    """
    Busca parecidos na ANEEL caso o nome exato não seja encontrado.
    """
    s = (sig_digitado or "").strip()
    if not s:
        return []

    tokens = [t for t in s.replace("-", " ").split() if len(t) >= 3]
    if not tokens:
        tokens = [s]

    likes_or = " OR ".join([f'"SigAgente" ILIKE \'%{t}%\'' for t in tokens])

    sql = f"""
        SELECT DISTINCT "SigAgente"
        FROM "{ANEEL_RESOURCE_ID}"
        WHERE ({likes_or})
        LIMIT {int(limit)}
    """

    try:
        resp = requests.get(ANEEL_SQL_BASE_URL, params={"sql": sql}, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            return []

        recs = data.get("result", {}).get("records", [])
        out = [r.get("SigAgente") for r in recs if r.get("SigAgente")]

        # remove duplicados mantendo ordem
        vistos = set()
        unicos = []
        for x in out:
            if x not in vistos:
                unicos.append(x)
                vistos.add(x)

        return unicos
    except Exception:
        return []


# 8.5) Consulta ANEEL e escolhe o registro correto
def obter_tarifa_energia_por_distribuidora(nome_distribuidora: str):
    """
    Retorna:
      - tarifa_base_kwh
      - tusd_kwh
      - te_kwh
      - inicio_vig
      - fim_vig
      - base_tarifaria
      - detalhe

    Regras:
      - B1 / Residencial / Convencional
      - prefere Tarifa de Aplicação
      - prefere Detalhe = Não se aplica
      - prefere registro vigente hoje
    """
    sig = mapear_para_sigagente(nome_distribuidora)
    if not sig:
        print("[ANEEL] SigAgente vazio.")
        return None

    sql = f"""
        SELECT
            "SigAgente",
            "DscBaseTarifaria",
            "DscSubGrupo",
            "DscClasse",
            "DscModalidadeTarifaria",
            "DscSubClasse",
            "DscDetalhe",
            "DscUnidadeTerciaria",
            "DatInicioVigencia",
            "DatFimVigencia",
            "VlrTUSD",
            "VlrTE"
        FROM "{ANEEL_RESOURCE_ID}"
        WHERE "SigAgente" = '{sig}'
          AND "DscSubGrupo" = 'B1'
          AND "DscClasse" = 'Residencial'
          AND "DscModalidadeTarifaria" = 'Convencional'
          AND "DscSubClasse" = 'Residencial'
          AND "DscBaseTarifaria" IN ('Tarifa de Aplicação', 'Base Econômica')
        ORDER BY "DatInicioVigencia" DESC
        LIMIT 200
    """

    try:
        resp = requests.get(ANEEL_SQL_BASE_URL, params={"sql": sql}, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print("Erro ao consultar API ANEEL (SQL):", e)
        return None

    if not data.get("success"):
        print("[ANEEL] Resposta sem success:", data)
        return None

    records = data.get("result", {}).get("records", [])
    if not records:
        print(f"[ANEEL] Sem registros para '{sig}'. Vou sugerir SigAgente semelhante...")
        sugestoes = sugerir_sigagente_aneel(sig, limit=25)
        if sugestoes:
            print(f"[ANEEL] Sugestões de SigAgente para '{sig}':")
            for x in sugestoes:
                print("   -", x)
        else:
            print(f"[ANEEL] Nenhuma sugestão encontrada para '{sig}'.")
        return None

    def prioridade_base(r):
        base = str(r.get("DscBaseTarifaria") or "").strip().upper()
        return 0 if base == "TARIFA DE APLICAÇÃO".upper() else 1

    def prioridade_detalhe(r):
        det = str(r.get("DscDetalhe") or "").strip().upper()
        # "Não se aplica" é o consumidor padrão, melhor que SCEE
        return 0 if det == "NÃO SE APLICA".upper() else 1

    hoje = date.today()
    candidatos = []

    for rec in records:
        unidade = str(rec.get("DscUnidadeTerciaria") or "").strip().upper()
        tusd = _parse_valor_monetario(rec.get("VlrTUSD"))
        te = _parse_valor_monetario(rec.get("VlrTE"))

        if tusd <= 0 and te <= 0:
            continue
        if unidade not in ("MWH", "KWH"):
            continue

        di = _parse_data_aneel(rec.get("DatInicioVigencia"))
        df = _parse_data_aneel(rec.get("DatFimVigencia"))

        vigente = False
        if di and df:
            vigente = (di <= hoje <= df)
        elif di and not df:
            vigente = (di <= hoje)

        total_mwh = tusd + te

        candidatos.append((
            not vigente,             # vigente primeiro
            prioridade_base(rec),   # tarifa de aplicação primeiro
            prioridade_detalhe(rec),# "não se aplica" primeiro
            -total_mwh,             # maior valor total primeiro
            rec
        ))

    if not candidatos:
        print(f"[ANEEL] Sem candidatos válidos para '{sig}'")
        return None

    candidatos.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    rec = candidatos[0][4]

    tusd = _parse_valor_monetario(rec.get("VlrTUSD"))
    te = _parse_valor_monetario(rec.get("VlrTE"))
    unidade = str(rec.get("DscUnidadeTerciaria") or "").strip().upper()
    detalhe = rec.get("DscDetalhe")
    base_tarif = rec.get("DscBaseTarifaria")

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
        f"[ANEEL] Usando registro SigAgente={sig} BaseTarifaria={base_tarif} "
        f"Detalhe={detalhe} DataInicioVigencia={inicio_vig} DataFimVigencia={fim_vig} "
        f"TUSD={tusd} TE={te} unidade={unidade} -> {tarifa_base_kwh:.5f} R$/kWh"
    )

    return {
        "sigagente": sig,
        "tarifa_base_kwh": round(tarifa_base_kwh, 5),
        "tusd_kwh": round(tusd_kwh, 5),
        "te_kwh": round(te_kwh, 5),
        "inicio_vig": str(inicio_vig) if inicio_vig else None,
        "fim_vig": str(fim_vig) if fim_vig else None,
        "base_tarifaria": base_tarif,
        "detalhe": detalhe,
    }


# 8.6) Calcula tarifa final com impostos
def calcular_tarifa_com_impostos(tarifa_base_kwh: float, uf: str):
    imp = obter_impostos_por_uf(uf)  # vem da sua sessão 7
    icms = float(imp.get("icms", 0.0))
    pis = float(imp.get("pis", 0.0))
    cofins = float(imp.get("cofins", 0.0))

    fator = 1.0 + (icms / 100.0) + (pis / 100.0) + (cofins / 100.0)
    tarifa_total = tarifa_base_kwh * fator

    v_icms = tarifa_base_kwh * (icms / 100.0)
    v_pis = tarifa_base_kwh * (pis / 100.0)
    v_cofins = tarifa_base_kwh * (cofins / 100.0)

    return {
        "icms_pct": icms,
        "pis_pct": pis,
        "cofins_pct": cofins,
        "icms_kwh": round(v_icms, 5),
        "pis_kwh": round(v_pis, 5),
        "cofins_kwh": round(v_cofins, 5),
        "tarifa_total_kwh": round(tarifa_total, 5),
    }


# 8.7) Endpoint energia
@tco_bp.route("/preco_energia")
def preco_energia():
    uf = (request.args.get("uf", "") or "").upper()
    municipio = request.args.get("municipio", "") or ""

    if not uf or not municipio:
        return jsonify({
            "tarifa_kwh": None,
            "tarifa_base_kwh": None,
            "distribuidora": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": None,
            "mensagem": "UF e município são obrigatórios."
        }), 400

    dist = obter_distribuidora_por_municipio(uf, municipio)
    if not dist:
        return jsonify({
            "tarifa_kwh": None,
            "tarifa_base_kwh": None,
            "distribuidora": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": None,
            "mensagem": "Não achei a distribuidora na sua tabela local. Ajuste manualmente."
        })

    dados_aneel = obter_tarifa_energia_por_distribuidora(dist)
    if dados_aneel is None:
        tarifa_fallback = {
            "AC": 0.95, "AL": 0.88, "AP": 0.78, "AM": 0.88, "BA": 0.91,
            "CE": 0.86, "DF": 0.84, "ES": 0.82, "GO": 0.86, "MA": 0.83,
            "MT": 0.89, "MS": 0.84, "MG": 0.90, "PA": 0.93, "PB": 0.84,
            "PR": 0.82, "PE": 0.87, "PI": 0.86, "RJ": 0.98, "RN": 0.86,
            "RS": 0.88, "RO": 0.85, "RR": 0.78, "SC": 0.78, "SP": 0.82,
            "SE": 0.88, "TO": 0.83,
        }.get(uf, 0.80)
        return jsonify({
            "tarifa_kwh": round(float(tarifa_fallback), 5),
            "tarifa_base_kwh": round(float(tarifa_fallback), 5),
            "distribuidora": dist,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": {
                "tusd_kwh": 0, "te_kwh": 0, "icms_kwh": 0, "pis_kwh": 0, "cofins_kwh": 0,
                "icms_pct": 0, "pis_pct": 0, "cofins_pct": 0,
                "base_tarifaria": "Estimativa local",
                "sigagente": mapear_para_sigagente(dist),
                "detalhe_aneel": "Fallback usado porque a consulta ANEEL falhou",
            },
            "mensagem": f"Tarifa preenchida por estimativa local para {uf}, pois a ANEEL não retornou. Você pode ajustar manualmente."
        })

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

    msg = (
        f"Tarifa B1 Residencial ({dist}) com impostos (ICMS/PIS/COFINS da sua planilha). "
        f"Vigência ANEEL: {dados_aneel['inicio_vig']} até {dados_aneel['fim_vig']}."
    )

    return jsonify({
        "tarifa_kwh": round(tarifa_total, 5),      # final com impostos
        "tarifa_base_kwh": round(base_kwh, 5),     # base ANEEL
        "distribuidora": dist,
        "vigencia_inicio": dados_aneel["inicio_vig"],
        "vigencia_fim": dados_aneel["fim_vig"],
        "detalhe": detalhe,
        "mensagem": msg
    })

# ============================================================
# 9) FIPE (CARROS)
# ============================================================
FIPE_BASE = "https://parallelum.com.br/fipe/api/v1/carros"
_tco_fipe_service = FipeService()

def _erro_fipe_tco(exc: Exception, fallback, status: int = 500):
    if isinstance(exc, FipeApiError):
        code = exc.status_code or status
        if code < 400:
            code = status
        payload = exc.to_dict()
        if isinstance(fallback, dict):
            payload.update({k: v for k, v in fallback.items() if k not in payload})
        return jsonify(payload), code
    print("Erro FIPE TCO:", exc)
    return jsonify(fallback), status

@tco_bp.route("/fipe/marcas")
def fipe_marcas():
    contexto = (request.args.get("contexto") or request.args.get("tipo") or "").strip()
    try:
        return jsonify(_tco_fipe_service.listar_marcas(contexto=contexto))
    except Exception as e:
        return _erro_fipe_tco(e, [])

@tco_bp.route("/fipe/modelos")
def fipe_modelos():
    codigo_marca = (request.args.get("codigo_marca") or "").strip()
    contexto = (request.args.get("contexto") or request.args.get("tipo") or "").strip()
    nome_marca = (request.args.get("nome_marca") or "").strip()
    if not codigo_marca:
        return jsonify({"modelos": []})
    try:
        return jsonify(_tco_fipe_service.listar_modelos(codigo_marca, contexto=contexto, nome_marca=nome_marca))
    except Exception as e:
        return _erro_fipe_tco(e, {"modelos": []})

@tco_bp.route("/fipe/anos")
def fipe_anos():
    codigo_marca = (request.args.get("codigo_marca") or "").strip()
    codigo_modelo = (request.args.get("codigo_modelo") or "").strip()
    contexto = (request.args.get("contexto") or request.args.get("tipo") or "").strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify([])
    try:
        return jsonify(_tco_fipe_service.listar_anos(codigo_marca, codigo_modelo, contexto=contexto))
    except Exception as e:
        return _erro_fipe_tco(e, [])

@tco_bp.route("/fipe/preco")
def fipe_preco():
    codigo_marca = (request.args.get("codigo_marca") or "").strip()
    codigo_modelo = (request.args.get("codigo_modelo") or "").strip()
    codigo_ano = (request.args.get("codigo_ano") or "").strip()
    if not (codigo_marca and codigo_modelo and codigo_ano):
        return jsonify({"erro": "Parâmetros incompletos"}), 400
    try:
        return jsonify(_tco_fipe_service.consultar_preco(codigo_marca, codigo_modelo, codigo_ano))
    except Exception as e:
        return _erro_fipe_tco(e, {"erro": "Erro ao consultar FIPE"})

# ============================================================
# 10) IPVA (MANTIDO COMO ESTAVA - ACADÊMICO)
# ============================================================
ALIQUOTAS_IPVA_CARRO = {
    "AC": 0.02, "AL": 0.03, "AP": 0.03, "AM": 0.03, "BA": 0.03, "CE": 0.03,
    "DF": 0.04, "ES": 0.02, "GO": 0.04, "MA": 0.03, "MT": 0.03, "MS": 0.04,
    "MG": 0.04, "PA": 0.03, "PB": 0.03, "PR": 0.04, "PE": 0.03, "PI": 0.03,
    "RJ": 0.04, "RN": 0.03, "RS": 0.03, "RO": 0.03, "RR": 0.03, "SC": 0.02,
    "SP": 0.04, "SE": 0.03, "TO": 0.02,
}
ANOS_ISENCAO_IPVA = {"SP": 20, "ES": 15, "RR": 10, "TO": 30}
UF_ISENCAO_ELETRICO_TOTAL = {"DF", "RN", "RS", "PE", "PB", "AC"}

def classificar_eletrificado(combustivel_str: str) -> bool:
    if not combustivel_str:
        return False
    texto = combustivel_str.lower()
    return ("elétric" in texto) or ("eletric" in texto) or ("híbrido" in texto) or ("hibrido" in texto)

def calcular_ipva_estado(uf: str, valor_veiculo: float, ano_fabricacao, eletrificado: bool = False) -> float:
    uf = (uf or "").upper()
    if valor_veiculo <= 0:
        return 0.0

    ano_atual = datetime.now().year
    try:
        ano_int = int(ano_fabricacao)
    except (TypeError, ValueError):
        ano_int = None

    idade = max(0, ano_atual - ano_int) if ano_int else 0

    limite_idade = ANOS_ISENCAO_IPVA.get(uf)
    if limite_idade is not None and ano_int and idade >= limite_idade:
        return 0.0

    if eletrificado and uf in UF_ISENCAO_ELETRICO_TOTAL:
        return 0.0

    aliquota = ALIQUOTAS_IPVA_CARRO.get(uf, 0.03)
    ipva = valor_veiculo * aliquota
    return round(ipva, 2)

@tco_bp.route("/ipva_estimado")
def ipva_estimado():
    uf = (request.args.get("uf", "") or "").upper()
    valor_str = request.args.get("valor", "") or "0"
    ano = request.args.get("ano", "") or ""
    combustivel = request.args.get("combustivel", "") or ""

    valor = conv(valor_str)
    eletrificado = classificar_eletrificado(combustivel)

    ipva = calcular_ipva_estado(
        uf=uf,
        valor_veiculo=valor,
        ano_fabricacao=ano,
        eletrificado=eletrificado,
    )
    return jsonify({"ipva": ipva})

