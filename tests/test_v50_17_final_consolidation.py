from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from services.site_usage_service import SiteUsageService

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _tco_event(service: SiteUsageService, *, visitor="visitor-a", session="session-a", city="Goiânia", region="GO", browser="Chrome", device="desktop", os_family="Windows", code="S-20260815-23456789AB"):
    return service.record_event(
        visitor_id=visitor,
        session_id=session,
        event_type="analysis",
        module="tco",
        action="simulation_completed",
        request_context={
            "network_hash": "network-a",
            "city": city,
            "region": region,
            "country": "BR",
            "browser_family": browser,
            "device_type": device,
            "os_family": os_family,
            "path": "/simular",
        },
        metadata={"resultado_codigo": code},
        vehicles=[
            {"role": "ve", "marca": "BYD", "modelo": "Dolphin", "codigo_fipe": "001234-5", "tecnologia": "BEV"},
            {"role": "icev", "marca": "Toyota", "modelo": "Yaris", "codigo_fipe": "009876-5", "tecnologia": "ICEV"},
        ],
        simulation_uf="GO",
        simulation_city="Goiânia",
        horizon_years=5,
        km_year=15000,
        analysis_type="tco",
    )


def test_completion_event_is_idempotent_by_snapshot_code(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    first = _tco_event(service)
    second = _tco_event(service, city="São Paulo", region="SP", browser="Safari", device="mobile", os_family="iOS")

    assert second == first
    summary = service.telemetry_summary()
    assert summary["counts"]["tco_simulations"] == 1
    assert summary["counts"]["researches"] == 1
    assert summary["counts"]["events"] == 1
    assert service.get_analysis_counts()["tco"] == 1

    # Ações que são realmente repetíveis continuam sendo contadas.
    for _ in range(2):
        service.record_event(
            visitor_id="visitor-a", session_id="session-a", event_type="export",
            module="tco", action="pdf_exported", request_context={"path": "/simular"},
            metadata={"resultado_codigo": "S-20260815-23456789AB"},
        )
    assert service.telemetry_summary()["counts"]["pdf_exports"] == 2


def test_event_keeps_access_context_frozen_even_if_session_changes(tmp_path):
    db = tmp_path / "usage.sqlite3"
    service = SiteUsageService(db)
    event_id = _tco_event(service)

    # Simula enriquecimento/alteração posterior da sessão e do visitante.
    with sqlite3.connect(db) as con:
        con.execute("UPDATE usage_sessions SET city='São Paulo', region='SP', browser_family='Safari', device_type='mobile', os_family='iOS', network_hash='network-new'")
        con.execute("UPDATE usage_visitors SET city='São Paulo', region='SP', browser_family='Safari', device_type='mobile', os_family='iOS', network_hash='network-new'")
        con.commit()

    detail = service.get_event_detail(event_id)
    assert detail is not None
    assert detail["access_city"] == "Goiânia"
    assert detail["access_region"] == "GO"
    assert detail["browser"] == "Chrome"
    assert detail["device"] == "desktop"
    assert detail["os"] == "Windows"
    assert detail["network"] == "network-a"[:12]

    assert service.telemetry_summary(access_location="Goiânia")["counts"]["researches"] == 1
    assert service.telemetry_summary(access_location="São Paulo")["counts"]["researches"] == 0
    visitors = service.list_visitors(access_location="Goiânia")["visitors"]
    assert visitors[0]["city"] == "Goiânia"
    assert visitors[0]["region"] == "GO"
    assert visitors[0]["browser"] == "Chrome"


def test_result_code_has_explicit_column_and_filter(tmp_path):
    service = SiteUsageService(tmp_path / "usage.sqlite3")
    _tco_event(service)
    with service._connection() as con:  # teste estrutural local
        row = con.execute("SELECT result_code FROM usage_events").fetchone()
        indexes = {r[1] for r in con.execute("PRAGMA index_list(usage_events)").fetchall()}
    assert row["result_code"] == "S-20260815-23456789AB"
    assert "idx_usage_events_result_code_when" in indexes
    assert service.telemetry_summary(result_code="S-20260815")["counts"]["researches"] == 1


def test_legacy_database_migrates_context_and_result_code_without_losing_event(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as con:
        con.executescript(
            """
            CREATE TABLE usage_visitors (
                visitor_hash TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                session_count INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
                page_view_count INTEGER NOT NULL DEFAULT 0, network_hash TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',
                browser_family TEXT NOT NULL DEFAULT '', device_type TEXT NOT NULL DEFAULT '', os_family TEXT NOT NULL DEFAULT '',
                first_referrer_host TEXT NOT NULL DEFAULT '', last_path TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE usage_sessions (
                session_hash TEXT PRIMARY KEY, visitor_hash TEXT NOT NULL, started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                event_count INTEGER NOT NULL DEFAULT 0, network_hash TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '', browser_family TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT '', os_family TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_hash TEXT NOT NULL, session_hash TEXT NOT NULL,
                occurred_at TEXT NOT NULL, event_type TEXT NOT NULL, module TEXT NOT NULL, action TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '', simulation_uf TEXT NOT NULL DEFAULT '', simulation_city TEXT NOT NULL DEFAULT '',
                horizon_years INTEGER, km_year INTEGER, metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        con.execute(
            "INSERT INTO usage_visitors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("vh", "2026-08-15T10:00:00+00:00", "2026-08-15T10:00:00+00:00", 1, 1, 0, "net", "Goiânia", "GO", "BR", "Chrome", "desktop", "Windows", "", "/simular"),
        )
        con.execute(
            "INSERT INTO usage_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("sh", "vh", "2026-08-15T10:00:00+00:00", "2026-08-15T10:00:00+00:00", 1, "net", "Goiânia", "GO", "BR", "Chrome", "desktop", "Windows"),
        )
        con.execute(
            "INSERT INTO usage_events(visitor_hash,session_hash,occurred_at,event_type,module,action,path,metadata_json) VALUES (?,?,?,?,?,?,?,?)",
            ("vh", "sh", "2026-08-15T10:00:00+00:00", "analysis", "tco", "simulation_completed", "/simular", json.dumps({"resultado_codigo": "S-20260815-23456789AB"}, separators=(",", ":"))),
        )
        con.commit()

    service = SiteUsageService(db)
    with service._connection() as con:
        columns = {r["name"] for r in con.execute("PRAGMA table_info(usage_events)").fetchall()}
        row = con.execute("SELECT * FROM usage_events WHERE id=1").fetchone()
    for field in ("result_code", "access_network", "access_city", "access_region", "access_country", "access_browser", "access_device", "access_os"):
        assert field in columns
    assert row["result_code"] == "S-20260815-23456789AB"
    assert row["access_city"] == "Goiânia"
    assert row["access_region"] == "GO"
    assert row["access_browser"] == "Chrome"
    assert service.telemetry_summary()["counts"]["events"] == 1


def test_v5017_mobile_admin_and_version_markers():
    html = read("templates/admin_usage.html")
    css = read("static/css/admin_usage.css")
    js = read("static/js/admin_usage.js")
    service = read("services/site_usage_service.py")
    config = read("config.py")

    assert 'CURVE_VERSION = "V50.25"' in config
    assert "Inteligência V50.17" in html
    assert "20260815_v50_17" in html
    assert html.count("admin-mobile-cards") >= 2
    assert "@media(max-width:640px)" in css
    assert "content:attr(data-label)" in css
    assert 'data-label="Pesquisa / veículo"' in js
    assert "RESULT_COMPLETION_ACTIONS" in service
    assert "access_city TEXT NOT NULL DEFAULT ''" in service
    assert "idx_usage_events_result_code_when" in service
