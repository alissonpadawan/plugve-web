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


class AdminUsageServiceV5007Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = SiteUsageService(Path(self.tempdir.name) / "usage.sqlite3")
        self.ctx_go = {
            "network_hash": "network-go",
            "city": "Goiânia",
            "region": "GO",
            "country": "BR",
            "browser_family": "Chrome",
            "device_type": "desktop",
            "os_family": "Windows",
            "path": "/simular",
        }
        self.ctx_sp = {
            "network_hash": "network-sp",
            "city": "São Paulo",
            "region": "SP",
            "country": "BR",
            "browser_family": "Safari",
            "device_type": "mobile",
            "os_family": "iOS",
            "path": "/consulta-fipe",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed(self):
        self.service.record_event(
            visitor_id="visitor-go", session_id="session-go", event_type="analysis",
            module="tco", action="simulation_completed", request_context=self.ctx_go,
            simulation_uf="GO", simulation_city="Goiânia", horizon_years=5, km_year=15000,
            vehicles=[
                {"role": "ve", "vehicle_key": "byd-dolphin", "marca": "BYD", "modelo": "Dolphin", "tecnologia": "ve"},
                {"role": "icev", "vehicle_key": "toyota-yaris", "marca": "Toyota", "modelo": "Yaris", "tecnologia": "icev"},
            ], analysis_type="tco",
        )
        self.service.record_event(
            visitor_id="visitor-sp", session_id="session-sp", event_type="analysis",
            module="fipe_plus", action="consultation_completed", request_context=self.ctx_sp,
            vehicles=[{"vehicle_key": "byd-dolphin", "marca": "BYD", "modelo": "Dolphin", "tecnologia": "ve"}],
            analysis_type="fipe_plus",
        )
        self.service.record_event(
            visitor_id="visitor-go", session_id="session-go", event_type="analysis",
            module="depreciacao", action="consultation_completed", request_context={**self.ctx_go, "path": "/depreciacao"},
            vehicles=[{"vehicle_key": "byd-dolphin", "marca": "BYD", "modelo": "Dolphin", "tecnologia": "ve"}],
            analysis_type="depreciacao",
        )

    def test_summary_exposes_rankings_technologies_and_access_locations(self):
        self._seed()
        summary = self.service.telemetry_summary()
        self.assertEqual(summary["counts"]["visitors"], 2)
        self.assertEqual(summary["counts"]["tco_simulations"], 1)
        self.assertTrue(any(item["city"] == "Goiânia" and item["region"] == "GO" for item in summary["access_locations"]))
        self.assertTrue(any(item["technology"] == "ve" for item in summary["technology_usage"]))
        self.assertTrue(any(item["marca"] == "BYD" for item in summary["top_brands"]))
        self.assertEqual(summary["top_pairs"][0]["vehicle_1"]["modelo"], "Dolphin")
        self.assertEqual(summary["top_pairs"][0]["vehicle_2"]["modelo"], "Yaris")

    def test_depreciation_curve_type_breakdown_is_explicit(self):
        self.service.record_event(
            visitor_id="visitor-go", session_id="session-go", event_type="analysis",
            module="depreciacao", action="consultation_completed", request_context=self.ctx_go,
            metadata={"tipo_curva": "propria", "origem_curva": "curva própria salva"},
            analysis_type="depreciacao",
        )
        self.service.record_event(
            visitor_id="visitor-sp", session_id="session-sp", event_type="analysis",
            module="depreciacao", action="consultation_completed", request_context=self.ctx_sp,
            metadata={"tipo_curva": "similaridade", "origem_curva": "Curva herdada por similaridade manual"},
            analysis_type="depreciacao",
        )
        breakdown = self.service.telemetry_summary()["depreciation_curve_types"]
        self.assertEqual(breakdown["propria"], 1)
        self.assertEqual(breakdown["similaridade"], 1)
        self.assertEqual(breakdown["nao_informado"], 0)

    def test_daily_buckets_respect_admin_timezone_offset(self):
        event_id = self.service.record_event(
            visitor_id="visitor-go", session_id="session-go", event_type="analysis",
            module="tco", action="simulation_completed", request_context=self.ctx_go,
            analysis_type="tco",
        )
        # 02:30 UTC de 10/08 ainda é 23:30 de 09/08 em UTC-3.
        with self.service._connection() as connection:
            connection.execute(
                "UPDATE usage_events SET occurred_at = ? WHERE id = ?",
                ("2026-08-10T02:30:00+00:00", event_id),
            )
        summary = self.service.telemetry_summary(
            start="2026-08-09T03:00:00Z",
            end="2026-08-10T02:59:59.999Z",
            tz_offset_minutes=-180,
        )
        self.assertEqual(summary["counts"]["events"], 1)
        self.assertEqual(summary["daily"][0]["day"], "2026-08-09")
        self.assertEqual(summary["timezone_offset_minutes"], -180)

    def test_events_include_coarse_access_context_but_not_raw_ip(self):
        self._seed()
        event = self.service.list_events(module="tco")["events"][0]
        self.assertEqual(event["access_city"], "Goiânia")
        self.assertEqual(event["access_region"], "GO")
        self.assertEqual(event["browser"], "Chrome")
        self.assertEqual(event["device"], "desktop")
        self.assertNotIn("ip", event)

    def test_period_visitors_are_selected_by_events_in_period(self):
        self._seed()
        today = self.service.list_events()["events"][0]["occurred_at"][:10]
        visitors = self.service.list_visitors(start=today, end=today)
        self.assertEqual(visitors["total"], 2)
        self.assertTrue(all(item["period_events"] >= 1 for item in visitors["visitors"]))
        self.assertTrue(all(item["period_sessions"] >= 1 for item in visitors["visitors"]))
        empty = self.service.list_visitors(start="2000-01-01", end="2000-01-02")
        self.assertEqual(empty["total"], 0)


@unittest.skipIf(create_app is None, "Flask indisponível no ambiente de validação")
class AdminUsageRoutesV5007Tests(unittest.TestCase):
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

    def test_admin_page_is_noindex_and_apis_remain_protected(self):
        page = self.client.get("/admin/uso")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertIn(b"Painel de uso e tend", page.data)
        self.assertEqual(self.client.get("/api/site-usage/admin/telemetry/summary").status_code, 401)


class AdminUsageInterfaceV5007Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_dashboard_has_filters_rankings_visitors_and_activity(self):
        html = (self.root / "templates" / "admin_usage.html").read_text(encoding="utf-8")
        self.assertIn('data-preset="today"', html)
        self.assertIn('data-preset="30d"', html)
        self.assertIn('id="admin_top_vehicles"', html)
        self.assertIn('id="admin_top_pairs"', html)
        self.assertIn('id="admin_visitors_body"', html)
        self.assertIn('id="admin_events_feed"', html)
        self.assertIn('id="admin_depreciation_curve_types"', html)
        self.assertIn("IP bruto não armazenado", html)

    def test_token_stays_in_session_storage_and_is_sent_as_header(self):
        js = (self.root / "static" / "js" / "admin_usage.js").read_text(encoding="utf-8")
        self.assertIn('sessionStorage.setItem(TOKEN_KEY, token)', js)
        self.assertIn('"X-PlugVE-Admin-Token": state.token', js)
        self.assertNotIn("localStorage.setItem(TOKEN_KEY", js)
        self.assertIn("/api/site-usage/admin/telemetry/visitors", js)
        self.assertIn("/api/site-usage/admin/telemetry/events", js)

    def test_admin_page_is_not_added_to_public_navigation(self):
        base = (self.root / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertNotIn('/admin/uso', base)

    def test_dashboard_converts_local_dates_to_utc_boundaries(self):
        js = (self.root / "static" / "js" / "admin_usage.js").read_text(encoding="utf-8")
        self.assertIn("localDateBoundaryIso", js)
        self.assertIn("toISOString()", js)
        self.assertIn('params.set("tz_offset_minutes"', js)

    def test_depreciation_pdf_event_is_after_valid_result_check(self):
        js = (self.root / "static" / "js" / "depreciacao.js").read_text(encoding="utf-8")
        start = js.index("function exportarPDFDepreciacao()")
        end = js.index("function abrirAuditoriaDepreciacao()", start)
        bloco = js[start:end]
        self.assertLess(bloco.index("if (!ultimoResumoDepreciacao"), bloco.index("registrarEventoUsoDepreciacao('pdf_exported')"))

    def test_admin_and_sync_credentials_are_separated_by_route_role(self):
        usage = (self.root / "routes" / "usage_routes.py").read_text(encoding="utf-8")
        tco = (self.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        dep = (self.root / "routes" / "depreciacao_routes.py").read_text(encoding="utf-8")
        fipe = (self.root / "routes" / "fipe_routes.py").read_text(encoding="utf-8")
        self.assertIn('current_app.config.get("PLUGVE_ADMIN_TOKEN"', usage)
        self.assertNotIn('current_app.config.get("PLUGVE_SYNC_TOKEN"', usage)
        admin_auth = tco[tco.index("def _sobre_admin_token_recebido"):tco.index("def _sobre_admin_unauthorized")]
        self.assertIn('current_app.config.get("PLUGVE_ADMIN_TOKEN"', admin_auth)
        self.assertNotIn('PLUGVE_SYNC_TOKEN', admin_auth)
        for source in (dep, fipe):
            auth = source[source.index("def _sync_token_recebido"):source.index("def _erro", source.index("def _sync_token_recebido"))] if "def _erro" in source[source.index("def _sync_token_recebido"):] else source[source.index("def _sync_token_recebido"):source.index("@", source.index("def _sync_token_recebido"))]
            self.assertIn('current_app.config.get("PLUGVE_SYNC_TOKEN"', auth)
            self.assertNotIn('PLUGVE_ADMIN_TOKEN', auth)

    def test_deployment_files_do_not_embed_admin_or_sync_secrets(self):
        render = (self.root / "render.yaml").read_text(encoding="utf-8")
        env_example = (self.root / ".env.example").read_text(encoding="utf-8")
        config = (self.root / "config.py").read_text(encoding="utf-8")
        self.assertNotRegex(render, r"(?s)key: PLUGVE_(?:ADMIN|SYNC)_TOKEN\s*\n\s*value:")
        self.assertIn("sync: false", render)
        self.assertIn("generateValue: true", render)
        self.assertNotIn("PLUGVE_ADMIN_TOKEN = os.environ.get(\"PLUGVE_ADMIN_TOKEN\", PLUGVE_SYNC_TOKEN)", config)
        self.assertIn("gere_outro_token_exclusivo_para_o_admin", env_example)


if __name__ == "__main__":
    unittest.main()
