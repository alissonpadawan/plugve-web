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
    return redirect(url_for("main.index"))

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


# 4.2) Helper visual
def real_format(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# 4.3) Layout padrão dos gráficos
def obter_layout_web():
    return {
        "width": 700,
        "height": 450,
        "legend": dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        "margin": dict(l=50, r=50, t=40, b=40),
    }


# 4.4) Projeção genérica de um veículo
def calcular_projecao_veiculo(veiculo, comum):
    nome = veiculo.get("nome", "Veículo")
    tipo = veiculo.get("tipo", "icev")  # ve ou icev

    preco = float(veiculo.get("preco", 0))
    consumo = float(veiculo.get("consumo", 0))
    manut = float(veiculo.get("manut", 0))
    ipva = float(veiculo.get("ipva", 0))
    seguro = float(veiculo.get("seguro", 0))
    depreciacao = float(veiculo.get("depreciacao", 0))

    energia_inicial = float(comum.get("energia", 0))
    combustivel_inicial = float(comum.get("combustivel", 0))
    aumento_energia = float(comum.get("aumento_energia", 0))
    aumento_combustivel = float(comum.get("aumento_combustivel", 0))
    anos = int(comum.get("anos", 1))
    km_ano = int(comum.get("km_ano", 0))

    tco = preco
    tco_s = preco
    preco_atual = preco

    energia_anual = energia_inicial
    combustivel_anual = combustivel_inicial

    anos_lista = []
    tco_lista = []
    tco_lista_s = []

    for ano in range(1, anos + 1):
        if ano > 1:
            energia_anual *= 1 + aumento_energia
            combustivel_anual *= 1 + aumento_combustivel

        preco_atual *= 1 - depreciacao

        if tipo == "ve":
            custo_uso = km_ano * consumo * energia_anual
        else:
            custo_uso = (km_ano / consumo * combustivel_anual) if consumo > 0 else 0.0

        custo_anual = custo_uso + manut + ipva + seguro

        tco += custo_anual
        tco_s += custo_anual

        tco_lista.append(tco - preco_atual)
        tco_lista_s.append(tco_s - preco)

        anos_lista.append(f"Ano {ano}")

    total_km = anos * km_ano if anos > 0 and km_ano > 0 else 1

    return {
        "nome": nome,
        "tipo": tipo,
        "anos_lista": anos_lista,
        "tco_final": tco - preco_atual,
        "tco_final_s": tco_s - preco,
        "custo_km": (tco - preco_atual) / total_km,
        "custo_km_s": (tco_s - preco) / total_km,
        "tco_lista": tco_lista,
        "tco_lista_s": tco_lista_s,
    }


# 4.5) Gera gráficos de comparação entre 2 veículos
def gerar_graficos_dupla(v1, v2):
    layout_web = obter_layout_web()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=v1["anos_lista"],
        y=v1["tco_lista"],
        mode="lines+markers",
        name=v1["nome"],
    ))
    fig.add_trace(go.Scatter(
        x=v2["anos_lista"],
        y=v2["tco_lista"],
        mode="lines+markers",
        name=v2["nome"],
    ))
    fig.update_layout(title_text="TCO acumulado COM depreciação", **layout_web)

    fig_s = go.Figure()
    fig_s.add_trace(go.Scatter(
        x=v1["anos_lista"],
        y=v1["tco_lista_s"],
        mode="lines+markers",
        name=v1["nome"],
    ))
    fig_s.add_trace(go.Scatter(
        x=v2["anos_lista"],
        y=v2["tco_lista_s"],
        mode="lines+markers",
        name=v2["nome"],
    ))
    fig_s.update_layout(title_text="TCO acumulado SEM depreciação", **layout_web)

    fig_custo_km = go.Figure()
    fig_custo_km.add_trace(go.Bar(
        x=[v1["nome"], v2["nome"]],
        y=[v1["custo_km"], v2["custo_km"]],
        text=[real_format(v1["custo_km"]), real_format(v2["custo_km"])],
        textposition="auto",
    ))
    fig_custo_km.update_layout(
        title_text="Custo por quilômetro rodado (R$/km)",
        width=500,
        height=400,
        yaxis_title="R$ / km",
    )

    return {
        "grafico": pio.to_html(fig, include_plotlyjs=False, full_html=False),
        "grafico_sem_depreciacao": pio.to_html(fig_s, include_plotlyjs=False, full_html=False),
        "grafico_custo_km": pio.to_html(fig_custo_km, include_plotlyjs=False, full_html=False),
    }


# 4.6) Empacota 1 comparação pronta para renderização
def montar_bloco_resultado(titulo, v1, v2):
    graficos = gerar_graficos_dupla(v1, v2)

    return {
        "titulo": titulo,
        "resumo_com": [
            {
                "nome": v1["nome"],
                "tco_final": real_format(v1["tco_final"]),
                "custo_km": real_format(v1["custo_km"]),
            },
            {
                "nome": v2["nome"],
                "tco_final": real_format(v2["tco_final"]),
                "custo_km": real_format(v2["custo_km"]),
            },
        ],
        "resumo_sem": [
            {
                "nome": v1["nome"],
                "tco_final": real_format(v1["tco_final_s"]),
                "custo_km": real_format(v1["custo_km_s"]),
            },
            {
                "nome": v2["nome"],
                "tco_final": real_format(v2["tco_final_s"]),
                "custo_km": real_format(v2["custo_km_s"]),
            },
        ],
        "grafico": graficos["grafico"],
        "grafico_sem_depreciacao": graficos["grafico_sem_depreciacao"],
        "grafico_custo_km": graficos["grafico_custo_km"],
    }


# 4.7) Converte resultado antigo para o novo formato de tela
def montar_bloco_resultado_cenario_original(dados_calculados):
    layout_web = obter_layout_web()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dados_calculados["anos_lista"],
        y=dados_calculados["tco_ve_lista"],
        mode="lines+markers",
        name=dados_calculados["modelo_ve"],
    ))
    fig.add_trace(go.Scatter(
        x=dados_calculados["anos_lista"],
        y=dados_calculados["tco_icev_lista"],
        mode="lines+markers",
        name=dados_calculados["modelo_icev"],
    ))
    fig.update_layout(title_text="TCO acumulado COM depreciação", **layout_web)

    fig_s = go.Figure()
    fig_s.add_trace(go.Scatter(
        x=dados_calculados["anos_lista"],
        y=dados_calculados["tco_ve_lista_s"],
        mode="lines+markers",
        name=dados_calculados["modelo_ve"],
    ))
    fig_s.add_trace(go.Scatter(
        x=dados_calculados["anos_lista"],
        y=dados_calculados["tco_icev_lista_s"],
        mode="lines+markers",
        name=dados_calculados["modelo_icev"],
    ))
    fig_s.update_layout(title_text="TCO acumulado SEM depreciação", **layout_web)

    fig_custo_km = go.Figure()
    fig_custo_km.add_trace(go.Bar(
        x=[dados_calculados["modelo_ve"], dados_calculados["modelo_icev"]],
        y=[dados_calculados["custo_km_ve"], dados_calculados["custo_km_icev"]],
        text=[real_format(dados_calculados["custo_km_ve"]), real_format(dados_calculados["custo_km_icev"])],
        textposition="auto",
    ))
    fig_custo_km.update_layout(
        title_text="Custo por quilômetro rodado (R$/km)",
        width=500,
        height=400,
        yaxis_title="R$ / km",
    )

    return {
        "titulo": "Comparação direta entre os dois carros selecionados",
        "resumo_com": [
            {
                "nome": dados_calculados["modelo_ve"],
                "tco_final": real_format(dados_calculados["tco_ve_final"]),
                "custo_km": real_format(dados_calculados["custo_km_ve"]),
            },
            {
                "nome": dados_calculados["modelo_icev"],
                "tco_final": real_format(dados_calculados["tco_icev_final"]),
                "custo_km": real_format(dados_calculados["custo_km_icev"]),
            },
        ],
        "resumo_sem": [
            {
                "nome": dados_calculados["modelo_ve"],
                "tco_final": real_format(dados_calculados["tco_ve_final_s"]),
                "custo_km": real_format(dados_calculados["custo_km_ve_s"]),
            },
            {
                "nome": dados_calculados["modelo_icev"],
                "tco_final": real_format(dados_calculados["tco_icev_final_s"]),
                "custo_km": real_format(dados_calculados["custo_km_icev_s"]),
            },
        ],
        "grafico": pio.to_html(fig, include_plotlyjs=False, full_html=False),
        "grafico_sem_depreciacao": pio.to_html(fig_s, include_plotlyjs=False, full_html=False),
        "grafico_custo_km": pio.to_html(fig_custo_km, include_plotlyjs=False, full_html=False),
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

    return {
        "nome": dados_form.get("modelo_ve", "Veículo elétrico"),
        "tipo": "ve",
        "preco": conv(dados_form.get("preco_ve", 0)),
        "consumo": conv(dados_form.get("consumo_ve", 0)),
        "manut": conv(dados_form.get("manut_ve", 0)),
        "ipva": ipva_ve,
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_ve", conv(dados_form.get("preco_ve", 0))),
        "depreciacao": conv(dados_form.get("depreciacao_ve", 0)) / 100.0,
    }


# 4.10) Monta veículo a combustão futuro
def montar_veiculo_icev(dados_form):
    return {
        "nome": dados_form.get("modelo_icev", "Veículo a combustão"),
        "tipo": "icev",
        "preco": conv(dados_form.get("preco_icev", 0)),
        "consumo": conv(dados_form.get("consumo_icev", 1)),
        "manut": conv(dados_form.get("manut_icev", 0)),
        "ipva": conv(dados_form.get("ipva_icev", 0)),
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_icev", conv(dados_form.get("preco_icev", 0))),
        "depreciacao": conv(dados_form.get("depreciacao_icev", 0)) / 100.0,
    }


# 4.11) Monta carro atual
def montar_veiculo_atual(dados_form):
    return {
        "nome": dados_form.get("modelo_atual", "Meu carro atual"),
        "tipo": "icev",
        "preco": conv(dados_form.get("preco_atual", 0)),
        "consumo": conv(dados_form.get("consumo_atual", 1)),
        "manut": conv(dados_form.get("manut_atual", 0)),
        "ipva": conv(dados_form.get("ipva_atual", 0)),
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_atual", conv(dados_form.get("preco_atual", 0))),
        "depreciacao": conv(dados_form.get("depreciacao_atual", 0)) / 100.0,
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
                dados_calculados = calcular_tco_completo(request.form)
                comparacoes.append(
                    montar_bloco_resultado_cenario_original(dados_calculados)
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

@lru_cache(maxsize=512)
def _fipe_get_json_cache(endpoint: str):
    resp = requests.get(f"{FIPE_BASE}/{endpoint.lstrip('/')}", timeout=20)
    resp.raise_for_status()
    return resp.json()

@tco_bp.route("/fipe/marcas")
def fipe_marcas():
    try:
        return jsonify(_fipe_get_json_cache("marcas"))
    except Exception as e:
        print("Erro FIPE /marcas:", e)
        return jsonify([]), 500

@tco_bp.route("/fipe/modelos")
def fipe_modelos():
    codigo_marca = request.args.get("codigo_marca")
    if not codigo_marca:
        return jsonify({"modelos": []})
    try:
        return jsonify(_fipe_get_json_cache(f"marcas/{codigo_marca}/modelos"))
    except Exception as e:
        print("Erro FIPE /modelos:", e)
        return jsonify({"modelos": []}), 500

@tco_bp.route("/fipe/anos")
def fipe_anos():
    codigo_marca = request.args.get("codigo_marca")
    codigo_modelo = request.args.get("codigo_modelo")
    if not codigo_marca or not codigo_modelo:
        return jsonify([])
    try:
        return jsonify(_fipe_get_json_cache(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos"))
    except Exception as e:
        print("Erro FIPE /anos:", e)
        return jsonify([]), 500

@tco_bp.route("/fipe/preco")
def fipe_preco():
    codigo_marca = request.args.get("codigo_marca")
    codigo_modelo = request.args.get("codigo_modelo")
    codigo_ano = request.args.get("codigo_ano")
    if not (codigo_marca and codigo_modelo and codigo_ano):
        return jsonify({"erro": "Parâmetros incompletos"}), 400
    try:
        return jsonify(_fipe_get_json_cache(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}"))
    except Exception as e:
        print("Erro FIPE /preco:", e)
        return jsonify({"erro": "Erro ao consultar FIPE"}), 500

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

