import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("PLUGVE_PREWARM_FIPE", "0")

try:
    from app import create_app
except (ModuleNotFoundError, ImportError) as exc:
    if getattr(exc, "name", None) == "flask" or "Flask" in str(exc):
        create_app = None
    else:
        raise
from services.site_usage_service import SiteUsageService


class UsageTelemetryServiceV5006Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "telemetry.sqlite3"
        self.service = SiteUsageService(self.db)
        self.ctx = {
            "network_hash": "abc123network",
            "city": "Goiânia",
            "region": "GO",
            "country": "BR",
            "browser_family": "Chrome",
            "device_type": "desktop",
            "os_family": "Windows",
            "referrer_host": "google.com",
            "path": "/simular",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def test_records_visitors_sessions_events_and_vehicles(self):
        vehicle1 = {"role": "ve", "codigo_modelo": "12124", "marca": "BYD", "modelo": "Dolphin Mini GS", "ano_modelo": "2026", "tecnologia": "ve"}
        vehicle2 = {"role": "icev", "codigo_modelo": "999", "marca": "Toyota", "modelo": "Yaris", "ano_modelo": "2026", "tecnologia": "icev"}
        self.service.record_event(
            visitor_id="browser-a", session_id="session-1", event_type="analysis", module="tco",
            action="simulation_completed", request_context=self.ctx, vehicles=[vehicle1, vehicle2],
            simulation_uf="GO", simulation_city="Goiânia", horizon_years=5, km_year=15000,
            metadata={"tipo_comparacao": "dois_carros_novos"}, analysis_type="tco",
        )
        self.service.record_event(
            visitor_id="browser-a", session_id="session-1", event_type="page_view", module="home",
            action="page_view", request_context={**self.ctx, "path": "/"},
        )
        self.service.record_event(
            visitor_id="browser-a", session_id="session-2", event_type="page_view", module="fipe_plus",
            action="page_view", request_context={**self.ctx, "path": "/consulta-fipe"},
        )
        summary = self.service.telemetry_summary()
        self.assertEqual(summary["counts"]["visitors"], 1)
        self.assertEqual(summary["counts"]["sessions"], 2)
        self.assertEqual(summary["counts"]["tco_simulations"], 1)
        self.assertEqual(summary["counts"]["page_views"], 2)
        self.assertEqual(summary["top_pairs"][0]["vehicle_1"]["modelo"], "Dolphin Mini GS")
        self.assertEqual(summary["top_pairs"][0]["vehicle_2"]["modelo"], "Yaris")
        self.assertEqual(summary["simulation_locations"][0]["city"], "Goiânia")
        visitors = self.service.list_visitors()["visitors"]
        self.assertEqual(visitors[0]["sessions"], 2)
        self.assertEqual(visitors[0]["city"], "Goiânia")
        events = self.service.list_events(module="tco")["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0]["vehicles"]), 2)
        self.assertEqual(self.service.get_analysis_counts()["tco"], 1)

    def test_date_filters_work_on_event_summary(self):
        self.service.record_event(
            visitor_id="a", session_id="s", event_type="page_view", module="home", action="page_view",
            request_context=self.ctx,
        )
        today = self.service.list_events()["events"][0]["occurred_at"][:10]
        self.assertEqual(self.service.telemetry_summary(start=today, end=today)["counts"]["events"], 1)
        self.assertEqual(self.service.telemetry_summary(start="2000-01-01", end="2000-01-02")["counts"]["events"], 0)


@unittest.skipIf(create_app is None, "Flask indisponível no ambiente de validação")
class UsageTelemetryRoutesV5006Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            ARQUIVO_USO_SITE=Path(self.tempdir.name) / "usage.sqlite3",
            ARQUIVO_SOBRE_ENGAJAMENTO=Path(self.tempdir.name) / "sobre.sqlite3",
            PLUGVE_ADMIN_TOKEN="admin-test",
            PLUGVE_SYNC_TOKEN="admin-test",
            SECRET_KEY="test-secret",
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _csrf(self):
        self.client.get("/consulta-fipe", headers={
            "X-Forwarded-For": "200.100.50.25",
            "X-Geo-City": "Goiânia",
            "X-Geo-Region": "GO",
            "X-Geo-Country": "BR",
            "User-Agent": "Mozilla/5.0 Windows Chrome/149.0",
        })
        with self.client.session_transaction() as sess:
            return sess["site_usage_csrf_token"]

    def test_page_view_and_public_fipe_event_are_pseudonymous(self):
        csrf = self._csrf()
        response = self.client.post(
            "/api/site-usage/event",
            headers={"X-CSRF-Token": csrf, "X-Forwarded-For": "200.100.50.25", "X-Geo-City": "Goiânia"},
            json={
                "module": "fipe_plus",
                "action": "consultation_completed",
                "vehicles": [{"codigo_fipe": "001234-5", "marca": "Teste", "modelo": "Carro Teste", "ano_modelo": "2025"}],
            },
        )
        self.assertEqual(response.status_code, 201)
        headers = {"X-PlugVE-Admin-Token": "admin-test"}
        summary = self.client.get("/api/site-usage/admin/telemetry/summary", headers=headers).get_json()
        self.assertEqual(summary["counts"]["fipe_plus_consultations"], 1)
        self.assertGreaterEqual(summary["counts"]["page_views"], 1)
        visitors = self.client.get("/api/site-usage/admin/telemetry/visitors", headers=headers).get_json()["visitors"]
        self.assertEqual(len(visitors), 1)
        self.assertNotEqual(visitors[0]["network"], "200.100.50.25")
        self.assertNotIn("200.100.50.25", str(visitors[0]))
        self.assertEqual(visitors[0]["city"], "Goiânia")
        events = self.client.get("/api/site-usage/admin/telemetry/events?module=fipe_plus", headers=headers).get_json()["events"]
        self.assertTrue(any(item["action"] == "consultation_completed" for item in events))

    def test_admin_telemetry_requires_token(self):
        self.assertEqual(self.client.get("/api/site-usage/admin/telemetry/summary").status_code, 401)
        self.assertEqual(self.client.get("/api/site-usage/admin/telemetry/events").status_code, 401)
        self.assertEqual(self.client.get("/api/site-usage/admin/telemetry/visitors").status_code, 401)

    def test_sync_header_does_not_authenticate_usage_admin(self):
        self.app.config.update(PLUGVE_ADMIN_TOKEN="admin-test", PLUGVE_SYNC_TOKEN="sync-test")
        response = self.client.get(
            "/api/site-usage/admin/telemetry/summary",
            headers={"X-PlugVE-Sync-Token": "sync-test"},
        )
        self.assertEqual(response.status_code, 401)

    def test_public_event_whitelist_blocks_arbitrary_actions(self):
        csrf = self._csrf()
        response = self.client.post(
            "/api/site-usage/event",
            headers={"X-CSRF-Token": csrf},
            json={"module": "admin", "action": "anything"},
        )
        self.assertEqual(response.status_code, 400)


class UsageTelemetryInterfaceV5006Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_fipe_plus_uses_structured_event_endpoint(self):
        html = (self.root / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
        self.assertIn("/api/site-usage/event", html)
        self.assertIn("action:'consultation_completed'", html)
        self.assertIn("codigo_fipe:data.CodigoFipe", html)

    def test_tco_and_depreciation_record_structured_server_events(self):
        tco = (self.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        dep = (self.root / "routes" / "depreciacao_routes.py").read_text(encoding="utf-8")
        self.assertIn('action="simulation_completed"', tco)
        self.assertIn('action="consultation_completed"', dep)
        self.assertIn('analysis_type="tco"', tco)
        self.assertIn('analysis_type="depreciacao"', dep)


if __name__ == "__main__":
    unittest.main()
