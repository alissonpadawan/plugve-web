from __future__ import annotations

import sqlite3
from pathlib import Path

from services.result_snapshot_service import ResultSnapshotService
from services.site_usage_service import SiteUsageService


def _vehicle(role: str, marca: str, modelo: str, fipe: str, tech: str) -> dict:
    return {
        "role": role,
        "marca": marca,
        "modelo": modelo,
        "codigo_fipe": fipe,
        "technology": tech,
    }


def test_v5134_usage_migration_keeps_legacy_user_null_and_tags_new_events(tmp_path: Path):
    db = tmp_path / "usage.sqlite3"
    service = SiteUsageService(db)
    service.record_event(
        visitor_id="legacy-v", session_id="legacy-s",
        event_type="page_view", module="home", action="page_view",
    )
    service.record_event(
        visitor_id="user-v", session_id="user-s", user_id="user-uuid-1",
        event_type="auth", module="auth", action="login",
    )
    with sqlite3.connect(db) as con:
        cols_events = {row[1] for row in con.execute("PRAGMA table_info(usage_events)")}
        cols_sessions = {row[1] for row in con.execute("PRAGMA table_info(usage_sessions)")}
        assert "user_id" in cols_events
        assert "user_id" in cols_sessions
        rows = con.execute("SELECT action, user_id FROM usage_events ORDER BY id").fetchall()
    assert rows[0] == ("page_view", None)
    assert rows[1] == ("login", "user-uuid-1")


def test_v5134_user_activity_summary(tmp_path: Path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    uid = "user-uuid-joao"
    common = dict(visitor_id="v1", session_id="s1", user_id=uid)
    service.record_event(**common, event_type="auth", module="auth", action="login")
    service.record_event(
        **common, event_type="analysis", module="tco", action="simulation_completed",
        simulation_uf="GO", simulation_city="Goiânia", analysis_type="tco",
        metadata={"resultado_codigo": "S-20260918-23456789AB"},
        vehicles=[
            _vehicle("veiculo_eletrico", "BYD", "Dolphin", "095012-2", "bev"),
            _vehicle("veiculo_combustao", "Toyota", "Yaris", "002180-6", "icev"),
        ],
    )
    service.record_event(
        **common, event_type="analysis", module="fipe_plus", action="consultation_completed",
        analysis_type="fipe_plus", metadata={"resultado_codigo": "F-20260918-23456789AC"},
        vehicles=[_vehicle("consultado", "BYD", "Dolphin", "095012-2", "bev")],
    )
    service.record_event(
        **common, event_type="analysis", module="depreciacao", action="consultation_completed",
        analysis_type="depreciacao", metadata={"resultado_codigo": "D-20260918-23456789AD"},
        vehicles=[_vehicle("consultado", "BYD", "Dolphin", "095012-2", "bev")],
    )
    service.record_event(
        **common, event_type="export", module="tco", action="pdf_exported",
        metadata={"resultado_codigo": "S-20260918-23456789AB"},
    )
    service.record_event(
        **common, event_type="interaction", module="resultado", action="historical_result_opened",
        metadata={"resultado_codigo": "S-20260918-23456789AB"},
    )
    service.submit_curve_request(visitor_id="v1", user_id=uid, payload={
        "tipo": "carros", "codigo_fipe": "095012-2", "codigo_ano": "2025-1",
        "marca": "BYD", "modelo": "Dolphin",
    })

    data = service.get_user_activity_summary(uid)
    metrics = data["metrics"]
    assert metrics["sessions"] == 1
    assert metrics["events"] == 6
    assert metrics["logins"] == 1
    assert metrics["tco"] == 1
    assert metrics["fipe_plus"] == 1
    assert metrics["depreciation"] == 1
    assert metrics["pdf_exports"] == 1
    assert metrics["historical_opens"] == 1
    assert metrics["curve_requests"] == 1
    assert (metrics["results_s"], metrics["results_d"], metrics["results_f"]) == (1, 1, 1)
    assert data["top_vehicles"][0]["modelo"] == "Dolphin"
    assert data["top_vehicles"][0]["uses"] == 3
    assert data["top_pairs"][0]["uses"] == 1
    assert data["simulation_cities"][0]["city"] == "Goiânia"
    assert data["timeline"][0]["user_id"] == uid


def test_v5134_snapshot_owner_is_optional_and_legacy_safe(tmp_path: Path):
    db = tmp_path / "snapshots.sqlite3"
    service = ResultSnapshotService(db, "V51.34")
    legacy = service.create_snapshot(result_type="D", module="depreciacao", payload={"legacy": True})
    owned = service.create_snapshot(
        result_type="S", module="tco", payload={"new": True}, owner_user_id="user-uuid-1"
    )
    assert service.get_snapshot(legacy["code"])["owner_user_id"] == ""
    assert service.get_snapshot(owned["code"])["owner_user_id"] == "user-uuid-1"


def test_v5134_static_integration_contracts():
    root = Path(__file__).resolve().parents[1]
    tracking = (root / "services" / "site_usage_tracking.py").read_text(encoding="utf-8")
    main = (root / "routes" / "main_routes.py").read_text(encoding="utf-8")
    admin = (root / "services" / "auth_admin_service.py").read_text(encoding="utf-8")
    privacy = (root / "templates" / "auth" / "privacy.html").read_text(encoding="utf-8")
    assert 'resolved_user_id = str(user_id or "").strip()' in tracking
    assert 'requester_user_id != owner_user_id' in main
    assert '"usage": self.usage.get_user_activity_summary' in admin
    assert "novas atividades também são associadas ao identificador interno da conta" in privacy
