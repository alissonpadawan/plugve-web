from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from services.pbev_matching_v46.normalizer import build_text_views, extract_technical_evidence
from services.pbev_service import PbevService


class PbevMatchingV46RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.service = PbevService(
            base_path=cls.root / "data" / "pbev" / "pbev_base_saneada_v1.json",
            manifest_path=cls.root / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
        )
        cls.cases = json.loads(
            (cls.root / "data" / "pbev" / "casos_regressao_matching_v46.json").read_text(encoding="utf-8")
        )
        cls.previous_engine = os.environ.get("PBEV_MATCHING_ENGINE")
        os.environ["PBEV_MATCHING_ENGINE"] = "v46"

    @classmethod
    def tearDownClass(cls):
        if cls.previous_engine is None:
            os.environ.pop("PBEV_MATCHING_ENGINE", None)
        else:
            os.environ["PBEV_MATCHING_ENGINE"] = cls.previous_engine

    def _assert_case(self, case):
        result = self.service.sugerir_consumo(case["consulta"])
        expected = case["esperado"]
        candidate = result.get("candidato") or {}
        candidate_text = " ".join(str(candidate.get(k) or "") for k in ("modelo", "versao")).upper()
        suggestion = result.get("sugestoes_consumo") or {}

        if "nivel_match" in expected:
            self.assertEqual(result.get("nivel_match"), expected["nivel_match"], case["id"])
        if "autopreencher" in expected:
            self.assertEqual(result.get("autopreencher"), expected["autopreencher"], case["id"])
        if expected.get("modelo_igual"):
            self.assertEqual(str(candidate.get("modelo") or "").upper(), expected["modelo_igual"].upper(), case["id"])
        wanted = expected.get("modelo_contem") or expected.get("modelo_versao_contem")
        if wanted:
            self.assertIn(wanted.upper(), candidate_text, case["id"])
        for key in ("modelo_nao_contem", "candidato_nao_contem"):
            if expected.get(key):
                self.assertNotIn(expected[key].upper(), candidate_text, case["id"])
        if expected.get("candidato_ausente"):
            self.assertFalse(candidate, case["id"])

        for key in (
            "gasolina_cidade_km_l",
            "etanol_cidade_km_l",
            "gasolina_diesel_cidade_km_l",
            "consumo_eletrico_kwh_km",
        ):
            if key in expected:
                self.assertAlmostEqual(float(suggestion.get(key) or 0), float(expected[key]), places=6, msg=case["id"])
        if expected.get("tipo_consumo"):
            self.assertEqual(suggestion.get("tipo"), expected["tipo_consumo"], case["id"])

        required = {
            "encontrou", "nivel_match", "score", "motivo", "autopreencher", "origem",
            "sugestoes_consumo", "candidato", "flags", "diagnostico", "debug", "diagnostico_terminal",
        }
        self.assertTrue(required <= set(result), case["id"])

    def test_all_known_real_regressions(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self._assert_case(case)

    def test_compact_and_segmented_views_are_both_preserved(self):
        samples = {
            "xDrive40i": ("XDRIVE40I", "XDRIVE 40I"),
            "Style1.0": ("STYLE1.0", "STYLE 1.0"),
            "TB12V": ("TB12V", "TB 12V"),
            "1.0T": ("1.0T", "1.0 T"),
            "XC 60": ("XC60", "XC 60"),
        }
        for raw, (atom, segmented) in samples.items():
            with self.subTest(raw=raw):
                views = build_text_views(raw)
                self.assertIn(atom.replace(".", ""), {a.replace(".", "") for a in views.atoms})
                self.assertIn(segmented, views.segmented)

    def test_technical_tokens_do_not_become_false_model_identity(self):
        views = build_text_views("Creta Comfort 1.0 TB12V Flex Aut.")
        tech = extract_technical_evidence(views, infer_natural=True)
        self.assertEqual(tech.displacements, frozenset({1.0}))
        self.assertEqual(tech.valves, frozenset({12}))
        self.assertTrue(tech.turbo)
        self.assertEqual(tech.transmission_family, "AUTO")

    def test_simular_template_has_only_the_approved_async_loading_guards(self):
        template = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        for prefix in ("atual", "ve", "icev"):
            self.assertIn(f'id="fipe_loading_{prefix}"', template)
            self.assertIn(f'id="pbev_loading_{prefix}"', template)
        self.assertIn('id="pbev_loading_modal_flex"', template)
        self.assertIn('id="pbev_loading_modal_phev"', template)
        self.assertIn("const CONSULTAS_FIPE_TCO", template)
        self.assertIn("const CONSULTAS_PBEV_TCO", template)
        self.assertIn("signal: consultaFipe.signal", template)
        self.assertIn("signal: consulta.signal", template)
        self.assertIn("Consultando valor FIPE…", template)
        self.assertIn("Consultando consumo no Inmetro…", template)
        self.assertNotIn("pbevBotaoConfirmacaoPorPrefixoTCO", template)
        self.assertNotIn("pbevGarantirModalConfirmacaoTCO", template)

    def test_engine_error_falls_back_to_v44_without_breaking_contract(self):
        class BrokenMatcher:
            def suggest(self, _consulta):
                raise RuntimeError("falha simulada")

        previous_matcher = getattr(self.service, "_matcher_v46", None)
        self.service._matcher_v46 = BrokenMatcher()
        try:
            result = self.service.sugerir_consumo(self.cases[0]["consulta"])
            self.assertEqual(result.get("motor_matching"), "v44_fallback_erro_v46")
            self.assertIn("falha simulada", (result.get("diagnostico") or {}).get("erro_motor_v46", ""))
            required = {
                "encontrou", "nivel_match", "score", "motivo", "autopreencher", "origem",
                "sugestoes_consumo", "candidato", "flags", "diagnostico", "debug", "diagnostico_terminal",
            }
            self.assertTrue(required <= set(result))
        finally:
            if previous_matcher is None:
                try:
                    delattr(self.service, "_matcher_v46")
                except AttributeError:
                    pass
            else:
                self.service._matcher_v46 = previous_matcher

    def test_v44_can_be_selected_without_template_change(self):
        previous = os.environ.get("PBEV_MATCHING_ENGINE")
        try:
            os.environ["PBEV_MATCHING_ENGINE"] = "v44"
            result = self.service.sugerir_consumo(self.cases[0]["consulta"])
            self.assertEqual(result["motor_matching"], "v44")
            self.assertIn("diagnostico", result)
        finally:
            if previous is None:
                os.environ.pop("PBEV_MATCHING_ENGINE", None)
            else:
                os.environ["PBEV_MATCHING_ENGINE"] = previous


if __name__ == "__main__":
    unittest.main()
