import ast
import unittest
from typing import Any, Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V47InsuranceExternalTests(unittest.TestCase):
    def test_fixed_percentage_was_removed_from_runtime_files(self):
        files = [
            ROOT / "routes" / "tco_routes.py",
            ROOT / "templates" / "simular.html",
            ROOT / "services" / "seguro_service.py",
        ]
        forbidden = ("0.047", "PERCENTUAL_SEGURO_PADRAO", "SEGURO_PADRAO_PERCENTUAL")
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} ainda aparece em {path}")

    def test_projection_uses_exact_annual_series_not_fipe_percentage(self):
        text = (ROOT / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "calcular_projecao_veiculo"
        )
        body = ast.get_source_segment(text, function) or ""
        self.assertIn("seguro_ano = seguro_serie[ano - 1]", body)
        self.assertNotIn("seguro_ano = valor_mercado * taxa_seguro", body)
        self.assertIn('"seguro_lista": seguro_lista', body)

    def test_external_endpoint_has_explicit_unconfigured_failure(self):
        route = (ROOT / "routes" / "seguro_routes.py").read_text(encoding="utf-8")
        service = (ROOT / "services" / "seguro_service.py").read_text(encoding="utf-8")
        self.assertIn('@seguro_bp.post("/estimar")', route)
        self.assertIn("except SeguroConfiguracaoError", route)
        self.assertIn("status = 503", route)
        self.assertIn("A fonte externa de seguro ainda não está configurada", service)
        self.assertNotIn("fallback_percentual", service)

    def test_generic_provider_parser_accepts_series_and_filters_profile(self):
        path = ROOT / "services" / "seguro_service.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        wanted = {"_float_value", "_find_key", "_parse_series_item", "_parse_series", "_sanitize_profile"}
        selected = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in wanted
        ]
        namespace = {"Any": Any, "Iterable": Iterable}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
        parsed = namespace["_parse_series"]({"data": {"annual_series": [4100, "4.280,50", {"premium": 4515}]}})
        profile = namespace["_sanitize_profile"]({
            "faixa_etaria": "36_55",
            "tipo_uso": "particular",
            "telefone": "não deve sair",
            "cpf": "não deve sair",
        })
        self.assertEqual(parsed, [4100.0, 4280.5, 4515.0])
        self.assertEqual(profile, {"faixa_etaria": "36_55", "tipo_uso": "particular"})

    def test_template_has_modal_annual_series_and_no_monthly_mode(self):
        text = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('id="modal_seguro_tco"', text)
        self.assertIn('/api/seguro/estimar', text)
        self.assertIn('seguro_ve_serie', text)
        self.assertIn('Seguro anual estimado', text)
        self.assertNotIn('Seguro mensal', text)
        self.assertNotIn('valor mensal', text.lower())

    def test_app_registers_insurance_blueprint(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("from routes.seguro_routes import seguro_bp", text)
        self.assertIn('app.register_blueprint(seguro_bp, url_prefix="/api/seguro")', text)


if __name__ == "__main__":
    unittest.main()
