import ast
import unittest
from pathlib import Path


class TcoInsuranceManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_path = Path(__file__).resolve().parents[1] / "routes" / "tco_routes.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        wanted_functions = {
            "conv",
            "seguro_padrao",
            "_flag_formulario_ativo",
            "seguro_formulario_ou_padrao",
        }
        selected = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "SEGURO_PADRAO_PERCENTUAL" for target in node.targets):
                    selected.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
                selected.append(node)
        module = ast.Module(body=selected, type_ignores=[])
        namespace = {}
        exec(compile(module, str(source_path), "exec"), namespace)
        cls.seguro_formulario_ou_padrao = staticmethod(namespace["seguro_formulario_ou_padrao"])

    def test_blank_manual_insurance_is_zero(self):
        dados = {"seguro_icev": "", "seguro_icev_manual": "1"}
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_icev", 100000), 0.0)

    def test_zero_manual_insurance_is_zero(self):
        dados = {"seguro_ve": "0", "seguro_ve_manual": "1"}
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 200000), 0.0)

    def test_automatic_blank_insurance_uses_default(self):
        dados = {"seguro_ve": "", "seguro_ve_manual": "0"}
        self.assertEqual(self.seguro_formulario_ou_padrao(dados, "seguro_ve", 100000), 4700.0)


if __name__ == "__main__":
    unittest.main()
