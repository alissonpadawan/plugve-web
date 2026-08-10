import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SeguroIntegracaoV50_04Tests(unittest.TestCase):
    def test_no_fixed_47_runtime(self):
        files = [
            ROOT / "routes" / "tco_routes.py",
            ROOT / "templates" / "simular.html",
            ROOT / "services" / "seguro_autoseg_service.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("0.047", text)
            self.assertNotIn("SEGURO_PADRAO_PERCENTUAL", text)
            self.assertNotIn("PERCENTUAL_SEGURO_PADRAO", text)

    def test_app_registers_local_autoseg_blueprint(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("from routes.seguro_routes import seguro_bp", text)
        self.assertIn('app.register_blueprint(seguro_bp, url_prefix="/api/seguro")', text)

    def test_frontend_uses_endpoint_and_keeps_manual_override(self):
        text = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('/api/seguro/estimar', text)
        self.assertIn('seguro_ve_manual', text)
        self.assertIn('seguro_icev_manual', text)
        self.assertIn('Estimativa SUSEP/AUTOSEG', text)
        self.assertIn('Valor informado pelo usuário.', text)

    def test_projection_keeps_rate_relative_to_projected_market_value(self):
        path = ROOT / "routes" / "tco_routes.py"
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "calcular_projecao_veiculo")
        body = ast.get_source_segment(text, fn) or ""
        self.assertIn("taxa_seguro = taxa_relativa(seguro_inicial, preco)", body)
        self.assertIn("seguro_ano = valor_mercado * taxa_seguro", body)
        self.assertIn('"seguro_lista": seguro_lista', body)

    def test_service_has_no_authorial_age_or_value_factors(self):
        text = (ROOT / "services" / "seguro_autoseg_service.py").read_text(encoding="utf-8")
        self.assertNotIn("TAXAS_POR_VALOR", text)
        self.assertNotIn("FATORES_IDADE", text)
        self.assertNotIn("FATORES_REGIAO", text)
        self.assertIn('taxa_calculada = premio / is_media', text)


if __name__ == "__main__":
    unittest.main()
