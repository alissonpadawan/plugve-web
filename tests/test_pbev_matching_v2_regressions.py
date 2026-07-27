import json
import unittest
from pathlib import Path

from services.pbev_service import PbevService


class PbevMatchingV2RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.service = PbevService(
            base_path=cls.root / "data" / "pbev" / "pbev_base_saneada_v1.json",
            manifest_path=cls.root / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
        )
        cls.cases = json.loads((cls.root / "data" / "pbev" / "casos_regressao_matching_v2.json").read_text(encoding="utf-8"))

    @staticmethod
    def _candidate_text(result):
        c = result.get("candidato") or {}
        return " ".join(str(c.get(k) or "") for k in ("marca", "modelo", "versao", "motor", "transmissao")).upper()

    def test_reported_cases(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = self.service.sugerir_consumo(dict(case["consulta"]))
                expected = case["esperado"]
                self.assertEqual(result.get("nivel_match"), expected.get("nivel_match"), result.get("diagnostico_terminal"))
                self.assertEqual(bool(result.get("autopreencher")), bool(expected.get("autopreencher")), result.get("diagnostico_terminal"))
                self.assertFalse(result.get("requer_confirmacao"), result.get("diagnostico_terminal"))
                self.assertEqual(result.get("opcoes_confirmacao"), [])
                if expected.get("candidato_ausente"):
                    self.assertIsNone(result.get("candidato"), result.get("diagnostico_terminal"))
                    continue
                text = self._candidate_text(result)
                if expected.get("modelo_igual"):
                    self.assertEqual(str((result.get("candidato") or {}).get("modelo") or "").upper(), expected["modelo_igual"].upper())
                if expected.get("modelo_versao_contem"):
                    self.assertIn(expected["modelo_versao_contem"].upper(), text)
                if expected.get("candidato_nao_contem"):
                    self.assertNotIn(expected["candidato_nao_contem"].upper(), text)
                s = result.get("sugestoes_consumo") or {}
                if expected.get("tipo_consumo"):
                    self.assertEqual(str(s.get("tipo") or "").lower(), expected["tipo_consumo"].lower())
                for key in (
                    "gasolina_cidade_km_l", "etanol_cidade_km_l",
                    "gasolina_diesel_cidade_km_l", "consumo_eletrico_kwh_km",
                ):
                    if key in expected:
                        self.assertAlmostEqual(float(s.get(key)), float(expected[key]), places=5, msg=result.get("diagnostico_terminal"))


if __name__ == "__main__":
    unittest.main()
