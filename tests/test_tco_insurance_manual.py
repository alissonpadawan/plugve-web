import ast
import json
import unittest
from pathlib import Path
from unittest.mock import Mock


class TcoInsuranceManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "routes" / "tco_routes.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        wanted = {
            "conv",
            "_flag_formulario_ativo",
            "_valor_seguro_manual_legado",
            "_serie_seguro_json",
            "_normalizar_serie_seguro",
            "extrair_seguro_formulario",
        }
        selected = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
        ]
        namespace = {"json": json}
        cls.service = Mock()
        cls.service.get_by_id.return_value = None
        namespace["get_seguro_service"] = lambda: cls.service
        module = ast.Module(body=selected, type_ignores=[])
        exec(compile(module, str(source_path), "exec"), namespace)
        cls.extract = staticmethod(namespace["extrair_seguro_formulario"])

    def setUp(self):
        self.service.reset_mock()
        self.service.get_by_id.return_value = None

    def test_blank_insurance_has_no_hidden_default(self):
        seguro = self.extract({"anos": "3", "seguro_ve": "", "seguro_ve_serie": ""}, "ve")
        self.assertEqual(seguro["serie_anual"], [0.0, 0.0, 0.0])
        self.assertEqual(seguro["origem"], "indisponivel")
        self.assertFalse(seguro["completa"])

    def test_manual_annual_series_is_preserved(self):
        dados = {
            "anos": "3",
            "seguro_icev": "4000",
            "seguro_icev_serie": json.dumps([4000, 4250.50, 4520]),
            "seguro_icev_origem": "manual",
        }
        seguro = self.extract(dados, "icev")
        self.assertEqual(seguro["serie_anual"], [4000.0, 4250.5, 4520.0])
        self.assertEqual(seguro["origem"], "manual")
        self.assertTrue(seguro["completa"])

    def test_partial_manual_series_is_zero_filled_and_marked_incomplete(self):
        seguro = self.extract(
            {
                "anos": "4",
                "seguro_atual_serie": json.dumps([3100, 3200]),
                "seguro_atual_origem": "manual",
            },
            "atual",
        )
        self.assertEqual(seguro["serie_anual"], [3100.0, 3200.0, 0.0, 0.0])
        self.assertFalse(seguro["completa"])

    def test_invalid_external_token_does_not_trust_posted_origin(self):
        dados = {
            "anos": "2",
            "seguro_ve": "5000",
            "seguro_ve_serie": json.dumps([5000, 5100]),
            "seguro_ve_origem": "externa_basica",
            "seguro_ve_estimate_id": "token-inexistente",
        }
        seguro = self.extract(dados, "ve")
        self.service.get_by_id.assert_called_once_with("token-inexistente")
        self.assertEqual(seguro["origem"], "manual")
        self.assertEqual(seguro["estimate_id"], "")

    def test_legacy_explicit_value_is_manual_not_percentage_default(self):
        seguro = self.extract({"anos": "2", "seguro_ve": "4700", "seguro_ve_serie": ""}, "ve")
        self.assertEqual(seguro["serie_anual"], [4700.0, 4700.0])
        self.assertEqual(seguro["origem"], "manual_constante_legado")


if __name__ == "__main__":
    unittest.main()
