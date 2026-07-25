import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("PLUGVE_PREWARM_FIPE", "0")

try:
    from app import create_app
except ModuleNotFoundError as exc:
    if exc.name == "flask":
        create_app = None
    else:
        raise

from services.site_usage_service import SiteUsageService


class SiteUsageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "usage.sqlite3"
        self.service = SiteUsageService(self.database)
        self.vehicle = {
            "tipo": "combustao",
            "codigo_fipe": "001234-5",
            "codigo_marca": "21",
            "codigo_modelo": "987",
            "codigo_ano": "2024-1",
            "marca": "Marca Teste",
            "modelo": "Modelo Teste 2.0",
            "ano_modelo": "2024",
            "combustivel": "Gasolina",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def test_analysis_counts_are_separate_and_totalized(self):
        self.service.record_analysis("tco")
        self.service.record_analysis("depreciacao", 2)
        self.service.record_analysis("fipe_plus", 3)
        counts = self.service.get_analysis_counts()
        self.assertEqual(counts["tco"], 1)
        self.assertEqual(counts["depreciacao"], 2)
        self.assertEqual(counts["fipe_plus"], 3)
        self.assertEqual(counts["total"], 6)

    def test_curve_requests_group_by_vehicle_and_unique_visitor(self):
        first = self.service.submit_curve_request(visitor_id="browser-a", payload=self.vehicle)
        duplicate = self.service.submit_curve_request(visitor_id="browser-a", payload=self.vehicle)
        second_person = self.service.submit_curve_request(visitor_id="browser-b", payload=self.vehicle)
        self.assertFalse(first["already_requested"])
        self.assertTrue(duplicate["already_requested"])
        self.assertFalse(second_person["already_requested"])

        page = self.service.list_curve_requests()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["requests"][0]["request_count"], 2)
        self.assertEqual(page["requests"][0]["status"], "pending")

    def test_requests_with_same_fipe_are_grouped_across_site_flows(self):
        from_fipe_plus = dict(self.vehicle, tipo="combustao")
        from_depreciation = dict(self.vehicle, tipo="auto")
        self.service.submit_curve_request(visitor_id="browser-a", payload=from_fipe_plus)
        self.service.submit_curve_request(visitor_id="browser-b", payload=from_depreciation)
        page = self.service.list_curve_requests()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["requests"][0]["request_count"], 2)

    def test_new_request_reopens_attended_item(self):
        self.service.submit_curve_request(visitor_id="browser-a", payload=self.vehicle)
        item = self.service.list_curve_requests()["requests"][0]
        updated = self.service.update_curve_request_status(item["id"], "attended")
        self.assertEqual(updated["status"], "attended")
        reopened = self.service.submit_curve_request(visitor_id="browser-b", payload=self.vehicle)
        self.assertTrue(reopened["reopened"])
        current = self.service.list_curve_requests()["requests"][0]
        self.assertEqual(current["status"], "pending")
        self.assertEqual(current["request_count"], 2)


@unittest.skipIf(create_app is None, "Flask indisponível no ambiente de validação")
class SiteUsageRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            ARQUIVO_USO_SITE=Path(self.tempdir.name) / "usage-routes.sqlite3",
            ARQUIVO_SOBRE_ENGAJAMENTO=Path(self.tempdir.name) / "sobre.sqlite3",
            PLUGVE_ADMIN_TOKEN="test-admin-token",
            PLUGVE_SYNC_TOKEN="test-admin-token",
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _csrf(self):
        self.client.get("/consulta-fipe")
        with self.client.session_transaction() as flask_session:
            return flask_session["site_usage_csrf_token"]

    @staticmethod
    def _vehicle():
        return {
            "tipo": "combustao",
            "codigo_fipe": "009999-1",
            "codigo_marca": "10",
            "codigo_modelo": "20",
            "codigo_ano": "2025-1",
            "marca": "Marca Rota",
            "modelo": "Modelo Rota",
            "ano_modelo": "2025",
            "combustivel": "Flex",
        }

    def test_public_analysis_and_about_total(self):
        token = self._csrf()
        response = self.client.post(
            "/api/site-usage/analysis",
            json={"type": "fipe_plus"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total"], 1)
        html = self.client.get("/sobre").get_data(as_text=True)
        self.assertIn("data-analysis-count", html)
        self.assertIn(">1</span>", html)

    def test_request_api_hides_internal_counts_and_admin_can_manage(self):
        token = self._csrf()
        unauthorized = self.client.post("/api/site-usage/curve-requests", json=self._vehicle())
        self.assertEqual(unauthorized.status_code, 403)

        submitted = self.client.post(
            "/api/site-usage/curve-requests",
            json=self._vehicle(),
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(submitted.status_code, 201)
        public_payload = submitted.get_json()
        self.assertTrue(public_payload["ok"])
        self.assertNotIn("request_count", public_payload)
        self.assertNotIn("status", public_payload)

        no_token = self.client.get("/api/site-usage/admin/dashboard")
        self.assertEqual(no_token.status_code, 401)
        headers = {"X-PlugVE-Admin-Token": "test-admin-token"}
        dashboard = self.client.get("/api/site-usage/admin/dashboard", headers=headers)
        self.assertEqual(dashboard.status_code, 200)
        item = dashboard.get_json()["requests"][0]
        self.assertEqual(item["request_count"], 1)
        self.assertEqual(item["status"], "pending")

        changed = self.client.patch(
            f"/api/site-usage/admin/curve-requests/{item['id']}",
            json={"status": "attended"},
            headers=headers,
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["request"]["status"], "attended")


class SiteUsageInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_about_shares_home_and_displays_total_analysis(self):
        html = (self.root / "templates" / "sobre.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "sobre.js").read_text(encoding="utf-8")
        home = (self.root / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("data-analysis-count", html)
        self.assertIn('const canonicalUrl = "https://curveveicular.com.br/";', script)
        self.assertIn('property="og:url" content="https://curveveicular.com.br/"', home)

    def test_request_buttons_exist_only_for_missing_curve_flows(self):
        fipe = (self.root / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
        depr = (self.root / "templates" / "depreciacao.html").read_text(encoding="utf-8")
        depr_js = (self.root / "static" / "js" / "depreciacao.js").read_text(encoding="utf-8")
        self.assertIn("btn_solicitar_curva_fipe_plus", fipe)
        self.assertIn("/api/site-usage/curve-requests", fipe)
        self.assertIn("usage_context: 'fipe_plus'", fipe)
        self.assertIn('id="btn_solicitar_curva"', depr)
        self.assertIn("solicitarCurvaDepreciacao", depr_js)
        simular = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn("solicitarCurvaTCO", simular)
        self.assertIn('modo === "solicitar"', simular)
        self.assertIn('meta name="curve-interaction-csrf"', simular)


if __name__ == "__main__":
    unittest.main()
