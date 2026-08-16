from __future__ import annotations

from pathlib import Path

from services.site_usage_service import SiteUsageService

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _seed(service: SiteUsageService) -> None:
    go = {
        "network_hash": "network-go",
        "city": "Goiânia",
        "region": "GO",
        "country": "BR",
        "browser_family": "Chrome",
        "device_type": "desktop",
        "os_family": "Windows",
        "path": "/simular",
    }
    sp = {
        "network_hash": "network-sp",
        "city": "São Paulo",
        "region": "SP",
        "country": "BR",
        "browser_family": "Safari",
        "device_type": "mobile",
        "os_family": "iOS",
        "path": "/consulta-fipe",
    }
    service.record_event(
        visitor_id="visitor-go", session_id="session-go", event_type="analysis",
        module="tco", action="simulation_completed", request_context=go,
        simulation_uf="GO", simulation_city="Goiânia", horizon_years=5, km_year=15000,
        metadata={"resultado_codigo": "S-20260815-23456789AB"},
        vehicles=[
            {"role": "ve", "marca": "BYD", "modelo": "Dolphin", "codigo_fipe": "001234-5", "tecnologia": "BEV"},
            {"role": "icev", "marca": "Toyota", "modelo": "Yaris", "codigo_fipe": "009876-5", "tecnologia": "ICEV"},
        ], analysis_type="tco",
    )
    service.record_event(
        visitor_id="visitor-go", session_id="session-go", event_type="analysis",
        module="depreciacao", action="consultation_completed", request_context=go,
        metadata={"resultado_codigo": "D-20260815-23456789EF", "tipo_curva": "propria"},
        vehicles=[{"role": "consultado", "marca": "BYD", "modelo": "Dolphin", "codigo_fipe": "001234-5", "tecnologia": "EV_PURO"}],
        analysis_type="depreciacao",
    )
    service.record_event(
        visitor_id="visitor-sp", session_id="session-sp", event_type="analysis",
        module="fipe_plus", action="consultation_completed", request_context=sp,
        metadata={"resultado_codigo": "F-20260815-23456789CD"},
        vehicles=[{"role": "consultado", "marca": "GWM", "modelo": "Haval H6 GT", "codigo_fipe": "096999-9", "tecnologia": "PHEV"}],
        analysis_type="fipe_plus",
    )
    service.record_event(
        visitor_id="visitor-sp", session_id="session-sp", event_type="export",
        module="fipe_plus", action="pdf_exported", request_context=sp,
        metadata={"resultado_codigo": "F-20260815-23456789CD"},
    )
    service.record_event(
        visitor_id="visitor-go", session_id="session-go", event_type="interaction",
        module="resultado", action="historical_result_opened", request_context=go,
        metadata={"resultado_codigo": "S-20260815-23456789AB"},
    )


def test_combined_market_filters_slice_summary_events_and_visitors(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    _seed(service)

    go_bev = service.telemetry_summary(access_location="GO", technology="bev")
    assert go_bev["counts"]["researches"] == 2
    assert go_bev["counts"]["visitors"] == 1
    assert go_bev["counts"]["tco_simulations"] == 1
    assert go_bev["counts"]["depreciation_consultations"] == 1
    assert go_bev["counts"]["fipe_plus_consultations"] == 0

    # Filtros de veículo e marca são filtros do evento. Isso permite cruzar:
    # "eventos que contêm Dolphin E também contêm Toyota".
    cross = service.telemetry_summary(vehicle="Dolphin", brand="Toyota")
    assert cross["counts"]["researches"] == 1
    assert {item["modelo"] for item in cross["top_vehicles"]} == {"Dolphin", "Yaris"}

    events = service.list_events(access_location="Goiânia", technology="bev")["events"]
    assert {event["module"] for event in events} == {"tco", "depreciacao"}
    visitors = service.list_visitors(technology="phev")["visitors"]
    assert len(visitors) == 1
    assert visitors[0]["city"] == "São Paulo"
    assert visitors[0]["period_researches"] == 1


def test_result_activity_and_result_code_filters_are_independent(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    _seed(service)

    result_open = service.telemetry_summary(activity="resultado")
    assert result_open["counts"]["historical_result_opens"] == 1
    assert result_open["counts"]["researches"] == 0

    by_code = service.telemetry_summary(result_code="S-20260815")
    assert by_code["counts"]["events"] == 2  # TCO original + reabertura histórica
    assert by_code["counts"]["tco_simulations"] == 1
    assert by_code["counts"]["historical_result_opens"] == 1

    pdf = service.telemetry_summary(activity="pdf")
    assert pdf["counts"]["events"] == 1
    assert pdf["counts"]["pdf_exports"] == 1


def test_market_rankings_expose_visitors_breakdowns_cities_and_active_devices(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    _seed(service)
    summary = service.telemetry_summary()

    dolphin = next(item for item in summary["top_vehicles"] if item["modelo"] == "Dolphin")
    assert dolphin["uses"] == 2
    assert dolphin["visitors"] == 1
    assert dolphin["tco"] == 1
    assert dolphin["depreciacao"] == 1
    assert dolphin["codigo_fipe"] == "001234-5"

    assert summary["top_pairs"][0]["uses"] == 1
    assert summary["top_pairs"][0]["visitors"] == 1
    assert {item["technology"] for item in summary["technology_usage"]} >= {"bev", "phev", "icev"}
    assert summary["access_locations"][0]["researches"] >= 1
    assert summary["top_active_visitors"][0]["researches"] >= 1
    assert summary["counts"]["researches"] == 3
    assert summary["counts"]["historical_result_opens"] == 1


def test_new_telemetry_normalizes_propulsion_without_rewriting_legacy_ve(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    service.record_event(
        visitor_id="v", session_id="s", event_type="analysis", module="fipe_plus",
        action="consultation_completed", request_context={"path": "/consulta-fipe"},
        vehicles=[
            {"modelo": "A", "tecnologia": "EV_PURO"},
            {"modelo": "B", "tecnologia": "PLUG_IN"},
            {"modelo": "C", "tecnologia": "HEV_NAO_PLUGIN"},
            {"modelo": "D", "tecnologia": "COMBUSTAO"},
            {"modelo": "E", "tecnologia": "ve"},
        ], analysis_type="fipe_plus",
    )
    event = service.list_events(module="fipe_plus")["events"][0]
    assert [v["technology"] for v in event["vehicles"]] == ["bev", "phev", "hev", "icev", "ve"]


def test_admin_v5016_has_global_market_filters_rankings_and_shared_query_parameters():
    html = read("templates/admin_usage.html")
    js = read("static/js/admin_usage.js")
    css = read("static/css/admin_usage.css")
    routes = read("routes/usage_routes.py")
    service = read("services/site_usage_service.py")

    assert "Inteligência V50.17" in html
    for identifier in (
        "admin_filter_activity", "admin_filter_vehicle", "admin_filter_technology",
        "admin_filter_brand", "admin_filter_access", "admin_filter_simulation",
        "admin_filter_environment", "admin_filter_result_code", "admin_top_active_visitors",
    ):
        assert f'id="{identifier}"' in html
    assert "Filtros combinados" in html
    assert "Veículos mais pesquisados" in html
    assert "Visitantes / dispositivos" in html
    assert "Cidade/UF do acesso" in html
    assert "Local usado na simulação" in html

    assert "state.marketFilters" in js
    assert "applyMarketFilters" in js
    assert "clearMarketFilters" in js
    assert 'params.set(key, String(value).trim())' in js
    assert "metric_researches" in js
    assert "metric_result_opens" in js
    assert "admin_top_active_visitors" in js
    assert ".admin-market-filter-grid" in css

    assert "def _market_filter_args()" in routes
    assert "**_market_filter_args()" in routes
    assert "def _event_filter_where(" in service
    assert "top_active_visitors" in service
    assert "COUNT(DISTINCT e.visitor_hash) AS visitors" in service


def test_tco_telemetry_source_uses_canonical_bev_phev_and_classifier_for_hev_icev():
    source = read("routes/tco_routes.py")
    assert "def _tecnologia_telemetria_tco" in source
    assert 'form.get("tipo_veiculo_ve")' in source
    assert 'if canonico in {"bev", "phev"}' in source
    assert "classificar_tipo_veiculo(" in source
    assert 'TIPO_HEV: "hev"' in source
    assert 'TIPO_COMBUSTAO: "icev"' in source
