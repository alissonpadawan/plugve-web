from __future__ import annotations

from pathlib import Path

from services.result_history_service import build_result_admin_summary
from services.site_usage_service import SiteUsageService

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_event_detail_keeps_pseudonymous_environment_and_vehicle_data(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    event_id = service.record_event(
        visitor_id="visitor-123",
        session_id="session-456",
        event_type="analysis",
        module="tco",
        action="simulation_completed",
        request_context={
            "network_hash": "abcdeffedcba123456789",
            "city": "Goiânia",
            "region": "GO",
            "country": "BR",
            "browser_family": "Chrome",
            "device_type": "desktop",
            "os_family": "Windows",
            "path": "/simular",
        },
        metadata={"resultado_codigo": "S-20260815-23456789AB"},
        vehicles=[
            {"role": "veiculo_eletrico", "marca": "BYD", "modelo": "Dolphin", "codigo_fipe": "001234-5", "tecnologia": "bev"},
            {"role": "veiculo_combustao", "marca": "Toyota", "modelo": "Yaris", "codigo_fipe": "009876-5", "tecnologia": "icev"},
        ],
        simulation_uf="GO",
        simulation_city="Goiânia",
        horizon_years=5,
        km_year=15000,
        analysis_type="tco",
    )
    detail = service.get_event_detail(event_id)
    assert detail is not None
    assert detail["visitor"]
    assert detail["session"]
    assert detail["network"] == "abcdeffedcba"
    assert detail["access_city"] == "Goiânia"
    assert detail["access_region"] == "GO"
    assert detail["browser"] == "Chrome"
    assert detail["device"] == "desktop"
    assert detail["os"] == "Windows"
    assert detail["result_code"] == "S-20260815-23456789AB"
    assert [v["codigo_fipe"] for v in detail["vehicles"]] == ["001234-5", "009876-5"]


def test_compact_snapshot_admin_summary_is_read_only_and_has_tco_core_values():
    record = {
        "code": "S-20260815-23456789AB",
        "result_type": "S",
        "module": "tco",
        "created_at_local": "2026-08-15T22:15:00-03:00",
        "schema_version": "curve-result-snapshot-v1",
        "platform_version": "V50.15",
        "payload_sha256": "a" * 64,
        "payload_bytes": 1234,
        "snapshot": {
            "payload": {
                "entrada": {"anos": "5", "km_ano": "15000"},
                "veiculos": [
                    {"role": "veiculo_eletrico", "modelo": "Dolphin", "codigo_fipe": "001234-5"},
                    {"role": "veiculo_combustao", "modelo": "Yaris", "codigo_fipe": "009876-5"},
                ],
                "resultado": {
                    "comparacoes": [{
                        "titulo": "Dolphin × Yaris",
                        "detalhes": [
                            {"nome": "Dolphin", "codigo_fipe": "001234-5", "tco_final": "R$ 84.117,58", "custo_km": "R$ 1,12"},
                            {"nome": "Yaris", "codigo_fipe": "009876-5", "tco_final": "R$ 102.143,34", "custo_km": "R$ 1,36"},
                        ],
                    }]
                },
            }
        },
    }
    summary = build_result_admin_summary(record)
    assert summary["code"] == "S-20260815-23456789AB"
    assert summary["created_at_display"] == "15/08/2026 às 22:15"
    assert summary["comparisons"][0]["detalhes"][0]["tco_final"] == "R$ 84.117,58"
    assert summary["comparisons"][0]["detalhes"][1]["codigo_fipe"] == "009876-5"


def test_admin_activity_list_and_modal_exist_and_do_not_expose_raw_ip():
    html = read("templates/admin_usage.html")
    js = read("static/js/admin_usage.js")
    css = read("static/css/admin_usage.css")
    routes = read("routes/usage_routes.py")

    assert "Atividades / Pesquisas" in html
    assert 'id="admin_activities_body"' in html
    assert "Pesquisa / veículo" in html
    assert 'id="admin_activity_modal"' in html
    assert 'id="admin_activity_modal_body"' in html
    assert "openActivityModal" in js
    assert "/api/site-usage/admin/telemetry/events/${encodeURIComponent(eventId)}" in js
    assert "Abrir resultado histórico" in js
    assert "Hash de rede" in js
    assert "IP bruto" not in js
    assert ".admin-modal-card" in css
    assert '@usage_bp.route("/api/site-usage/admin/telemetry/events/<int:event_id>"' in routes
    assert "build_result_admin_summary(stored)" in routes


def test_historical_result_open_is_recorded_as_meaningful_activity():
    source = read("routes/main_routes.py")
    tracking = read("services/site_usage_tracking.py")
    assert 'module="resultado"' in source
    assert 'action="historical_result_opened"' in source
    assert '"resultado_codigo": codigo' in source
    # Continua sem armazenar IP bruto: a camada de tracking só deriva hash de rede.
    assert '"network_hash": _network_hash(_client_ip())' in tracking
