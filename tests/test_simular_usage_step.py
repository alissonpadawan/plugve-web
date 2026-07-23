import unittest
from pathlib import Path


class SimularUsageStepTests(unittest.TestCase):
    def test_km_year_inputs_use_500_step(self):
        html = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('id="uso_km_ano_input" value="15000" min="0" step="500"', html)
        self.assertIn('id="km_ano_input" value="15000" min="0" step="500"', html)
        self.assertIn('id="resumo_km_ano" min="0" step="500"', html)
        self.assertIn('function liberarPassoKmParaEnvioPlugVE()', html)
        self.assertIn('campo.step = "any"', html)


if __name__ == "__main__":
    unittest.main()
