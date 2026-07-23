import unittest
from pathlib import Path

from services.pbev_service import PbevService


class PbevMatchingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.service = PbevService(
            base_path=root / "data" / "pbev" / "pbev_base_saneada_v1.json",
            manifest_path=root / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
        )

    def test_compact_commercial_identifier_suffix_is_not_equivalent(self):
        query_ids = self.service._identificadores_comerciais_modelo("AB12 Limited")
        candidate_ids = self.service._identificadores_comerciais_modelo("AB12S Limited")
        self.assertEqual(query_ids, {"AB12"})
        self.assertEqual(candidate_ids, {"AB12S"})
        self.assertTrue(self.service._identificadores_comerciais_divergentes(query_ids, candidate_ids))

    def test_split_alphanumeric_spelling_remains_equivalent(self):
        query_ids = self.service._identificadores_comerciais_modelo("E 2008 GT")
        candidate_ids = self.service._identificadores_comerciais_modelo("E2008 GT")
        self.assertIn("E2008", query_ids)
        self.assertIn("E2008", candidate_ids)
        self.assertFalse(self.service._identificadores_comerciais_divergentes(query_ids, candidate_ids))

    def test_weak_near_candidate_does_not_block_strong_identity(self):
        top = {
            "avaliacao": {
                "identidade_tecnica_forte": True,
                "tecnica_suficiente_para_consumo": True,
            },
            "registro": {
                "marca": "Marca Exemplo",
                "modelo": "AB12",
                "versao": "Limited",
                "motor": "1.0 T",
                "transmissao": "A-6",
                "combustivel": "Flex",
                "tipo_propulsao": "Combustão",
            },
            "sugestao": {"tipo": "flex", "gasolina_cidade_km_l": 13.2, "etanol_cidade_km_l": 9.2},
        }
        weak = {
            "avaliacao": {
                "identidade_tecnica_forte": False,
                "tecnica_suficiente_para_consumo": False,
            },
            "registro": {
                "marca": "Marca Exemplo",
                "modelo": "AB12S",
                "versao": "Limited",
                "motor": "1.0 T",
                "transmissao": "A-6",
                "combustivel": "Flex",
                "tipo_propulsao": "Combustão",
            },
            "sugestao": {"tipo": "flex", "gasolina_cidade_km_l": 13.0, "etanol_cidade_km_l": 9.1},
        }
        self.assertFalse(self.service._candidatos_proximos_bloqueiam_autofill(top, [weak]))

    def test_hb20_hatch_dominates_hb20s_false_ambiguity(self):
        consulta = {
            "prefixo": "icev",
            "marca": "Hyundai",
            "modelo": "HB20 Limited 1.0 TB Flex 12V Aut.",
            "texto_modelo": "HB20 Limited 1.0 TB Flex 12V Aut. Zero km Flex",
            "ano": 2026,
            "texto_ano": "Zero km Zero km Flex",
            "ano_codigo": "32000-5",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
            "codigo_fipe": "015251-0",
        }
        result = self.service.sugerir_consumo(consulta)
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "HB20")
        self.assertEqual(result["candidato"]["versao"], "Limited")
        self.assertEqual(result["ano_tabela_pbev"], 2026)
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 13.2)
        self.assertEqual(result["sugestoes_consumo"]["etanol_cidade_km_l"], 9.2)
        self.assertTrue(result["diagnostico"]["dominante"])
        self.assertFalse(result["diagnostico"]["ambiguidade_proxima"])

    def test_hb20s_sedan_dominates_hb20_hatch(self):
        consulta = {
            "prefixo": "icev",
            "marca": "Hyundai",
            "modelo": "HB20S Limited 1.0 TB Flex 12V Aut.",
            "texto_modelo": "HB20S Limited 1.0 TB Flex 12V Aut. Zero km Flex",
            "ano": 2026,
            "texto_ano": "Zero km Flex",
            "ano_codigo": "32000-5",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
        }
        result = self.service.sugerir_consumo(consulta)
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "HB20S")
        self.assertEqual(result["candidato"]["versao"], "Limited")
        self.assertTrue(result["diagnostico"]["dominante"])
        self.assertFalse(result["diagnostico"]["ambiguidade_proxima"])


if __name__ == "__main__":
    unittest.main()
