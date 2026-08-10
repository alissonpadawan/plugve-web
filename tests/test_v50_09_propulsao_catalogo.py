from __future__ import annotations

from pathlib import Path

from services.fipe_catalog_classifier import FipeCatalogPropulsionClassifier
from services.tipo_veiculo_service import (
    TIPO_HEV,
    TIPO_PHEV,
    classificar_tipo_veiculo,
)


def _ctx(decision) -> str:
    if decision.contexts == frozenset({"ve"}):
        return "ve"
    if decision.contexts == frozenset({"icev"}):
        return "icev"
    return "misto"


def test_haval_h6_tecnologia_real_no_catalogo():
    classifier = FipeCatalogPropulsionClassifier()
    casos = [
        ("Haval H6 1.5 AWD (Hibrido)", 2024, "icev"),
        ("Haval H6 ONE 1.5 (Hibrido)", 2026, "icev"),
        ("Haval H6 2 1.5 (Híbrido)", 2026, "icev"),
        ("Haval H6 HEV2 1.5 (Híbrido)", 2026, "icev"),
        ("Haval H6 GT 1.5 AWD (Híbrido)", 2025, "ve"),
        ("Haval H6 PHEV19 1.5 (Híbrido)", 2026, "ve"),
        ("Haval H6 PHEV34 1.5 (Híbrido)", 2026, "ve"),
        ("Haval H6 PHEV35 1.5 (Híbrido)", 2026, "ve"),
    ]
    for modelo, ano, esperado in casos:
        decisao = classifier.classify("GWM", modelo, year=ano, fuel=f"{ano} Híbrido")
        assert _ctx(decisao) == esperado, (modelo, decisao.as_dict())


def test_phev_colado_a_numero_e_reconhecido_globalmente():
    classifier = FipeCatalogPropulsionClassifier()
    decisao = classifier.classify(
        "LAND ROVER",
        "Range Rover Sport PHEV404 HSE (Híbrido)",
        year=2020,
        fuel="2020 Híbrido",
    )
    assert _ctx(decisao) == "ve"
    assert decisao.tipo_plugve == "PHEV"


def test_fallback_tipo_haval_h6_nao_depende_do_lado_da_tela():
    assert classificar_tipo_veiculo("Haval H6 GT 1.5 AWD (Híbrido)", "Híbrido", "2025", "GWM") == TIPO_PHEV
    assert classificar_tipo_veiculo("Haval H6 PHEV19 1.5 (Híbrido)", "Híbrido", "2026", "GWM") == TIPO_PHEV
    assert classificar_tipo_veiculo("Haval H6 PHEV35 1.5 (Híbrido)", "Híbrido", "2026", "GWM") == TIPO_PHEV
    assert classificar_tipo_veiculo("Haval H6 HEV2 1.5 (Híbrido)", "Híbrido", "2026", "GWM") == TIPO_HEV
    assert classificar_tipo_veiculo("Haval H6 ONE 1.5 (Híbrido)", "Híbrido", "2026", "GWM") == TIPO_HEV


def test_frontend_prioriza_tipo_canonico_do_backend():
    root = Path(__file__).resolve().parents[1]
    html = (root / "templates" / "simular.html").read_text(encoding="utf-8")
    assert "tipoCatalogoAnoSelecionadoTCO(anoSelect)" in html
    assert 'opt?.dataset?.tipoVeiculo' in html
    assert 'prefixoNorm === "ve" && ehHibridoGenerico' not in html
    assert r"PHEV(?:\s*[-/]?\s*\d{1,4})?" in html
