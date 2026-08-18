import ast
import math
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "routes" / "tco_routes.py"
ROUTE = ROUTE_PATH.read_text(encoding="utf-8")
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
AUDITORIA = (ROOT / "templates" / "auditoria_tco.html").read_text(encoding="utf-8")
TREE = ast.parse(ROUTE)


def _nodes_by_name(*names):
    wanted = set(names)
    out = []
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            out.append(node)
        elif isinstance(node, ast.Assign):
            assigned = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if assigned & wanted:
                out.append(node)
    return out


def _monetary_ns():
    names = {
        "TCO_CONVENCAO_MONETARIA", "TCO_CONVENCAO_MONETARIA_ROTULO", "TCO_METODOLOGIA_MONETARIA_VERSAO",
        "TCO_MOEDA", "TCO_INFLACAO_FONTE", "TCO_INFLACAO_RECORTE", "TCO_CALIBRACAO_INICIO",
        "TCO_CALIBRACAO_FIM", "TCO_CALIBRACAO_ANOS", "TCO_ENERGIA_ITEM_SIDRA", "TCO_COMBUSTIVEL_ITEM_SIDRA",
        "TCO_IPCA_GERAL_ANUAL_PERCENTUAL", "TCO_ENERGIA_NOMINAL_ANUAL_PERCENTUAL",
        "TCO_COMBUSTIVEL_NOMINAL_ANUAL_PERCENTUAL", "taxa_anual_equivalente_percentual", "taxa_real_percentual",
        "TCO_INFLACAO_GERAL_EQUIVALENTE_PERCENTUAL", "TCO_ENERGIA_NOMINAL_ORIGEM_PERCENTUAL",
        "TCO_COMBUSTIVEL_NOMINAL_ORIGEM_PERCENTUAL", "TCO_ENERGIA_REAL_CALCULADA_PERCENTUAL",
        "TCO_COMBUSTIVEL_REAL_CALCULADA_PERCENTUAL", "TCO_ENERGIA_REAL_PADRAO_PERCENTUAL",
        "TCO_COMBUSTIVEL_REAL_PADRAO_PERCENTUAL", "AUMENTO_ENERGIA_PADRAO_PERCENTUAL",
        "AUMENTO_COMBUSTIVEL_PADRAO_PERCENTUAL", "AUMENTO_ENERGIA_PADRAO", "AUMENTO_COMBUSTIVEL_PADRAO",
    }
    ns = {}
    # Preserve source order because derived constants depend on previous definitions.
    for node in TREE.body:
        take = False
        if isinstance(node, ast.FunctionDef) and node.name in names:
            take = True
        elif isinstance(node, ast.Assign):
            assigned = {t.id for t in node.targets if isinstance(t, ast.Name)}
            take = bool(assigned & names)
        if take:
            exec(compile(ast.Module([node], type_ignores=[]), str(ROUTE_PATH), "exec"), ns)
    return ns


def _finance_ns():
    ns = _monetary_ns()
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"juros_financiamento_por_ano", "juros_financiamento_monetario_por_ano"}:
            exec(compile(ast.Module([node], type_ignores=[]), str(ROUTE_PATH), "exec"), ns)
    return ns


def test_calibracao_reproduz_defaults_nominais_e_ipca_geral():
    ns = _monetary_ns()
    assert math.isclose(ns["TCO_ENERGIA_NOMINAL_ORIGEM_PERCENTUAL"], 4.642787197813325, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(ns["TCO_COMBUSTIVEL_NOMINAL_ORIGEM_PERCENTUAL"], 5.563079767141721, rel_tol=0, abs_tol=1e-12)
    assert round(ns["TCO_ENERGIA_NOMINAL_ORIGEM_PERCENTUAL"], 1) == 4.6
    assert round(ns["TCO_COMBUSTIVEL_NOMINAL_ORIGEM_PERCENTUAL"], 1) == 5.6
    assert math.isclose(ns["TCO_INFLACAO_GERAL_EQUIVALENTE_PERCENTUAL"], 5.6611317411088935, rel_tol=0, abs_tol=1e-12)


def test_conversao_nominal_real_casos_matematicos():
    fn = _monetary_ns()["taxa_real_percentual"]
    assert math.isclose(fn(5.0, 5.0), 0.0, abs_tol=1e-12)
    assert fn(7.0, 5.0) > 0
    assert fn(3.0, 5.0) < 0
    assert math.isclose(fn(3.25, 0.0), 3.25, abs_tol=1e-12)


def test_defaults_reais_sao_negativos_e_nao_truncados():
    ns = _monetary_ns()
    assert math.isclose(ns["TCO_ENERGIA_REAL_CALCULADA_PERCENTUAL"], -0.9637834902154196, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(ns["TCO_COMBUSTIVEL_REAL_CALCULADA_PERCENTUAL"], -0.09279852709453973, rel_tol=0, abs_tol=1e-12)
    assert ns["AUMENTO_ENERGIA_PADRAO_PERCENTUAL"] == -0.96
    assert ns["AUMENTO_COMBUSTIVEL_PADRAO_PERCENTUAL"] == -0.09


def test_preco_anual_usa_ano_um_sem_reajuste():
    assert 'energia_ano = energia_inicial * ((1 + aumento_energia) ** (ano - 1))' in ROUTE
    assert 'combustivel_ano = combustivel_inicial * ((1 + aumento_combustivel) ** (ano - 1))' in ROUTE
    base = 100.0
    g = -0.0096
    assert math.isclose(base * ((1 + g) ** (1 - 1)), 100.0)
    assert math.isclose(base * ((1 + g) ** (2 - 1)), 99.04)


def test_financiamento_price_permanece_nominal_e_juros_sao_deflacionados_mes_a_mes():
    ns = _finance_ns()
    fn = ns["juros_financiamento_monetario_por_ano"]
    principal = 1000.0
    i = 0.01
    months = 3
    factor = (1 + i) ** months
    payment = principal * (i * factor) / (factor - 1)
    fin = {"ativo": True, "principal": principal, "taxa_mensal": i, "meses": months, "parcela": payment}
    pi = 12.0
    got = fn(fin, 1, pi)

    pi_m = (1.12 ** (1 / 12)) - 1
    saldo = principal
    nominal = 0.0
    real = 0.0
    for mes in range(1, 4):
        j = saldo * i
        nominal += j
        real += j / ((1 + pi_m) ** mes)
        saldo -= payment - j
    assert math.isclose(got["nominais"][0], nominal, rel_tol=0, abs_tol=1e-10)
    assert math.isclose(got["reais"][0], real, rel_tol=0, abs_tol=1e-10)
    assert got["reais"][0] < got["nominais"][0]
    assert [m["mes"] for m in got["memoria_mensal"]] == [1, 2, 3]


def test_interface_mantem_taxas_reais_e_auditoria_preserva_convencao_apos_limpeza_visual():
    assert "Variação real anual da energia (%)" in SIMULAR
    assert "Variação real anual dos combustíveis (%)" in SIMULAR
    assert 'value="-0,96"' in SIMULAR
    assert 'value="-0,09"' in SIMULAR
    # V50.26 removeu essas notas da interface/PDF, mas a metodologia permanece na auditoria/backend.
    assert "TCO acumulado em reais constantes da data-base da simulação" not in SIMULAR
    assert "Valores monetários acumulados expressos em reais constantes da data-base da simulação" not in SIMULAR
    assert "Convenção monetária" in AUDITORIA
    assert 'TCO_CONVENCAO_MONETARIA = "reais_constantes_data_base"' in ROUTE


def test_auditoria_registra_convencao_calibracao_e_juros_nominais_reais():
    for token in (
        "Convenção monetária", "IPCA geral equivalente", "energia nominal de origem",
        "energia real usada", "combustíveis nominal de origem", "combustíveis real usada",
        "Juros nominais", "Juros reais", "Total anual real", "não aplicada", "não calculado",
    ):
        assert token in AUDITORIA
    assert '"metodologia_monetaria": metodologia_monetaria' in ROUTE
    assert '"financiamento_juros_nominais": juros_financiamento_nominal_ano' in ROUTE
    assert '"financiamento_juros_reais": juros_financiamento_ano' in ROUTE


def test_snapshot_novo_congela_metodologia_e_antigo_nao_e_recalculado_pelo_registro():
    assert '"metodologia_monetaria": resultado_final.get("metodologia_monetaria") or {}' in ROUTE
    assert '"auditoria": _remover_html_graficos_snapshot(montar_payload_auditoria_tco(resultado_final))' in ROUTE
    # A rota de registro apenas persiste payload; recuperação histórica continua fora do cálculo TCO.
    snapshot_def = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_registrar_snapshot_tco")
    snapshot_src = ast.get_source_segment(ROUTE, snapshot_def) or ""
    assert "calcular_projecao_veiculo" not in snapshot_src
    assert "estimar_seguro_v2" not in snapshot_src
    # A apresentação nova só é aplicada quando o snapshot possui metadado monetário V50.24.
    # Snapshots legados mantêm rótulos/reajustes históricos e não recebem retroativamente a convenção real.
    assert "{% if resultado.metodologia_monetaria %}" in SIMULAR
    assert "Aumento anual da energia" in SIMULAR
    assert "Aumento anual do combustível" in SIMULAR
    assert "{% set monetaria = auditoria.metodologia_monetaria|default(None) %}" in AUDITORIA
    assert "auditoria.parametros.aumento_energia" in AUDITORIA
    assert "auditoria.parametros.aumento_combustivel" in AUDITORIA
    # Invalida apenas o estado temporário de formulário da semântica nominal anterior.
    assert 'PLUGVE_TCO_STORAGE_KEY = "plugve_tco_form_state_v27"' in SIMULAR


def test_seguro_manual_permanece_percentual_da_trajetoria_real_sem_inflacao_extra():
    projection_def = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "calcular_projecao_veiculo")
    src = ast.get_source_segment(ROUTE, projection_def) or ""
    assert "taxa_seguro = taxa_relativa(seguro_inicial, preco)" in src
    assert "seguro_ano = valor_mercado * taxa_seguro" in src
    assert "inflacao_geral_percentual" not in src.split("seguro_ano = valor_mercado * taxa_seguro", 1)[0][-250:]


def test_versionamento_metodologico_e_site():
    cfg = (ROOT / "config.py").read_text(encoding="utf-8")
    assert 'CURVE_VERSION = "V50.27"' in cfg
    assert 'TCO_METODOLOGIA_MONETARIA_VERSAO = "TCO_REAL_BASE_V1"' in ROUTE
