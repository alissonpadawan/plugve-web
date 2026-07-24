import re
import unittest
from pathlib import Path


class SimularAlignmentStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_each_alignment_key_exists_in_both_vehicle_columns(self):
        for key in ("perfil", "preco", "consumo", "manutencao", "ipva", "seguro", "depreciacao"):
            self.assertEqual(
                len(re.findall(fr'data-plugve-align="{key}"', self.template)),
                2,
                msg=f"O par de alinhamento {key!r} deve existir exatamente nos dois lados.",
            )

    def test_alignment_is_measured_and_disabled_on_mobile(self):
        self.assertIn("function alinharParesVeiculosPlugVE()", self.template)
        self.assertIn("getBoundingClientRect().height", self.template)
        self.assertIn("window.innerWidth < 1024", self.template)
        self.assertIn("@media(max-width:1023px){.plugve-align-pair{min-height:0!important}}", self.template)

    def test_dynamic_content_triggers_realignment(self):
        self.assertIn("new MutationObserver(() => agendarAlinhamentoVeiculosPlugVE())", self.template)
        self.assertIn('window.addEventListener("resize", agendarAlinhamentoVeiculosPlugVE', self.template)
        self.assertIn("agendarAlinhamentoVeiculosPlugVE();", self.template)


if __name__ == "__main__":
    unittest.main()
