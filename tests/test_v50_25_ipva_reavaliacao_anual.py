import ast
import math
from datetime import date
from pathlib import Path

from services.ipva_service import IpvaService

ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "routes" / "tco_routes.py"
ROUTE = ROUTE_PATH.read_text(encoding="utf-8")
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
AUDITORIA = (ROOT / "templates" / "auditoria_tco.html").read_text(encoding="utf-8")
TREE = ast.parse(ROUTE)


def _fn_node(name):
    return next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _ipva_ns():
    ns = {"date": date, "IpvaService": IpvaService}
    for name in ("_ano_base_simulacao", "calcular_ipva_projetado_ano"):
        node = _fn_node(name)
        exec(compile(ast.Module([node], type_ignores=[]), str(ROUTE_PATH), "exec"), ns)
    return ns


def _veiculo_ipva(*, ano_fabricacao="2012", combustivel="Gasolina", tipo_propulsao="Gasolina", origem="automatico", preco=100000.0):
    return {
        "preco": preco,
        "combustivel": combustivel,
        "ipva_meta": {
            "origem": origem,
            "ano_fabricacao": ano_fabricacao,
            "ano_aquisicao": ano_fabricacao,
            "valor_primeira_compra": preco,
            "combustivel": combustivel,
            "tipo_propulsao": tipo_propulsao,
            "potencia_cv": None,
            "cilindrada_cc": None,
            "motor": "",
            "categoria": "",
            "uso": "particular",
            "compra_local": None,
            "zero_km": str(ano_fabricacao).lower().startswith("zero km"),
        },
    }


def _calc(veiculo, *, uf, valor, ano, taxa):
    fn = _ipva_ns()["calcular_ipva_projetado_ano"]
    comum = {"uf": uf, "data_base_monetaria": "2026-08-18"}
    return fn(veiculo=veiculo, comum=comum, valor_mercado=valor, ano_indice=ano, taxa_ipva_legada=taxa)


def test_arquitetura_reutiliza_ipva_service_sem_duplicar_regras_estaduais():
    src = ast.get_source_segment(ROUTE, _fn_node("calcular_ipva_projetado_ano")) or ""
    assert "IpvaService.calcular" in src
    assert "ANOS_ISENCAO_IDADE" not in src
    assert 'if uf == "' not in src


def test_go_adquire_isencao_exatamente_aos_15_anos():
    veiculo = _veiculo_ipva(ano_fabricacao="2012")
    ano1 = _calc(veiculo, uf="GO", valor=100000, ano=1, taxa=0.0375)
    ano2 = _calc(veiculo, uf="GO", valor=90000, ano=2, taxa=0.0375)
    ano3 = _calc(veiculo, uf="GO", valor=81000, ano=3, taxa=0.0375)

    assert ano1["ano_calendario"] == 2026
    assert ano1["idade_veiculo"] == 14
    assert math.isclose(ano1["ipva"], 3750.0, abs_tol=1e-9)
    assert not ano1["isento"]

    assert ano2["ano_calendario"] == 2027
    assert ano2["idade_veiculo"] == 15
    assert ano2["ipva"] == 0.0
    assert ano2["isento"]
    assert ano2["isencao_idade"]

    assert ano3["idade_veiculo"] == 16
    assert ano3["ipva"] == 0.0
    assert ano3["isento"]


def test_fronteira_um_ano_antes_no_limite_e_um_ano_depois():
    veiculo = _veiculo_ipva(ano_fabricacao="2012")
    idades = [_calc(veiculo, uf="GO", valor=100000, ano=n, taxa=0.0375)["idade_veiculo"] for n in (1, 2, 3)]
    isentos = [_calc(veiculo, uf="GO", valor=100000, ano=n, taxa=0.0375)["isento"] for n in (1, 2, 3)]
    assert idades == [14, 15, 16]
    assert isentos == [False, True, True]


def test_veiculo_ja_isento_permanece_zero_desde_ano_um():
    veiculo = _veiculo_ipva(ano_fabricacao="2010")
    for ano in (1, 2, 3):
        got = _calc(veiculo, uf="GO", valor=100000 * (0.9 ** (ano - 1)), ano=ano, taxa=0.0375)
        assert got["ipva"] == 0.0
        assert got["isento"]
        assert got["isencao_idade"]


def test_sem_mudanca_de_isencao_recalcula_sobre_valor_projetado():
    veiculo = _veiculo_ipva(ano_fabricacao="2020")
    a1 = _calc(veiculo, uf="SP", valor=100000, ano=1, taxa=0.04)
    a2 = _calc(veiculo, uf="SP", valor=90000, ano=2, taxa=0.04)
    a3 = _calc(veiculo, uf="SP", valor=81000, ano=3, taxa=0.04)
    assert [a1["ipva"], a2["ipva"], a3["ipva"]] == [4000.0, 3600.0, 3240.0]
    assert not any(x["isento"] for x in (a1, a2, a3))


def test_beneficios_tecnologicos_continuam_no_motor_central():
    bev = _veiculo_ipva(ano_fabricacao="2026", combustivel="Elétrico", tipo_propulsao="BEV")
    hev = _veiculo_ipva(ano_fabricacao="2026", combustivel="Gasolina", tipo_propulsao="HEV")
    phev = _veiculo_ipva(ano_fabricacao="2026", combustivel="Gasolina", tipo_propulsao="PHEV")

    r_bev = _calc(bev, uf="RJ", valor=100000, ano=1, taxa=0.005)
    r_hev = _calc(hev, uf="RJ", valor=100000, ano=1, taxa=0.015)
    r_phev = _calc(phev, uf="RJ", valor=100000, ano=1, taxa=0.015)
    assert math.isclose(r_bev["ipva"], 500.0, abs_tol=1e-9)
    assert math.isclose(r_hev["ipva"], 1500.0, abs_tol=1e-9)
    assert math.isclose(r_phev["ipva"], 1500.0, abs_tol=1e-9)
    assert r_bev["criterio"] == "tecnologia"
    assert r_hev["criterio"] == "tecnologia"
    assert r_phev["criterio"] == "tecnologia"


def test_zero_km_inicia_com_idade_zero_e_nao_fica_negativo():
    veiculo = _veiculo_ipva(ano_fabricacao="Zero km 2026", combustivel="Elétrico", tipo_propulsao="BEV")
    a1 = _calc(veiculo, uf="AM", valor=150000, ano=1, taxa=0.015)
    a2 = _calc(veiculo, uf="AM", valor=140000, ano=2, taxa=0.015)
    assert a1["idade_veiculo"] == 0
    assert a2["idade_veiculo"] == 1
    assert a1["ipva"] >= 0 and a2["ipva"] >= 0


def test_ipva_independe_de_financiamento_e_seguro():
    base = _veiculo_ipva(ano_fabricacao="2012")
    com_extras = {**base, "financiamento": {"ativo": True, "principal": 999999}, "seguro": 12345, "seguro_meta": {"origem": "automatico"}}
    a = _calc(base, uf="GO", valor=90000, ano=2, taxa=0.0375)
    b = _calc(com_extras, uf="GO", valor=90000, ano=2, taxa=0.0375)
    assert a["ipva"] == b["ipva"]
    assert a["regra"] == b["regra"]


def test_ipva_manual_preserva_taxa_informada_mas_respeita_isencao_futura():
    veiculo = _veiculo_ipva(ano_fabricacao="2012", origem="manual")
    a1 = _calc(veiculo, uf="GO", valor=100000, ano=1, taxa=0.05)
    a2 = _calc(veiculo, uf="GO", valor=90000, ano=2, taxa=0.05)
    assert math.isclose(a1["ipva"], 5000.0, abs_tol=1e-9)
    assert a1["criterio"] == "manual_com_reavaliacao_elegibilidade"
    assert a2["ipva"] == 0.0
    assert a2["isencao_idade"]


def test_formulario_legado_preserva_taxa_v50_24_por_compatibilidade():
    veiculo = {"preco": 100000, "combustivel": "Gasolina", "ipva_meta": {"origem": "legado"}}
    a2 = _calc(veiculo, uf="GO", valor=90000, ano=2, taxa=0.0375)
    assert math.isclose(a2["ipva"], 3375.0, abs_tol=1e-9)
    assert not a2["reavaliado_anualmente"]


def test_interface_marca_origem_ipva_e_pdf_nao_exibe_taxa_fixa_quando_anual():
    for token in ('name="ipva_atual_manual"', 'name="ipva_ve_manual"', 'name="ipva_icev_manual"'):
        assert token in SIMULAR
    assert "marcarIpvaManualTCO" in SIMULAR
    assert "tipo_propulsao: tipoPropulsao || \"\"" in SIMULAR
    assert "Reavaliado ano a ano" in SIMULAR
    assert "Regras cadastradas na data-base aplicadas à idade e ao valor projetados." in SIMULAR


def test_auditoria_registra_idade_regra_isencao_e_ipva_anual():
    for token in ("Memória anual do IPVA", "Exercício", "Idade", "Valor-base", "Alíquota", "Isento?", "Critério/regra"):
        assert token in AUDITORIA
    for token in (
        '"ipva_ano_calendario":', '"ipva_idade_veiculo":', '"ipva_criterio":', '"ipva_regra":',
        '"ipva_isento":', '"ipva_isencao_idade":', '"ipva_beneficio_tecnologia":',
    ):
        assert token in ROUTE


def test_snapshot_s_novo_congela_memoria_e_antigo_nao_e_recalculado():
    snapshot = _fn_node("_registrar_snapshot_tco")
    src = ast.get_source_segment(ROUTE, snapshot) or ""
    assert '"resultado": _remover_html_graficos_snapshot' in src
    assert '"auditoria": _remover_html_graficos_snapshot' in src
    assert "calcular_ipva_projetado_ano" not in src
    assert "IpvaService.calcular" not in src


def test_regressao_monetaria_v50_24_e_versionamento_v50_25():
    assert 'TCO_METODOLOGIA_MONETARIA_VERSAO = "TCO_REAL_BASE_V1"' in ROUTE
    assert 'AUMENTO_ENERGIA_PADRAO_PERCENTUAL = TCO_ENERGIA_REAL_PADRAO_PERCENTUAL' in ROUTE
    assert 'AUMENTO_COMBUSTIVEL_PADRAO_PERCENTUAL = TCO_COMBUSTIVEL_REAL_PADRAO_PERCENTUAL' in ROUTE
    assert '"ipva_metodologia_versao": "IPVA_ANUAL_V1"' in ROUTE
    cfg = (ROOT / "config.py").read_text(encoding="utf-8")
    assert 'CURVE_VERSION = "V50.27"' in cfg
