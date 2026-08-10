import ast
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TCO_PATH = ROOT / "routes" / "tco_routes.py"
TCO = TCO_PATH.read_text(encoding="utf-8")
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
AUDITORIA = (ROOT / "templates" / "auditoria_tco.html").read_text(encoding="utf-8")


def _co2_namespace():
    tree = ast.parse(TCO, filename=str(TCO_PATH))
    selected = []
    wanted_functions = {
        "normalizar",
        "fatores_combustivel_operacional_kg_l",
        "fator_combustivel_co2_kg_l",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            nomes = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(n.startswith("FATOR_CO2_") or n.startswith("FRAC_") for n in nomes):
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            selected.append(node)
    ns = {"os": os, "unicodedata": __import__("unicodedata")}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(TCO_PATH), "exec"), ns)
    return ns


def test_fuel_pure_factors_and_commercial_blends_are_the_final_methodology():
    ns = _co2_namespace()
    assert math.isclose(ns["FATOR_CO2_GASOLINA_A_FOSSIL_KG_L"], 2.23)
    assert math.isclose(ns["FATOR_CO2_ETANOL_ANIDRO_BIOGENICO_KG_L"], 1.58)
    assert math.isclose(ns["FATOR_CO2_ETANOL_HIDRATADO_BIOGENICO_KG_L"], 1.51)
    assert math.isclose(ns["FATOR_CO2_DIESEL_MINERAL_FOSSIL_KG_L"], 2.63)
    assert math.isclose(ns["FATOR_CO2_BIODIESEL_BIOGENICO_KG_L"], 2.46)
    assert math.isclose(ns["FRAC_GASOLINA_A_E30"], 0.70)
    assert math.isclose(ns["FRAC_ETANOL_ANIDRO_E30"], 0.30)
    assert math.isclose(ns["FRAC_DIESEL_MINERAL_B15"], 0.85)
    assert math.isclose(ns["FRAC_BIODIESEL_B15"], 0.15)


def test_effective_commercial_factors_split_fossil_and_biogenic():
    ns = _co2_namespace()
    fn = ns["fatores_combustivel_operacional_kg_l"]
    gasolina = fn("Gasolina")
    etanol = fn("Etanol")
    diesel = fn("Diesel S10")
    assert gasolina["tipo"] == "gasolina_c_e30"
    assert math.isclose(gasolina["fossil_kg_l"], 0.70 * 2.23)
    assert math.isclose(gasolina["biogenico_kg_l"], 0.30 * 1.58)
    assert etanol["tipo"] == "etanol_hidratado"
    assert math.isclose(etanol["fossil_kg_l"], 0.0)
    assert math.isclose(etanol["biogenico_kg_l"], 1.51)
    assert diesel["tipo"] == "diesel_b15"
    assert math.isclose(diesel["fossil_kg_l"], 0.85 * 2.63)
    assert math.isclose(diesel["biogenico_kg_l"], 0.15 * 2.46)


def test_sin_factor_has_explicit_value_and_date_base_and_can_be_overridden():
    assert 'PLUGVE_CO2_SIN_KG_KWH' in TCO
    assert 'PLUGVE_CO2_SIN_DATA_BASE' in TCO
    assert '"0.0461"' in TCO
    assert '"2025 - média anual"' in TCO
    assert 'FATOR_CO2_ENERGIA_DATA_BASE' in TCO


def test_old_unqualified_operational_factors_are_gone():
    for old in ["2.212", "1.526", "2.603", "0.0289"]:
        assert old not in TCO


def test_flex_and_phev_account_for_biogenic_parts_separately():
    assert 'co2_gasolina_biogenico_kg = litros_gasolina * FATOR_CO2_GASOLINA_C_E30_BIOGENICO_KG_L' in TCO
    assert 'co2_etanol_biogenico_kg = litros_etanol * FATOR_CO2_ETANOL_HIDRATADO_BIOGENICO_KG_L' in TCO
    assert 'co2_diesel_biogenico_kg' in TCO
    assert 'fatores_phev = fatores_combustivel_operacional_kg_l(combustivel_descricao, "gasolina")' in TCO
    assert 'co2_biogenico_anual_kg = co2_gasolina_biogenico_kg + co2_etanol_biogenico_kg + co2_diesel_biogenico_kg' in TCO


def test_ui_pdf_and_audit_explain_new_methodology_and_date_base():
    assert 'Gasolina C E30 — fóssil' in SIMULAR
    assert 'Gasolina C E30 — biogênico' in SIMULAR
    assert 'Etanol hidratado — biogênico' in SIMULAR
    assert 'Diesel B15 — biogênico' in SIMULAR
    assert 'data-base {{ comp.impacto_ambiental.fatores.energia_data_base }}' in SIMULAR
    assert 'CO₂ biogênico dos biocombustíveis é informado separadamente' in SIMULAR
    assert 'CO₂ biogênico operacional' in AUDITORIA
    assert 'gasolina C comum' in AUDITORIA
    assert 'diesel B15' in AUDITORIA


def test_audit_formula_documents_commercial_blends_not_pure_fuels():
    assert 'Gasolina C comum E30: CO₂_fóssil = L × 0,70 × 2,23; CO₂_biogênico = L × 0,30 × 1,58' in TCO
    assert 'Etanol hidratado: CO₂_fóssil = 0; CO₂_biogênico = L × 1,51' in TCO
    assert 'Diesel B15: CO₂_fóssil = L × 0,85 × 2,63; CO₂_biogênico = L × 0,15 × 2,46' in TCO
