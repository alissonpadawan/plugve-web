import json
import tempfile
import unittest
from pathlib import Path

from scripts.diagnosticar_matching_pbev_v45_etapa2 import run
from services.pbev_service import PbevService


class PbevMatchingV45Etapa2Tests(unittest.TestCase):
    """Regressões do núcleo geral da V45 Etapa 2."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.cases_path = cls.root / "data" / "pbev" / "casos_regressao_matching_v45_etapa2.json"
        cls.service = PbevService(
            base_path=cls.root / "data" / "pbev" / "pbev_base_saneada_v1.json",
            manifest_path=cls.root / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
        )
        cases = json.loads(cls.cases_path.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in cases}

    def _result(self, case_id):
        return self.service.sugerir_consumo(self.cases[case_id]["consulta"])

    def test_technical_components_do_not_become_commercial_strong_tokens(self):
        self.assertNotIn("TB12V", self.service.extrair_tokens_fortes_modelo("1.0 TB 12V Flex Aut."))
        self.assertNotIn("TDI16V", self.service.extrair_tokens_fortes_modelo("2.8 TDI 16V 4x4 Aut."))

    def test_real_commercial_identifiers_remain_strong(self):
        examples = {
            "Volvo XC 60 T8": "XC60",
            "Hyundai HB20S Limited": "HB20S",
            "Peugeot e-2008 GT": "E2008",
            "Ferrari SF90 Spider": "SF90",
            "Jetour T1 Premium": "T1",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertIn(expected, self.service.extrair_tokens_fortes_modelo(text))

    def test_creta_is_high_exact_match_and_autofills(self):
        result = self._result("hyundai_creta_comfort_tb12v_zero_km")
        diagnostics = result["diagnostico"]

        self.assertTrue(result["encontrou"])
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["criterio_match"], "exato")
        self.assertEqual(result["candidato"]["id_pbev"], "PBEV-2026-0386")
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 12.0)
        self.assertEqual(result["sugestoes_consumo"]["etanol_cidade_km_l"], 8.4)
        self.assertNotIn("TB12V", diagnostics["tokens_fortes_fipe"])
        self.assertTrue(diagnostics["identidade_tecnica_forte"])
        self.assertTrue(diagnostics["tecnica_suficiente_para_consumo"])

    def test_hilux_tdi16v_is_parsed_as_technical_configuration(self):
        result = self._result("toyota_hilux_srv_tdi16v")
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("SRV", (result["candidato"].get("versao") or "").upper())
        self.assertNotIn("TDI16V", result["diagnostico"]["tokens_fortes_fipe"])

    def test_spider_abbreviation_is_resolved_generally(self):
        result = self._result("ferrari_12cilindri_spider")
        candidate_text = " ".join(
            str(result["candidato"].get(key) or "") for key in ("modelo", "versao")
        ).upper()
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("12CILINDRI", candidate_text)
        self.assertIn("SPI", candidate_text)

    def test_explicit_my_prevents_newer_configuration_from_winning(self):
        result = self._result("volvo_xc60_t8_ultimate_dark_my24")
        candidate_text = " ".join(
            str(result["candidato"].get(key) or "") for key in ("modelo", "versao")
        ).upper()
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("XC60", candidate_text)
        self.assertNotIn("MY25", candidate_text)

    def test_absent_sf90_stays_without_match_after_rescue_search(self):
        result = self._result("sf90_sem_cobertura")
        filters = result["debug"]["filtros"]

        self.assertEqual(result["nivel_match"], "sem_match")
        self.assertFalse(result["autopreencher"])
        self.assertFalse(result.get("candidato"))
        self.assertEqual(result["debug"]["normalizacao"].get("motor"), "V2")
        self.assertGreaterEqual(filters.get("candidatos_contradicao_bloqueados", 0), 1)
        self.assertEqual(filters["descartados_prefiltro_identidade"], 0)
        self.assertEqual(filters["registros_avaliados_marca"], filters["registros_marca"])

    def test_stage2_harness_passes_all_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, summary = run(self.cases_path, Path(tmp))

        self.assertEqual(summary["casos_total"], 31)
        self.assertEqual(summary["casos_aprovados"], 31)
        self.assertEqual(summary["falhas"], 0)
        self.assertEqual(summary["positivos_localizados"], 29)
        self.assertEqual(summary["positivos_autopreenchidos"], 28)
        self.assertEqual(summary["negativos_preservados"], 2)
        self.assertEqual(summary["lacunas_corrigidas_etapa2"], 4)
        self.assertTrue(summary["prefiltro_destrutivo_removido"])
        self.assertTrue(all(row["status_execucao"] == "APROVADO" for row in rows))


if __name__ == "__main__":
    unittest.main()
