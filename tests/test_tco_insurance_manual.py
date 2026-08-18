import ast
import unittest
from pathlib import Path


def _fake_estimator(*, valor_fipe, uf, municipio="", ano_modelo="", tecnologia="gasolina", codigo_fipe=""):
    # Deliberadamente diferente de 4,7% para provar que o runtime não usa o fallback antigo.
    return {"valor_anual": float(valor_fipe) * 0.052, "fonte": "IPSA/TEx + AUTOSEG/SUSEP"}


class TcoInsuranceManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "routes" / "tco_routes.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        wanted = {
            "conv",
            "_flag_formulario_ativo",
            "_prefixo_seguro_campo",
            "_seguro_considerado_formulario",
            "_ano_modelo_seguro_formulario",
            "estimativa_seguro_backend",
            "seguro_formulario_ou_padrao",
        }
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        from datetime import datetime
        namespace = {"estimar_seguro_v2": _fake_estimator, "datetime": datetime}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
        cls.seguro_formulario_ou_padrao = staticmethod(namespace["seguro_formulario_ou_padrao"])

    def test_blank_manual_insurance_is_zero(self):
        dados = {"seguro_icev": "", "seguro_icev_manual": "1"}
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_icev", 100000), 0.0)

    def test_zero_manual_insurance_is_zero(self):
        dados = {"seguro_ve": "0", "seguro_ve_manual": "1", "seguro_ve_considerado": "1"}
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 200000), 0.0)

    def test_explicitly_not_considered_insurance_is_zero_even_with_stale_value(self):
        dados = {
            "seguro_ve": "5.432,10",
            "seguro_ve_manual": "1",
            "seguro_ve_considerado": "0",
        }
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 100000), 0.0)

    def test_automatic_blank_insurance_uses_autoseg_reference(self):
        dados = {
            "seguro_ve": "",
            "seguro_ve_manual": "0",
            "estado_uf": "GO",
            "ano_modelo_ve": "Zero km",
        }
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 100000), 5200.0)

    def test_posted_automatic_value_is_preserved(self):
        dados = {"seguro_ve": "5.432,10", "seguro_ve_manual": "0"}
        self.assertAlmostEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 100000), 5432.10, places=2)


if __name__ == "__main__":
    unittest.main()
