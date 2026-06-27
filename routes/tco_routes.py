# Módulo TCO integrado a partir da calculadora original.
# Mantido separado do app.py principal para preservar modularidade.
# ============================================================
# 0) IMPORTS E APP
# ============================================================
from flask import Blueprint, render_template, request, flash, jsonify, redirect, url_for, abort
import plotly.graph_objs as go
import plotly.io as pio
import os
import uuid
import re
from pathlib import Path
from datetime import datetime, date
import requests
import pandas as pd
import unicodedata
from functools import lru_cache

from services.fipe_service import FipeService, FipeApiError

tco_bp = Blueprint("tco", __name__)

# Cache leve em memória para abrir a auditoria técnica em nova guia logo após a simulação.
# Não é persistência metodológica; serve apenas para transportar a memória recém-calculada.
AUDITORIA_TCO_CACHE = {}
AUDITORIA_TCO_CACHE_MAX = 20

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

# Fatores ambientais iniciais usados na seção de impacto ambiental.
# A estimativa é operacional: não inclui fabricação do veículo, bateria,
# transporte, manutenção ou descarte. Os valores ficam centralizados aqui
# para facilitar revisão metodológica posterior na dissertação.
FATOR_CO2_ENERGIA_KG_KWH = 0.0289   # MCTI/SIN: 0,0289 tCO2/MWh = 0,0289 kgCO2/kWh
FATOR_CO2_GASOLINA_KG_L = 2.212     # gasolina comercial: premissa inicial kgCO2/L
FATOR_CO2_ETANOL_KG_L = 0.0         # etanol: CO2 fóssil da queima tratado como biogênico separado
FATOR_CO2_ETANOL_BIOGENICO_KG_L = 1.526  # etanol hidratado: CO2 biogênico reportado à parte
FATOR_CO2_DIESEL_S10_KG_L = 2.603   # diesel S10/comercial: premissa inicial kgCO2/L
FATOR_ARVORE_TCO2_ANO = 0.060       # EPA: árvore urbana média, tCO2/ano

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


def limpar_nome_veiculo(nome: str) -> str:
    """Remove duplicações comuns vindas da composição FIPE + ano/combustível."""
    texto = str(nome or "Veículo").strip()
    if not texto:
        return "Veículo"

    texto = re.sub(r"\s+", " ", texto)
    # Ex.: Zero km Zero km Elétrico -> Zero km Elétrico
    texto = re.sub(r"(?i)\bzero\s*km\b(?:\s+\bzero\s*km\b)+", "Zero km", texto)

    # Se o modelo já contém a tecnologia entre parênteses, evita repetir no final.
    tecnologias = ["Elétrico", "Híbrido", "Flex", "Gasolina", "Diesel"]
    for termo in tecnologias:
        termo_re = re.escape(termo)
        if re.search(rf"\({termo_re}\)", texto, flags=re.I):
            texto = re.sub(rf"(?i)(\bZero\s*km\b)\s+{termo_re}\s*$", r"\1", texto)
            texto = re.sub(rf"(?i)\s+{termo_re}\s*$", "", texto)

    # Reforço contra repetições finais simples: Híbrido Híbrido, Flex Flex etc.
    for termo in tecnologias:
        termo_re = re.escape(termo)
        texto = re.sub(rf"(?i)\b{termo_re}\b(?:\s+\b{termo_re}\b)+", termo, texto)

    return re.sub(r"\s+", " ", texto).strip()


def classe_visual_veiculo(veiculo: dict) -> str:
    tipo = str((veiculo or {}).get("tipo", "") or "").strip().lower()
    texto = normalizar(f"{(veiculo or {}).get('combustivel', '')} {(veiculo or {}).get('nome', '')}")
    if tipo == "ve":
        return "plugve-theme-eletrico"
    if tipo == "phev":
        return "plugve-theme-phev"
    if "DIESEL" in texto:
        return "plugve-theme-diesel"
    if "FLEX" in texto or "ETANOL" in texto:
        return "plugve-theme-flex"
    if "GASOL" in texto:
        return "plugve-theme-gasolina"
    if "HIBRID" in texto or "HIBRIDO" in texto or "HIBRIDA" in texto:
        return "plugve-theme-hibrido"
    return "plugve-theme-neutro"


def detectar_phev_texto(modelo: str = "", combustivel: str = "", tipo_form: str = "") -> bool:
    """Detecta híbrido plug-in de forma leve, sem alterar o catálogo FIPE."""
    tipo = normalizar(tipo_form)
    if tipo == "PHEV":
        return True
    texto = normalizar(f"{modelo or ''} {combustivel or ''}")
    padroes = [
        "PHEV", "PLUG IN", "PLUGIN", "HIBRIDO PLUG IN", "HIBRIDA PLUG IN",
        "HYBRID PLUG IN", "DM I", "DMI", "TFSI E", "E HYBRID", "EHIBRID",
        "RECHARGE", "330E", "530E", "545E", "740E", "745E",
        "C 300E", "E 300E", "GLC 300E", "GLE 350E", "225XE",
    ]
    return any(p in texto for p in padroes)

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
CORES_GRAFICOS = ["#168A4A", "#14232C", "#C99A3D", "#6B7280"]


def real_format(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percentual_format(valor):
    return f"{float(valor or 0) * 100:.2f}%".replace(".", ",")


def toneladas_format(valor):
    valor = float(valor or 0)
    if abs(valor) < 0.005:
        return "0,00 tCO₂"
    return f"{valor:,.2f} tCO₂".replace(",", "X").replace(".", ",").replace("X", ".")


def kg_format(valor):
    return f"{float(valor or 0):,.0f} kgCO₂".replace(",", "X").replace(".", ",").replace("X", ".")


def numero_format(valor, casas=1):
    try:
        return f"{float(valor or 0):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0"


def arvores_format(valor):
    valor = max(0.0, float(valor or 0))
    if valor < 1:
        return "menos de 1 árvore"
    return f"{valor:,.0f} árvores".replace(",", ".")


def fator_combustivel_co2_kg_l(texto_combustivel: str = "", padrao: str = "gasolina") -> float:
    texto = normalizar(texto_combustivel)
    if "DIESEL" in texto or padrao == "diesel":
        return FATOR_CO2_DIESEL_S10_KG_L
    if "ETANOL" in texto or "ALCOOL" in texto or padrao == "etanol":
        # Para a comparação principal, o CO2 da queima do etanol é reportado
        # como biogênico separado. Não é ACV e não significa zero absoluto.
        return FATOR_CO2_ETANOL_KG_L
    return FATOR_CO2_GASOLINA_KG_L


def calcular_arvores_equivalentes(co2_t: float, anos: int) -> float:
    anos = max(1, int(anos or 1))
    denom = FATOR_ARVORE_TCO2_ANO * anos
    return max(0.0, float(co2_t or 0.0) / denom) if denom > 0 else 0.0


def fatores_ambientais_resumo() -> dict:
    return {
        "energia": f"{FATOR_CO2_ENERGIA_KG_KWH:.4f}".replace(".", ",") + " kgCO₂/kWh",
        "gasolina": f"{FATOR_CO2_GASOLINA_KG_L:.3f}".replace(".", ",") + " kgCO₂ fóssil/L",
        "etanol": "CO₂ da queima reportado como biogênico separado",
        "etanol_biogenico": f"{FATOR_CO2_ETANOL_BIOGENICO_KG_L:.3f}".replace(".", ",") + " kgCO₂ biogênico/L",
        "diesel": f"{FATOR_CO2_DIESEL_S10_KG_L:.3f}".replace(".", ",") + " kgCO₂ fóssil/L",
        "arvore": f"{FATOR_ARVORE_TCO2_ANO:.3f}".replace(".", ",") + " tCO₂/árvore.ano",
    }




def soma_lista(valores) -> float:
    return sum(float(v or 0.0) for v in (valores or []))


def extrair_componentes_horizonte(v: dict) -> dict:
    """Resume os principais componentes do horizonte para comparação e auditoria."""
    return {
        "uso": soma_lista(v.get("custo_uso_lista")),
        "ipva": soma_lista(v.get("ipva_lista")),
        "seguro": soma_lista(v.get("seguro_lista")),
        "manutencao": soma_lista(v.get("manut_lista")),
        "depreciacao": float(v.get("perda_depreciacao_final", 0) or 0),
        "financiamento_juros": float(v.get("juros_financiamento_horizonte", 0) or 0),
        "operacional": float(v.get("gasto_operacional_final", 0) or 0),
        "revenda": float(v.get("valor_revenda_final", 0) or 0),
        "tco": float(v.get("tco_final", 0) or 0),
        "custo_km": float(v.get("custo_km", 0) or 0),
        "co2_fossil": float(v.get("co2_total_t", 0) or 0),
        "co2_biogenico": float(v.get("co2_biogenico_total_t", 0) or 0),
    }


def formatar_linha_anual(memoria: dict) -> dict:
    return {
        "ano": memoria.get("rotulo") or f"Ano {memoria.get('ano', '')}",
        "uso": real_format(memoria.get("uso", memoria.get("energia_combustivel", 0))),
        "ipva": real_format(memoria.get("ipva", 0)),
        "seguro": real_format(memoria.get("seguro", 0)),
        "manutencao": real_format(memoria.get("manutencao", 0)),
        "financiamento": real_format(memoria.get("financiamento_juros", 0)),
        "operacional_acumulado": real_format(memoria.get("gasto_operacional_acumulado", 0)),
        "depreciacao_acumulada": real_format(memoria.get("depreciacao_acumulada", 0)),
        "revenda": real_format(memoria.get("valor_revenda", 0)),
        "tco": real_format(memoria.get("tco_acumulado", 0)),
        "co2_fossil_acumulado": toneladas_format(memoria.get("co2_fossil_acumulado_t", 0)),
        "co2_biogenico_acumulado": toneladas_format(memoria.get("co2_biogenico_acumulado_t", 0)),
    }


def montar_comparacao_componentes(v1: dict, v2: dict) -> list:
    """Tabela detalhada por componente: Carro 1, Carro 2, diferença e melhor alternativa."""
    c1 = extrair_componentes_horizonte(v1)
    c2 = extrair_componentes_horizonte(v2)

    def melhor_indice(a, b, maior_melhor=False, informativo=False):
        if informativo or abs(float(a or 0) - float(b or 0)) < 1e-9:
            return 0
        if maior_melhor:
            return 1 if a > b else 2
        return 1 if a < b else 2

    def melhor_texto(idx):
        if idx == 1:
            return v1.get("nome_curto", "Carro 1")
        if idx == 2:
            return v2.get("nome_curto", "Carro 2")
        return "Empate" 

    def fmt(valor, tipo):
        if tipo == "moeda":
            return real_format(valor)
        if tipo == "km":
            return f"{real_format(valor)}/km"
        if tipo == "ton":
            return toneladas_format(valor)
        return numero_format(valor, 2)

    def row(rotulo, chave, tipo="moeda", maior_melhor=False, ajuda="", informativo=False):
        a = float(c1.get(chave, 0) or 0)
        b = float(c2.get(chave, 0) or 0)
        idx = melhor_indice(a, b, maior_melhor=maior_melhor, informativo=informativo)
        return {
            "rotulo": rotulo,
            "valor_1": fmt(a, tipo),
            "valor_2": fmt(b, tipo),
            "diferenca": fmt(abs(a - b), tipo),
            "melhor": idx,
            "melhor_texto": "Informativo" if informativo else melhor_texto(idx),
            "ajuda": ajuda,
        }

    linhas = [
        row("Energia/combustível", "uso", ajuda="Custo de recarga, combustível ou combinação configurada no perfil de uso."),
        row("IPVA", "ipva", ajuda="Soma do IPVA projetado no horizonte."),
        row("Seguro", "seguro", ajuda="Seguro projetado a partir da premissa informada/editável."),
        row("Manutenção", "manutencao", ajuda="Manutenção anual informada multiplicada pelo horizonte."),
        row("Depreciação", "depreciacao", ajuda="Perda estimada entre valor inicial e valor futuro de revenda."),
        row("Financiamento/juros", "financiamento_juros", ajuda="Somente juros do financiamento no horizonte, para não somar o principal duas vezes."),
        row("Gasto operacional acumulado", "operacional", ajuda="Uso, manutenção, IPVA, seguro e juros no período."),
        row("Custo total", "tco", ajuda="Gasto operacional acumulado somado à perda por depreciação."),
        row("Valor de revenda", "revenda", maior_melhor=True, ajuda="Maior valor residual é favorável."),
        row("Custo por km", "custo_km", tipo="km", ajuda="Custo total dividido pela quilometragem total."),
        row("Diferença a cada 10.000 km", "custo_km_10000", tipo="moeda", ajuda="Leitura financeira do custo por km multiplicado por 10.000 km."),
        row("CO₂ fóssil operacional", "co2_fossil", tipo="ton", ajuda="Emissões operacionais estimadas; não é ACV completo."),
        row("CO₂ biogênico do etanol", "co2_biogenico", tipo="ton", ajuda="Informado à parte para não chamar etanol de zero absoluto.", informativo=True),
    ]

    # A chave custo_km_10000 é derivada para simplificar a tabela.
    for linha in linhas:
        if linha["rotulo"] == "Diferença a cada 10.000 km":
            a = float(c1.get("custo_km", 0) or 0) * 10000
            b = float(c2.get("custo_km", 0) or 0) * 10000
            idx = melhor_indice(a, b)
            linha.update({
                "valor_1": real_format(a),
                "valor_2": real_format(b),
                "diferenca": real_format(abs(a - b)),
                "melhor": idx,
                "melhor_texto": melhor_texto(idx),
            })
            break
    return linhas


def montar_memoria_anual_formatada(v: dict) -> dict:
    return {
        "nome": v.get("nome", "Veículo"),
        "nome_curto": v.get("nome_curto", "Veículo"),
        "linhas": [formatar_linha_anual(m) for m in (v.get("memoria_anual") or [])],
    }

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


def bool_form(dados_form, campo: str) -> bool:
    valor = str(dados_form.get(campo, "") or "").strip().lower()
    return valor in {"1", "true", "on", "sim", "yes"}


def percentual_0_100_form(dados_form, campo: str, padrao: float = 0.0) -> float:
    return max(0.0, min(100.0, conv(dados_form.get(campo, padrao))))


def custo_uso_combustivel_flex(km_ano: float, etanol_pct: float, preco_gasolina: float, preco_etanol: float, consumo_gasolina: float, consumo_etanol: float) -> float:
    """
    Calcula o custo anual de uso para veículo flex com consumo separado.

    A proporção representa o perfil de uso informado pelo usuário.
    Cada parcela usa seu consumo próprio em km/L.
    """
    km_ano = max(0.0, float(km_ano or 0.0))
    etanol_frac = max(0.0, min(1.0, float(etanol_pct or 0.0) / 100.0))
    gasolina_frac = 1.0 - etanol_frac

    custo = 0.0
    if gasolina_frac > 0 and consumo_gasolina > 0 and preco_gasolina > 0:
        custo += (km_ano * gasolina_frac / consumo_gasolina) * preco_gasolina
    if etanol_frac > 0 and consumo_etanol > 0 and preco_etanol > 0:
        custo += (km_ano * etanol_frac / consumo_etanol) * preco_etanol
    return custo


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
    nome = limpar_nome_veiculo(nome)
    return nome if len(nome) <= limite else nome[: limite - 1].rstrip() + "…"


# 4.3) Layout padrão dos gráficos
def obter_layout_web(titulo: str = ""):
    return {
        "title": {"text": titulo, "x": 0.02, "xanchor": "left", "font": {"size": 18, "color": "#14232C"}},
        "template": "plotly_white",
        "height": 430,
        "autosize": True,
        "font": {"family": "Inter, Arial, sans-serif", "size": 12, "color": "#1F2933"},
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
# Regra: energia e combustível sobem a.a.; IPVA e seguro acompanham o valor de mercado do veículo.
# 4.4) Projeção genérica de um veículo
# Regra V26: energia e combustível sobem a.a.; IPVA e seguro acompanham o valor de mercado do veículo.
def calcular_projecao_veiculo(veiculo, comum):
    nome = limpar_nome_veiculo(veiculo.get("nome", "Veículo"))
    tipo = veiculo.get("tipo", "icev")  # ve, phev ou icev

    preco = max(0.0, float(veiculo.get("preco", 0) or 0))
    consumo = max(0.0, float(veiculo.get("consumo", 0) or 0))
    manut = max(0.0, float(veiculo.get("manut", 0) or 0))
    ipva_inicial = max(0.0, float(veiculo.get("ipva", 0) or 0))
    seguro_inicial = max(0.0, float(veiculo.get("seguro", 0) or 0))
    depreciacao = max(0.0, min(float(veiculo.get("depreciacao", 0) or 0), 0.95))
    financiamento = veiculo.get("financiamento") or {}
    combustivel_descricao = veiculo.get("combustivel", "")

    energia_inicial = max(0.0, float(comum.get("energia", 0) or 0))
    combustivel_inicial = max(0.0, float(comum.get("combustivel", 0) or 0))
    aumento_energia = float(comum.get("aumento_energia", 0) or 0)
    aumento_combustivel = float(comum.get("aumento_combustivel", 0) or 0)
    anos = max(1, int(comum.get("anos", 1) or 1))
    km_ano = max(0, int(comum.get("km_ano", 0) or 0))

    fuel = comum.get("fuel") or {}
    usar_perfil_flex = (
        tipo != "ve"
        and bool(fuel.get("flex_configurado"))
        and str(fuel.get("prefixo") or "") == str(veiculo.get("prefixo") or "")
    )
    flex_etanol_pct = max(0.0, min(100.0, float(fuel.get("percent_etanol", 0) or 0)))
    flex_preco_gasolina = max(0.0, float(fuel.get("preco_gasolina", 0) or 0))
    flex_preco_etanol = max(0.0, float(fuel.get("preco_etanol", 0) or 0))
    flex_consumo_gasolina = max(0.0, float(fuel.get("consumo_gasolina", 0) or 0))
    flex_consumo_etanol = max(0.0, float(fuel.get("consumo_etanol", 0) or 0))

    phev = comum.get("phev") or {}
    usar_perfil_phev = (
        tipo == "phev"
        and bool(phev.get("configurado"))
        and str(phev.get("prefixo") or "") == str(veiculo.get("prefixo") or "")
    )
    phev_eletrico_pct = max(0.0, min(100.0, float(phev.get("percent_eletrico", 100) or 0)))
    phev_combustivel_pct = 100.0 - phev_eletrico_pct
    phev_consumo_eletrico = max(0.0, float(phev.get("consumo_eletrico", 0) or 0))
    phev_consumo_combustivel = max(0.0, float(phev.get("consumo_combustivel", 0) or 0))
    phev_preco_combustivel = max(0.0, float(phev.get("preco_combustivel", 0) or 0))

    taxa_ipva = taxa_relativa(ipva_inicial, preco)
    taxa_seguro = taxa_relativa(seguro_inicial, preco)

    valor_mercado = preco
    gasto_operacional_acumulado = 0.0
    co2_acumulado_kg = 0.0
    co2_biogenico_acumulado_kg = 0.0

    anos_lista = []
    anos_eixo = ["Hoje"]
    tco_lista = []
    tco_lista_s = []
    valor_mercado_lista = [valor_mercado]
    depreciacao_acumulada_lista = [0.0]
    depreciacao_ano_lista = []
    gasto_operacional_lista = []
    custo_uso_lista = []
    ipva_lista = []
    seguro_lista = []
    manut_lista = []
    preco_energia_lista = []
    preco_combustivel_lista = []
    financiamento_juros_lista = []
    co2_anual_kg_lista = []
    co2_acumulado_t_lista = []
    co2_biogenico_t_lista = []
    memoria_anual = []
    co2_componentes_kg = {"energia": 0.0, "gasolina": 0.0, "etanol": 0.0, "etanol_biogenico": 0.0, "diesel": 0.0}
    financiamento_juros_anuais = juros_financiamento_por_ano(financiamento, anos)

    for ano in range(1, anos + 1):
        valor_mercado_inicio_ano = valor_mercado
        energia_ano = energia_inicial * ((1 + aumento_energia) ** (ano - 1))
        combustivel_ano = combustivel_inicial * ((1 + aumento_combustivel) ** (ano - 1))

        ipva_ano = valor_mercado * taxa_ipva
        seguro_ano = valor_mercado * taxa_seguro

        co2_energia_kg = 0.0
        co2_gasolina_kg = 0.0
        co2_etanol_kg = 0.0
        co2_etanol_biogenico_kg = 0.0
        co2_diesel_kg = 0.0

        if tipo == "ve":
            custo_uso = km_ano * consumo * energia_ano
            co2_energia_kg = km_ano * consumo * FATOR_CO2_ENERGIA_KG_KWH if consumo > 0 else 0.0
        elif tipo == "phev":
            if usar_perfil_phev:
                frac_eletrico = phev_eletrico_pct / 100.0
                frac_combustivel = phev_combustivel_pct / 100.0
                consumo_eletrico_uso = phev_consumo_eletrico or consumo
                custo_eletrico = km_ano * frac_eletrico * consumo_eletrico_uso * energia_ano if frac_eletrico > 0 and consumo_eletrico_uso > 0 else 0.0
                co2_energia_kg = km_ano * frac_eletrico * consumo_eletrico_uso * FATOR_CO2_ENERGIA_KG_KWH if frac_eletrico > 0 and consumo_eletrico_uso > 0 else 0.0

                preco_combustivel_ano = (phev_preco_combustivel or combustivel_inicial) * ((1 + aumento_combustivel) ** (ano - 1))
                litros_combustivel = (km_ano * frac_combustivel / phev_consumo_combustivel) if frac_combustivel > 0 and phev_consumo_combustivel > 0 else 0.0
                custo_combustivel = litros_combustivel * preco_combustivel_ano if litros_combustivel > 0 and preco_combustivel_ano > 0 else 0.0
                # Primeira versão: parcela a combustível do PHEV usa gasolina como premissa padrão.
                co2_gasolina_kg = litros_combustivel * FATOR_CO2_GASOLINA_KG_L
                custo_uso = custo_eletrico + custo_combustivel
            else:
                custo_uso = km_ano * consumo * energia_ano
                co2_energia_kg = km_ano * consumo * FATOR_CO2_ENERGIA_KG_KWH if consumo > 0 else 0.0
        elif usar_perfil_flex:
            fator_reajuste = (1 + aumento_combustivel) ** (ano - 1)
            custo_uso = custo_uso_combustivel_flex(
                km_ano=km_ano,
                etanol_pct=flex_etanol_pct,
                preco_gasolina=flex_preco_gasolina * fator_reajuste,
                preco_etanol=flex_preco_etanol * fator_reajuste,
                consumo_gasolina=flex_consumo_gasolina,
                consumo_etanol=flex_consumo_etanol,
            )
            etanol_frac = max(0.0, min(1.0, flex_etanol_pct / 100.0))
            gasolina_frac = 1.0 - etanol_frac
            litros_gasolina = (km_ano * gasolina_frac / flex_consumo_gasolina) if gasolina_frac > 0 and flex_consumo_gasolina > 0 else 0.0
            litros_etanol = (km_ano * etanol_frac / flex_consumo_etanol) if etanol_frac > 0 and flex_consumo_etanol > 0 else 0.0
            co2_gasolina_kg = litros_gasolina * FATOR_CO2_GASOLINA_KG_L
            co2_etanol_kg = litros_etanol * FATOR_CO2_ETANOL_KG_L
            co2_etanol_biogenico_kg = litros_etanol * FATOR_CO2_ETANOL_BIOGENICO_KG_L
        else:
            litros_combustivel = (km_ano / consumo) if consumo > 0 else 0.0
            custo_uso = litros_combustivel * combustivel_ano if litros_combustivel > 0 else 0.0
            fator_co2 = fator_combustivel_co2_kg_l(combustivel_descricao)
            if fator_co2 == FATOR_CO2_DIESEL_S10_KG_L:
                co2_diesel_kg = litros_combustivel * fator_co2
            elif fator_co2 == FATOR_CO2_ETANOL_KG_L:
                co2_etanol_kg = litros_combustivel * fator_co2
                co2_etanol_biogenico_kg = litros_combustivel * FATOR_CO2_ETANOL_BIOGENICO_KG_L
            else:
                co2_gasolina_kg = litros_combustivel * fator_co2

        # Indicador principal: CO2 fóssil operacional. O CO2 da queima do etanol
        # é mostrado separadamente como biogênico, sem afirmar zero absoluto.
        co2_anual_kg = co2_energia_kg + co2_gasolina_kg + co2_etanol_kg + co2_diesel_kg
        co2_acumulado_kg += co2_anual_kg
        co2_biogenico_acumulado_kg += co2_etanol_biogenico_kg
        co2_componentes_kg["energia"] += co2_energia_kg
        co2_componentes_kg["gasolina"] += co2_gasolina_kg
        co2_componentes_kg["etanol"] += co2_etanol_kg
        co2_componentes_kg["etanol_biogenico"] += co2_etanol_biogenico_kg
        co2_componentes_kg["diesel"] += co2_diesel_kg

        juros_financiamento_ano = financiamento_juros_anuais[ano - 1] if ano - 1 < len(financiamento_juros_anuais) else 0.0
        custo_anual = custo_uso + manut + ipva_ano + seguro_ano + juros_financiamento_ano
        gasto_operacional_acumulado += custo_anual

        valor_mercado = valor_mercado * (1 - depreciacao)
        depreciacao_ano = max(0.0, valor_mercado_inicio_ano - valor_mercado)
        perda_depreciacao = max(0.0, preco - valor_mercado)
        tco_com_depreciacao = gasto_operacional_acumulado + perda_depreciacao

        anos_lista.append(f"Ano {ano}")
        anos_eixo.append(f"Ano {ano}")
        tco_lista.append(tco_com_depreciacao)
        tco_lista_s.append(gasto_operacional_acumulado)
        valor_mercado_lista.append(valor_mercado)
        depreciacao_acumulada_lista.append(perda_depreciacao)
        depreciacao_ano_lista.append(depreciacao_ano)
        gasto_operacional_lista.append(gasto_operacional_acumulado)
        custo_uso_lista.append(custo_uso)
        ipva_lista.append(ipva_ano)
        seguro_lista.append(seguro_ano)
        manut_lista.append(manut)
        preco_energia_lista.append(energia_ano)
        preco_combustivel_lista.append(combustivel_ano)
        financiamento_juros_lista.append(juros_financiamento_ano)
        co2_anual_kg_lista.append(co2_anual_kg)
        co2_acumulado_t_lista.append(co2_acumulado_kg / 1000.0)
        co2_biogenico_t_lista.append(co2_biogenico_acumulado_kg / 1000.0)
        memoria_anual.append({
            "ano": ano,
            "rotulo": f"Ano {ano}",
            "km_ano": km_ano,
            "uso": custo_uso,
            "energia_combustivel": custo_uso,
            "ipva": ipva_ano,
            "seguro": seguro_ano,
            "manutencao": manut,
            "financiamento_juros": juros_financiamento_ano,
            "gasto_operacional_ano": custo_anual,
            "gasto_operacional_acumulado": gasto_operacional_acumulado,
            "depreciacao_ano": depreciacao_ano,
            "depreciacao_acumulada": perda_depreciacao,
            "valor_revenda": valor_mercado,
            "tco_acumulado": tco_com_depreciacao,
            "preco_energia": energia_ano,
            "preco_combustivel": combustivel_ano,
            "co2_fossil_t": co2_anual_kg / 1000.0,
            "co2_fossil_acumulado_t": co2_acumulado_kg / 1000.0,
            "co2_biogenico_t": co2_etanol_biogenico_kg / 1000.0,
            "co2_biogenico_acumulado_t": co2_biogenico_acumulado_kg / 1000.0,
            "co2_energia_kg": co2_energia_kg,
            "co2_gasolina_kg": co2_gasolina_kg,
            "co2_etanol_fossil_kg": co2_etanol_kg,
            "co2_etanol_biogenico_kg": co2_etanol_biogenico_kg,
            "co2_diesel_kg": co2_diesel_kg,
        })

    total_km = anos * km_ano if anos > 0 and km_ano > 0 else 1
    valor_revenda_final = valor_mercado_lista[-1]
    perda_depreciacao_final = max(0.0, preco - valor_revenda_final)
    gasto_operacional_final = gasto_operacional_lista[-1] if gasto_operacional_lista else 0.0
    tco_final = tco_lista[-1] if tco_lista else 0.0
    tco_final_s = tco_lista_s[-1] if tco_lista_s else 0.0
    juros_financiamento_horizonte = sum(financiamento_juros_lista)
    co2_total_t = co2_acumulado_kg / 1000.0
    co2_biogenico_total_t = co2_biogenico_acumulado_kg / 1000.0
    co2_anual_medio_t = co2_total_t / anos if anos > 0 else 0.0
    co2_biogenico_anual_medio_t = co2_biogenico_total_t / anos if anos > 0 else 0.0
    co2_por_km_kg = co2_acumulado_kg / total_km if total_km > 0 else 0.0
    componentes_tco = {
        "uso": sum(custo_uso_lista),
        "energia_combustivel": sum(custo_uso_lista),
        "ipva": sum(ipva_lista),
        "seguro": sum(seguro_lista),
        "manutencao": sum(manut_lista),
        "financiamento_juros": juros_financiamento_horizonte,
        "depreciacao": perda_depreciacao_final,
        "operacional": gasto_operacional_final,
        "gasto_operacional": gasto_operacional_final,
        "revenda": valor_revenda_final,
        "valor_revenda": valor_revenda_final,
        "tco": tco_final,
        "tco_total": tco_final,
        "custo_km": tco_final / total_km,
        "co2_fossil": co2_total_t,
        "co2_total_t": co2_total_t,
        "co2_biogenico": co2_biogenico_total_t,
        "co2_etanol_biogenico_t": co2_biogenico_total_t,
    }

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
        "anos_horizonte": anos,
        "km_ano": km_ano,
        "total_km": total_km,
        "tco_final": tco_final,
        "tco_final_s": tco_final_s,
        "custo_km": tco_final / total_km,
        "custo_km_s": tco_final_s / total_km,
        "tco_lista": tco_lista,
        "tco_lista_s": tco_lista_s,
        "valor_mercado_lista": valor_mercado_lista,
        "depreciacao_acumulada_lista": depreciacao_acumulada_lista,
        "depreciacao_ano_lista": depreciacao_ano_lista,
        "gasto_operacional_lista": gasto_operacional_lista,
        "custo_uso_lista": custo_uso_lista,
        "ipva_lista": ipva_lista,
        "seguro_lista": seguro_lista,
        "manut_lista": manut_lista,
        "preco_energia_lista": preco_energia_lista,
        "preco_combustivel_lista": preco_combustivel_lista,
        "financiamento_juros_lista": financiamento_juros_lista,
        "memoria_anual": memoria_anual,
        "memoria_anual_formatada": [formatar_linha_anual(m) for m in memoria_anual],
        "componentes_tco": componentes_tco,
        "componentes_totais": componentes_tco,
        "co2_anual_kg_lista": co2_anual_kg_lista,
        "co2_acumulado_t_lista": co2_acumulado_t_lista,
        "co2_biogenico_t_lista": co2_biogenico_t_lista,
        "co2_total_t": co2_total_t,
        "co2_biogenico_total_t": co2_biogenico_total_t,
        "co2_anual_medio_t": co2_anual_medio_t,
        "co2_biogenico_anual_medio_t": co2_biogenico_anual_medio_t,
        "co2_por_km_kg": co2_por_km_kg,
        "co2_componentes_t": {k: v / 1000.0 for k, v in co2_componentes_kg.items() if k != "etanol_biogenico"},
        "co2_biogenico_componentes_t": {"etanol": co2_componentes_kg.get("etanol_biogenico", 0.0) / 1000.0},
    }

# 4.5) Gera gráficos de comparação entre 2 veículos
def gerar_graficos_dupla(v1, v2):
    cor1, cor2 = CORES_GRAFICOS[0], CORES_GRAFICOS[1]

    fig_tco = go.Figure()
    fig_tco.add_trace(go.Scatter(
        x=v1["anos_lista"], y=v1["tco_lista"], mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v1["nome"]] * len(v1["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>Custo total: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_tco.add_trace(go.Scatter(
        x=v2["anos_lista"], y=v2["tco_lista"], mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v2["nome"]] * len(v2["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>Custo total: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_tco.update_layout(**obter_layout_web("Custo total acumulado ano a ano"), yaxis_title="Custo acumulado (R$)")

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
    fig_gastos.update_layout(**obter_layout_web("Gastos operacionais acumulados"), yaxis_title="Gasto acumulado (R$)")

    pares_componentes = [
        ("Energia/comb.", "energia_combustivel"),
        ("IPVA", "ipva"),
        ("Seguro", "seguro"),
        ("Manutenção", "manutencao"),
        ("Depreciação", "depreciacao"),
        ("Juros", "financiamento_juros"),
    ]
    comp1 = v1.get("componentes_totais") or v1.get("componentes_tco") or {}
    comp2 = v2.get("componentes_totais") or v2.get("componentes_tco") or {}
    pares_componentes = [
        (label, chave) for label, chave in pares_componentes
        if abs(float(comp1.get(chave, 0.0) or 0.0)) > 1e-9 or abs(float(comp2.get(chave, 0.0) or 0.0)) > 1e-9
    ]
    labels_componentes = [label for label, _ in pares_componentes]
    chaves_componentes = [chave for _, chave in pares_componentes]

    fig_componentes = go.Figure()
    if labels_componentes:
        fig_componentes.add_trace(go.Bar(
            x=labels_componentes,
            y=[comp1.get(k, 0.0) for k in chaves_componentes],
            name=v1["nome_curto"],
            marker_color=cor1,
            hovertemplate="%{x}<br>" + v1["nome_curto"] + ": R$ %{y:,.2f}<extra></extra>",
        ))
        fig_componentes.add_trace(go.Bar(
            x=labels_componentes,
            y=[comp2.get(k, 0.0) for k in chaves_componentes],
            name=v2["nome_curto"],
            marker_color=cor2,
            hovertemplate="%{x}<br>" + v2["nome_curto"] + ": R$ %{y:,.2f}<extra></extra>",
        ))
        fig_componentes.update_layout(
            **obter_layout_web("Componentes do custo total no horizonte"),
            yaxis_title="Valor acumulado (R$)",
            barmode="group",
        )

    def grafico_componentes_anuais(v, titulo):
        fig = go.Figure()
        componentes = [
            ("Energia/comb.", v.get("custo_uso_lista", [])),
            ("IPVA", v.get("ipva_lista", [])),
            ("Seguro", v.get("seguro_lista", [])),
            ("Manutenção", v.get("manut_lista", [])),
            ("Juros", v.get("financiamento_juros_lista", [])),
            ("Depreciação", v.get("depreciacao_ano_lista", [])),
        ]
        componentes = [
            (nome_comp, valores or []) for nome_comp, valores in componentes
            if any(abs(float(valor or 0)) > 1e-9 for valor in (valores or []))
        ]
        if not componentes:
            return ""
        for nome_comp, valores in componentes:
            fig.add_trace(go.Bar(
                x=v.get("anos_lista", []),
                y=valores,
                name=nome_comp,
                hovertemplate=nome_comp + "<br>%{x}: R$ %{y:,.2f}<extra></extra>",
            ))
        layout_componentes_anuais = obter_layout_web(titulo)
        layout_componentes_anuais.update({
            "height": 500,
            "yaxis_title": "Custo anual (R$)",
            "barmode": "stack",
            "margin": {"l": 70, "r": 30, "t": 78, "b": 118},
            "legend": {"orientation": "h", "yanchor": "top", "y": -0.22, "xanchor": "left", "x": 0},
        })
        fig.update_xaxes(tickangle=0)
        fig.update_layout(**layout_componentes_anuais)
        return html_grafico(fig)

    fig_revenda = go.Figure()
    fig_revenda.add_trace(go.Scatter(
        x=v1["anos_eixo"], y=v1["valor_mercado_lista"], mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        fill="tozeroy", fillcolor="rgba(22, 138, 74, 0.10)",
        customdata=[v1["nome"]] * len(v1["anos_eixo"]),
        hovertemplate="%{customdata}<br>%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_revenda.add_trace(go.Scatter(
        x=v2["anos_eixo"], y=v2["valor_mercado_lista"], mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        fill="tozeroy", fillcolor="rgba(20, 35, 44, 0.08)",
        customdata=[v2["nome"]] * len(v2["anos_eixo"]),
        hovertemplate="%{customdata}<br>%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_revenda.update_layout(**obter_layout_web("Valor estimado de revenda ano a ano"), yaxis_title="Valor de mercado (R$)")

    def grafico_depreciacao_individual(v, cor):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=v["anos_eixo"], y=v["valor_mercado_lista"], mode="lines+markers", name="Valor de revenda",
            line={"color": cor, "width": 3, "shape": "spline"}, marker={"size": 8},
            fill="tozeroy", fillcolor="rgba(22, 138, 74, 0.10)",
            hovertemplate="%{x}<br>Valor estimado: R$ %{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(**obter_layout_web(f"Depreciação — {nome_curto(v['nome'], 42)}"), yaxis_title="Valor de mercado (R$)")
        return html_grafico(fig)

    fig_co2 = go.Figure()
    fig_co2.add_trace(go.Scatter(
        x=v1["anos_lista"], y=v1.get("co2_acumulado_t_lista", []), mode="lines+markers", name=v1["nome_curto"],
        line={"color": cor1, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v1["nome"]] * len(v1["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>CO₂ fóssil operacional: %{y:,.2f} t<extra></extra>",
    ))
    fig_co2.add_trace(go.Scatter(
        x=v2["anos_lista"], y=v2.get("co2_acumulado_t_lista", []), mode="lines+markers", name=v2["nome_curto"],
        line={"color": cor2, "width": 3, "shape": "spline"}, marker={"size": 8},
        customdata=[v2["nome"]] * len(v2["anos_lista"]),
        hovertemplate="%{customdata}<br>%{x}<br>CO₂ fóssil operacional: %{y:,.2f} t<extra></extra>",
    ))
    fig_co2.update_layout(**obter_layout_web("CO₂ fóssil operacional acumulado"), yaxis_title="Emissões acumuladas (tCO₂)")

    diferenca_tco = [float(a or 0) - float(b or 0) for a, b in zip(v1.get("tco_lista", []), v2.get("tco_lista", []))]
    fig_diferenca = go.Figure()
    fig_diferenca.add_trace(go.Scatter(
        x=v1.get("anos_lista", []), y=diferenca_tco, mode="lines+markers",
        name=f"{v1['nome_curto']} - {v2['nome_curto']}",
        line={"color": CORES_GRAFICOS[2], "width": 3, "shape": "spline"}, marker={"size": 8},
        hovertemplate="%{x}<br>Diferença de custo total: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_diferenca.add_hline(y=0, line_width=1, line_dash="dash", line_color="#94a3b8")
    fig_diferenca.update_layout(**obter_layout_web("Diferença acumulada ano a ano"), yaxis_title="Diferença de custo total (R$)")

    return {
        "grafico": html_grafico(fig_tco),
        "grafico_sem_depreciacao": html_grafico(fig_gastos),
        "grafico_componentes": html_grafico(fig_componentes) if labels_componentes else "",
        "grafico_componentes_anuais_v1": grafico_componentes_anuais(v1, f"Componentes anuais — {nome_curto(v1.get('nome', 'Veículo 1'), 44)}"),
        "grafico_componentes_anuais_v2": grafico_componentes_anuais(v2, f"Componentes anuais — {nome_curto(v2.get('nome', 'Veículo 2'), 44)}"),
        "grafico_custo_km": "",
        "grafico_revenda_comparativo": html_grafico(fig_revenda),
        "grafico_depreciacao_v1": grafico_depreciacao_individual(v1, cor1),
        "grafico_depreciacao_v2": grafico_depreciacao_individual(v2, cor2),
        "grafico_ambiental": html_grafico(fig_co2),
        "grafico_diferenca_anual": html_grafico(fig_diferenca),
    }


# 4.6) Empacota 1 comparação pronta para renderização
def montar_bloco_resultado(titulo, v1, v2):
    graficos = gerar_graficos_dupla(v1, v2)
    vencedor = v1 if v1["tco_final"] <= v2["tco_final"] else v2
    outro = v2 if vencedor is v1 else v1
    economia = max(0.0, outro["tco_final"] - vencedor["tco_final"])
    economia_percentual = economia / outro["tco_final"] if outro["tco_final"] > 0 else 0.0
    anos_horizonte = max(1, int(v1.get("anos_horizonte", v2.get("anos_horizonte", 1)) or 1))

    def resumo(v):
        financiamento = v.get("financiamento") or {}
        return {
            "nome": v["nome"],
            "nome_curto": v["nome_curto"],
            "tipo": v.get("tipo", ""),
            "combustivel": v.get("combustivel", ""),
            "tema_classe": classe_visual_veiculo(v),
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
            "financiamento_ativo": bool(financiamento.get("ativo")),
            "valor_financiado": real_format(financiamento.get("principal", 0)),
            "entrada_financiamento": real_format(financiamento.get("entrada", 0)),
            "parcela_financiamento": real_format(financiamento.get("parcela", 0)),
            "prazo_financiamento": int(financiamento.get("meses", 0) or 0),
            "taxa_financiamento": percentual_format(financiamento.get("taxa_mensal", 0)),
            "total_financiamento": real_format(financiamento.get("total_pago", 0)),
            "juros_financiamento_total": real_format(financiamento.get("juros_total", 0)),
            "juros_financiamento_horizonte": real_format(v.get("juros_financiamento_horizonte", 0)),
            "co2_total": toneladas_format(v.get("co2_total_t", 0)),
            "co2_biogenico": toneladas_format(v.get("co2_biogenico_total_t", 0)),
            "co2_anual": toneladas_format(v.get("co2_anual_medio_t", 0)),
            "co2_por_km": f"{numero_format(v.get('co2_por_km_kg', 0), 3)} kgCO₂/km",
            "arvores_compensacao": arvores_format(calcular_arvores_equivalentes(v.get("co2_total_t", 0), v.get("anos_horizonte", 1))),
        }

    def melhor_indice(valor1: float, valor2: float, maior_melhor: bool = False) -> int:
        valor1 = float(valor1 or 0)
        valor2 = float(valor2 or 0)
        if abs(valor1 - valor2) < 1e-9:
            return 0
        if maior_melhor:
            return 1 if valor1 > valor2 else 2
        return 1 if valor1 < valor2 else 2

    def melhor_texto(indice: int) -> str:
        return "Empate" if indice == 0 else f"Carro {indice}"

    def linha_comparativa(rotulo: str, valor1: float, valor2: float, maior_melhor: bool = False, ajuda: str = "") -> dict:
        return {
            "rotulo": rotulo,
            "valor_1": real_format(valor1),
            "valor_2": real_format(valor2),
            "melhor": melhor_indice(valor1, valor2, maior_melhor=maior_melhor),
            "ajuda": ajuda,
        }

    def linha_componente(rotulo: str, valor1: float, valor2: float, tipo: str = "moeda", maior_melhor: bool = False, ajuda: str = "") -> dict:
        valor1_num = float(valor1 or 0)
        valor2_num = float(valor2 or 0)
        melhor = melhor_indice(valor1_num, valor2_num, maior_melhor=maior_melhor)
        diferenca = abs(valor1_num - valor2_num)
        if tipo == "co2":
            fmt = toneladas_format
            diff_fmt = toneladas_format(diferenca)
        elif tipo == "km":
            fmt = lambda x: f"{real_format(x)}/km"
            diff_fmt = f"{real_format(diferenca)}/km"
        else:
            fmt = real_format
            diff_fmt = real_format(diferenca)
        return {
            "rotulo": rotulo,
            "valor_1": fmt(valor1_num),
            "valor_2": fmt(valor2_num),
            "diferenca": diff_fmt,
            "melhor": melhor,
            "melhor_texto": melhor_texto(melhor),
            "ajuda": ajuda,
            "raw_1": valor1_num,
            "raw_2": valor2_num,
        }

    resumo_v1 = resumo(v1)
    resumo_v2 = resumo(v2)
    comp1 = v1.get("componentes_totais") or v1.get("componentes_tco") or extrair_componentes_horizonte(v1)
    comp2 = v2.get("componentes_totais") or v2.get("componentes_tco") or extrair_componentes_horizonte(v2)

    comparativo_indicadores = [
        linha_comparativa("Custo total no horizonte", v1["tco_final"], v2["tco_final"], ajuda="Custo total de propriedade estimado no período."),
        linha_comparativa("Custo total por km", v1["custo_km"], v2["custo_km"], ajuda="Custo total dividido pela quilometragem total simulada."),
        linha_comparativa("Gasto operacional acumulado", v1["gasto_operacional_final"], v2["gasto_operacional_final"], ajuda="Energia ou combustível, manutenção, IPVA, seguro e juros no horizonte."),
        {"rotulo": "CO₂ fóssil operacional acumulado", "valor_1": toneladas_format(v1.get("co2_total_t", 0)), "valor_2": toneladas_format(v2.get("co2_total_t", 0)), "melhor": melhor_indice(v1.get("co2_total_t", 0), v2.get("co2_total_t", 0)), "ajuda": "Estimativa operacional; etanol biogênico é reportado à parte."},
        linha_comparativa("Perda por depreciação", v1["perda_depreciacao_final"], v2["perda_depreciacao_final"], ajuda="Diferença entre o valor inicial e o valor estimado de revenda."),
        linha_comparativa("Valor estimado de revenda", v1["valor_revenda_final"], v2["valor_revenda_final"], maior_melhor=True, ajuda="Maior valor é favorável."),
    ]

    if resumo_v1["financiamento_ativo"] or resumo_v2["financiamento_ativo"]:
        comparativo_indicadores.append(linha_comparativa("Juros pagos no horizonte", v1.get("juros_financiamento_horizonte", 0), v2.get("juros_financiamento_horizonte", 0), ajuda="Somente os juros que incidem dentro do período analisado."))

    comparativo_componentes = [
        linha_componente("Energia/combustível", comp1.get("energia_combustivel", comp1.get("uso", 0)), comp2.get("energia_combustivel", comp2.get("uso", 0)), ajuda="Energia elétrica ou combustível consumido no horizonte."),
        linha_componente("IPVA", comp1.get("ipva", 0), comp2.get("ipva", 0)),
        linha_componente("Seguro", comp1.get("seguro", 0), comp2.get("seguro", 0)),
        linha_componente("Manutenção", comp1.get("manutencao", 0), comp2.get("manutencao", 0)),
        linha_componente("Depreciação", comp1.get("depreciacao", 0), comp2.get("depreciacao", 0)),
        linha_componente("Financiamento/juros", comp1.get("financiamento_juros", 0), comp2.get("financiamento_juros", 0), ajuda="Principal não é somado novamente; entra o custo financeiro."),
        linha_componente("Gasto operacional acumulado", comp1.get("gasto_operacional", comp1.get("operacional", 0)), comp2.get("gasto_operacional", comp2.get("operacional", 0))),
        linha_componente("Valor de revenda", comp1.get("valor_revenda", comp1.get("revenda", 0)), comp2.get("valor_revenda", comp2.get("revenda", 0)), maior_melhor=True),
        linha_componente("Custo total", comp1.get("tco", comp1.get("tco_total", 0)), comp2.get("tco", comp2.get("tco_total", 0))),
        linha_componente("Custo por km", v1.get("custo_km", 0), v2.get("custo_km", 0), tipo="km"),
        linha_componente("CO₂ fóssil operacional", v1.get("co2_total_t", 0), v2.get("co2_total_t", 0), tipo="co2", ajuda="Não inclui fabricação, bateria, descarte nem CO₂ biogênico do etanol."),
        linha_componente("CO₂ biogênico do etanol", v1.get("co2_biogenico_total_t", 0), v2.get("co2_biogenico_total_t", 0), tipo="co2", ajuda="Reportado separadamente; não entra no indicador fóssil principal."),
    ]
    # Evita poluir o relatório com componentes inexistentes ou não aplicáveis
    # (ex.: financiamento/juros igual a zero para os dois veículos).
    comparativo_componentes = [
        linha for linha in comparativo_componentes
        if abs(float(linha.get("raw_1", 0) or 0)) > 1e-9 or abs(float(linha.get("raw_2", 0) or 0)) > 1e-9
    ]

    vencedor_custo_km = v1 if v1["custo_km"] <= v2["custo_km"] else v2
    outro_custo_km = v2 if vencedor_custo_km is v1 else v1
    diferenca_custo_km = max(0.0, outro_custo_km["custo_km"] - vencedor_custo_km["custo_km"])
    total_km = max(float(v1.get("total_km", 0) or 0), float(v2.get("total_km", 0) or 0))
    total_km_formatado = f"{int(round(total_km)):,}".replace(",", ".")

    custo_km_comparacao = {
        "vencedor_nome": vencedor_custo_km["nome"],
        "veiculo_1_nome": v1["nome_curto"],
        "veiculo_2_nome": v2["nome_curto"],
        "veiculo_1_valor": real_format(v1["custo_km"]),
        "veiculo_2_valor": real_format(v2["custo_km"]),
        "melhor": 1 if vencedor_custo_km is v1 else 2,
        "diferenca": real_format(diferenca_custo_km),
        "impacto_10000": real_format(diferenca_custo_km * 10000),
        "impacto_horizonte": real_format(diferenca_custo_km * total_km),
        "quilometragem_horizonte": total_km_formatado,
    }

    diferenca_tco_abs = abs(float(v1.get("tco_final", 0) or 0) - float(v2.get("tco_final", 0) or 0))
    base_maior_tco = max(float(v1.get("tco_final", 0) or 0), float(v2.get("tco_final", 0) or 0))
    comparativo_componentes_resumo = {
        "diferenca_horizonte": real_format(diferenca_tco_abs),
        "diferenca_percentual": percentual_format(diferenca_tco_abs / base_maior_tco if base_maior_tco > 0 else 0),
        "diferenca_por_ano": real_format(diferenca_tco_abs / anos_horizonte),
        "diferenca_10000km": real_format(diferenca_custo_km * 10000),
    }

    co2_1 = float(v1.get("co2_total_t", 0) or 0)
    co2_2 = float(v2.get("co2_total_t", 0) or 0)
    menor_co2 = v1 if co2_1 <= co2_2 else v2
    maior_co2 = v2 if menor_co2 is v1 else v1
    co2_evitado_t = max(0.0, float(maior_co2.get("co2_total_t", 0) or 0) - float(menor_co2.get("co2_total_t", 0) or 0))
    impacto_ambiental = {
        "menor_nome": menor_co2["nome"],
        "maior_nome": maior_co2["nome"],
        "veiculo_1_nome": v1["nome_curto"],
        "veiculo_2_nome": v2["nome_curto"],
        "veiculo_1_total": toneladas_format(co2_1),
        "veiculo_2_total": toneladas_format(co2_2),
        "veiculo_1_biogenico": toneladas_format(v1.get("co2_biogenico_total_t", 0)),
        "veiculo_2_biogenico": toneladas_format(v2.get("co2_biogenico_total_t", 0)),
        "veiculo_1_anual": toneladas_format(v1.get("co2_anual_medio_t", 0)),
        "veiculo_2_anual": toneladas_format(v2.get("co2_anual_medio_t", 0)),
        "veiculo_1_por_km": f"{numero_format(v1.get('co2_por_km_kg', 0), 3)} kgCO₂/km",
        "veiculo_2_por_km": f"{numero_format(v2.get('co2_por_km_kg', 0), 3)} kgCO₂/km",
        "co2_evitado": toneladas_format(co2_evitado_t),
        "arvores_equivalentes": arvores_format(calcular_arvores_equivalentes(co2_evitado_t, anos_horizonte)),
        "anos": anos_horizonte,
        "fatores": fatores_ambientais_resumo(),
        "componentes_1": {k: toneladas_format(v) for k, v in (v1.get("co2_componentes_t") or {}).items()},
        "componentes_2": {k: toneladas_format(v) for k, v in (v2.get("co2_componentes_t") or {}).items()},
        "componentes_biogenicos_1": {"etanol": toneladas_format((v1.get("co2_biogenico_componentes_t") or {}).get("etanol", 0))},
        "componentes_biogenicos_2": {"etanol": toneladas_format((v2.get("co2_biogenico_componentes_t") or {}).get("etanol", 0))},
    }

    memoria_anual_comparativa = []
    mem1 = v1.get("memoria_anual") or []
    mem2 = v2.get("memoria_anual") or []
    for idx in range(min(len(mem1), len(mem2))):
        m1, m2 = mem1[idx], mem2[idx]
        memoria_anual_comparativa.append({
            "ano": m1.get("rotulo", f"Ano {idx + 1}"),
            "v1_uso": real_format(m1.get("energia_combustivel", 0)),
            "v2_uso": real_format(m2.get("energia_combustivel", 0)),
            "v1_operacional": real_format(m1.get("gasto_operacional_acumulado", 0)),
            "v2_operacional": real_format(m2.get("gasto_operacional_acumulado", 0)),
            "v1_depreciacao": real_format(m1.get("depreciacao_acumulada", 0)),
            "v2_depreciacao": real_format(m2.get("depreciacao_acumulada", 0)),
            "v1_tco": real_format(m1.get("tco_acumulado", 0)),
            "v2_tco": real_format(m2.get("tco_acumulado", 0)),
            "diferenca_tco": real_format(abs(float(m1.get("tco_acumulado", 0) or 0) - float(m2.get("tco_acumulado", 0) or 0))),
            "v1_revenda": real_format(m1.get("valor_revenda", 0)),
            "v2_revenda": real_format(m2.get("valor_revenda", 0)),
            "v1_co2": toneladas_format(m1.get("co2_fossil_acumulado_t", 0)),
            "v2_co2": toneladas_format(m2.get("co2_fossil_acumulado_t", 0)),
        })

    auditoria_veiculos = [
        {"nome": v1["nome"], "tipo": v1.get("tipo", ""), "componentes": comp1, "memoria": [formatar_linha_anual(m) for m in mem1]},
        {"nome": v2["nome"], "tipo": v2.get("tipo", ""), "componentes": comp2, "memoria": [formatar_linha_anual(m) for m in mem2]},
    ]

    return {
        "titulo": titulo,
        "vencedor_nome": vencedor["nome"],
        "vencedor_indice": 1 if vencedor is v1 else 2,
        "economia": real_format(economia),
        "economia_percentual": percentual_format(economia_percentual),
        "detalhes": [resumo_v1, resumo_v2],
        "comparativo_indicadores": comparativo_indicadores,
        "comparativo_componentes": comparativo_componentes,
        "comparacao_componentes": comparativo_componentes,
        "comparativo_componentes_resumo": comparativo_componentes_resumo,
        "memoria_anual_comparativa": memoria_anual_comparativa,
        "memoria_anual": [montar_memoria_anual_formatada(v1), montar_memoria_anual_formatada(v2)],
        "auditoria_veiculos": auditoria_veiculos,
        "custo_km_comparacao": custo_km_comparacao,
        "impacto_ambiental": impacto_ambiental,
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
        "grafico_componentes": graficos.get("grafico_componentes", ""),
        "grafico_componentes_anuais_v1": graficos.get("grafico_componentes_anuais_v1", ""),
        "grafico_componentes_anuais_v2": graficos.get("grafico_componentes_anuais_v2", ""),
        "grafico_custo_km": "",
        "grafico_revenda_comparativo": graficos["grafico_revenda_comparativo"],
        "grafico_depreciacao_v1": graficos["grafico_depreciacao_v1"],
        "grafico_depreciacao_v2": graficos["grafico_depreciacao_v2"],
        "grafico_ambiental": graficos.get("grafico_ambiental", ""),
        "grafico_diferenca_anual": graficos.get("grafico_diferenca_anual", ""),
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
        "fuel": {
            "tipo": str(dados_form.get("fuel_tipo_detectado", "") or "").strip().lower(),
            "flex_configurado": bool_form(dados_form, "fuel_flex_configurado"),
            "prefixo": str(dados_form.get("fuel_prefixo_configurado", "") or "").strip(),
            "percent_etanol": percentual_0_100_form(dados_form, "fuel_percent_etanol", 0),
            "preco_gasolina": conv(dados_form.get("fuel_preco_gasolina", 0)),
            "preco_etanol": conv(dados_form.get("fuel_preco_etanol", 0)),
            "preco_diesel_s10": conv(dados_form.get("fuel_preco_diesel_s10", 0)),
            "consumo_gasolina": conv(dados_form.get("fuel_consumo_gasolina", 0)),
            "consumo_etanol": conv(dados_form.get("fuel_consumo_etanol", 0)),
        },
        "phev": {
            "configurado": bool_form(dados_form, "phev_configurado"),
            "prefixo": str(dados_form.get("phev_prefixo_configurado", "") or "").strip(),
            "percent_eletrico": percentual_0_100_form(dados_form, "phev_percent_eletrico", 100),
            "preco_combustivel": conv(dados_form.get("phev_preco_combustivel", 0)),
            "consumo_eletrico": conv(dados_form.get("phev_consumo_eletrico", 0)),
            "consumo_combustivel": conv(dados_form.get("phev_consumo_combustivel", 0)),
        },
    }


# 4.9) Monta veículo elétrico futuro
def montar_veiculo_ve(dados_form):
    ipva_ve = 0.0 if "isencao_ipva_ve" in dados_form else conv(dados_form.get("ipva_ve", 0))

    preco = conv(dados_form.get("preco_ve", 0))
    modelo = limpar_nome_veiculo(dados_form.get("modelo_ve", "Veículo elétrico"))
    combustivel = dados_form.get("combustivel_ve", "")
    tipo_form = dados_form.get("tipo_veiculo_ve", "")
    tipo = "phev" if detectar_phev_texto(modelo, combustivel, tipo_form) else "ve"
    return {
        "nome": modelo,
        "tipo": tipo,
        "prefixo": "ve",
        "combustivel": combustivel,
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
        "nome": limpar_nome_veiculo(dados_form.get("modelo_icev", "Veículo a combustão")),
        "tipo": "icev",
        "prefixo": "icev",
        "combustivel": dados_form.get("combustivel_icev", ""),
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
        "nome": limpar_nome_veiculo(dados_form.get("modelo_atual", "Meu carro atual")),
        "tipo": "icev",
        "prefixo": "atual",
        "combustivel": dados_form.get("combustivel_atual", ""),
        "preco": preco,
        "consumo": conv(dados_form.get("consumo_atual", 1)),
        "manut": conv(dados_form.get("manut_atual", 0)),
        "ipva": conv(dados_form.get("ipva_atual", 0)),
        "seguro": seguro_formulario_ou_padrao(dados_form, "seguro_atual", preco),
        "depreciacao": conv(dados_form.get("depreciacao_atual", 0)) / 100.0,
        "financiamento": calcular_financiamento_form(dados_form, "atual", preco),
    }


# ============================================================
# 4.12) Auditoria técnica da simulação/TCO
# ============================================================
def montar_payload_auditoria_tco(resultado_final: dict) -> dict:
    form = resultado_final.get("form_values") or {}
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "tipo_comparacao": resultado_final.get("tipo_comparacao", ""),
        "parametros": {
            "uf": form.get("estado_uf") or form.get("uf") or "",
            "municipio": form.get("municipio") or form.get("municipio_select") or "",
            "anos": form.get("anos") or "",
            "km_ano": form.get("km_ano") or "",
            "energia": form.get("energia") or "",
            "combustivel": form.get("combustivel") or "",
            "aumento_energia": form.get("aumento_energia") or "0",
            "aumento_combustivel": form.get("aumento_combustivel") or "0",
        },
        "perfis": {
            "flex_configurado": form.get("fuel_flex_configurado") or "0",
            "flex_percent_etanol": form.get("fuel_percent_etanol") or "",
            "flex_preco_gasolina": form.get("fuel_preco_gasolina") or "",
            "flex_preco_etanol": form.get("fuel_preco_etanol") or "",
            "flex_consumo_gasolina": form.get("fuel_consumo_gasolina") or "",
            "flex_consumo_etanol": form.get("fuel_consumo_etanol") or "",
            "phev_configurado": form.get("phev_configurado") or "0",
            "phev_percent_eletrico": form.get("phev_percent_eletrico") or "",
            "phev_consumo_eletrico": form.get("phev_consumo_eletrico") or "",
            "phev_preco_combustivel": form.get("phev_preco_combustivel") or "",
            "phev_consumo_combustivel": form.get("phev_consumo_combustivel") or "",
        },
        "formulas": [
            {"nome": "Custo total", "formula": "custo total = gasto operacional acumulado + depreciação acumulada"},
            {"nome": "Gasto operacional", "formula": "energia/combustível + manutenção + IPVA + seguro + juros do financiamento"},
            {"nome": "Depreciação", "formula": "valor inicial - valor estimado de revenda"},
            {"nome": "Flex", "formula": "km×%gasolina/consumo_gasolina×preço_gasolina + km×%etanol/consumo_etanol×preço_etanol"},
            {"nome": "PHEV", "formula": "km×%elétrico×kWh/km×tarifa + km×%combustível/kmL×preço combustível"},
            {"nome": "CO₂ fóssil operacional", "formula": "energia elétrica, gasolina e diesel por fatores de emissão; etanol biogênico é informado à parte"},
            {"nome": "Árvores", "formula": "CO₂ evitado ÷ (0,060 tCO₂ por árvore.ano × anos de análise)"},
        ],
        "comparacoes": [],
        "notas": [
            "A auditoria mostra a memória de cálculo da simulação de custo total. Não substitui a auditoria específica das curvas de depreciação.",
            "O CO₂ é estimativa operacional. Não inclui fabricação do veículo, bateria, manutenção, transporte, descarte ou análise de ciclo de vida completa.",
            "O CO₂ da queima do etanol é tratado como biogênico e apresentado separadamente; não é chamado de zero absoluto.",
            "No financiamento, o custo total considera juros/custos financeiros no horizonte para evitar somar o principal duas vezes.",
        ],
    }

    for comp in resultado_final.get("comparacoes") or []:
        componentes = comp.get("comparacao_componentes") or comp.get("comparativo_componentes") or []
        memoria_anual = comp.get("memoria_anual") or []
        memoria_comparativa = comp.get("memoria_anual_comparativa") or []
        payload["comparacoes"].append({
            "titulo": comp.get("titulo", "Comparação"),
            "vencedor_nome": comp.get("vencedor_nome", ""),
            "economia": comp.get("economia", ""),
            "economia_percentual": comp.get("economia_percentual", ""),
            "detalhes": comp.get("detalhes") or [],
            "comparativo_indicadores": comp.get("comparativo_indicadores") or [],
            "comparacao_componentes": componentes,
            "comparativo_componentes": componentes,
            "impacto_ambiental": comp.get("impacto_ambiental") or {},
            "memoria_anual": memoria_anual,
            "memoria_anual_comparativa": memoria_comparativa,
            "auditoria_veiculos": comp.get("auditoria_veiculos") or [],
        })
    return payload


def registrar_auditoria_tco(resultado_final: dict) -> str:
    token = uuid.uuid4().hex
    AUDITORIA_TCO_CACHE[token] = montar_payload_auditoria_tco(resultado_final)
    while len(AUDITORIA_TCO_CACHE) > AUDITORIA_TCO_CACHE_MAX:
        primeiro = next(iter(AUDITORIA_TCO_CACHE.keys()))
        AUDITORIA_TCO_CACHE.pop(primeiro, None)
    return token


@tco_bp.route("/simular/auditoria")
def auditoria_tco():
    token = (request.args.get("token") or "").strip()
    auditoria = AUDITORIA_TCO_CACHE.get(token)
    if not auditoria:
        abort(404)
    return render_template("auditoria_tco.html", auditoria=auditoria)


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
            token_auditoria = registrar_auditoria_tco(resultado_final)
            resultado_final["auditoria_url"] = url_for("tco.auditoria_tco", token=token_auditoria)

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
        from services.combustivel_service import obter_precos_combustiveis
        dados = obter_precos_combustiveis(uf, municipio)
        dados.update({"uf": uf, "municipio": municipio})
        return jsonify(dados)
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

