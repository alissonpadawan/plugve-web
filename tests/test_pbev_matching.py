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

    def test_plus_after_trim_is_not_treated_as_family_descriptor(self):
        tokens_all = self.service._tokens("DUSTER INTENSE PLUS 1.6 16V FLEX MEC")
        trim_tokens = self.service._trim_tokens_contextual("DUSTER INTENSE PLUS 1.6 16V FLEX MEC")
        self.assertEqual(self.service._family_descriptor_tokens_contextual(tokens_all, trim_tokens), set())

    def test_duster_intense_plus_zero_km_prefers_exact_year_and_equivalent_consumption(self):
        consulta = {
            "prefixo": "icev",
            "marca": "Renault",
            "modelo": "DUSTER Intense Plus 1.6 16V Flex Mec.",
            "texto_modelo": "Renault DUSTER Intense Plus 1.6 16V Flex Mec. Zero km Flex",
            "ano": 2026,
            "texto_ano": "Zero km Flex",
            "ano_codigo": "32000-5",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
            "zero_km": True,
        }
        result = self.service.sugerir_consumo(consulta)
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["ano_tabela_pbev"], 2026)
        self.assertEqual(result["candidato"]["modelo"], "DUSTER")
        self.assertEqual(result["candidato"]["versao"], "DUSTER INTP MT")
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 11.2)
        self.assertEqual(result["sugestoes_consumo"]["etanol_cidade_km_l"], 7.6)
        self.assertTrue(result["diagnostico"]["dominante"])
        self.assertFalse(result["diagnostico"]["ambiguidade_proxima"])
        self.assertTrue(result["diagnostico"]["ambiguidade_resolvida_por_consumo"])

    def test_corolla_cross_xrx_hybrid_flex_exposes_separate_fuel_consumptions(self):
        consulta = {
            "prefixo": "icev",
            "marca": "Toyota",
            "modelo": "Corolla Cross XRX 1.8 16V Aut.",
            "texto_modelo": "Corolla Cross XRX 1.8 16V Aut. Híbrido Zero km",
            "ano": 2026,
            "texto_ano": "Zero km Híbrido",
            "ano_codigo": "32000-3",
            "combustivel": "Híbrido",
            "tipo_veiculo": "hibrido",
        }
        result = self.service.sugerir_consumo(consulta)
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["sugestoes_consumo"]["tipo"], "hibrido_flex")
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 16.6)
        self.assertEqual(result["sugestoes_consumo"]["etanol_cidade_km_l"], 11.6)


    def test_zero_km_32000_is_centralized_and_prioritizes_latest_pbev_year(self):
        resolved = self.service.resolver_ano_fipe_para_matching({
            "ano": 32000,
            "ano_codigo": "32000-5",
            "texto_ano": "Zero km Flex",
        })
        self.assertTrue(resolved["zero_km_contexto"])
        self.assertIsNone(resolved["ano_referencia"])
        self.assertEqual(resolved["prioridade_ano_tabela"], "mais_recente")

        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Toyota",
            "modelo": "Corolla Cross XRE 2.0 16V Flex Aut.",
            "texto_modelo": "Corolla Cross XRE 2.0 16V Flex Aut. Zero km Flex",
            "ano": 32000,
            "ano_codigo": "32000-5",
            "texto_ano": "Zero km Flex",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["ano_tabela_pbev"], 2026)
        self.assertEqual(result["criterio_match"], "exato")

    def test_automotive_aliases_and_strong_tokens_are_general(self):
        normalized = self.service.normalizar_aliases_automotivos("Discovery Sp. X-Dyn P250FF Pick-up")
        self.assertIn("DISCOVERY SPORT", normalized)
        self.assertIn("X DYNAMIC", normalized)
        self.assertIn("P250", normalized)
        self.assertIn("PICKUP", normalized)
        self.assertEqual(self.service.extrair_tokens_fortes_modelo("T1 I-DM"), {"T1"})
        self.assertEqual(self.service.extrair_tokens_fortes_modelo("S06 DM"), {"S06"})
        self.assertEqual(self.service.extrair_tokens_fortes_modelo("P250FF"), {"P250"})
        self.assertNotIn("16V", self.service.extrair_tokens_fortes_modelo("1.6 16V"))

    def test_jetour_t1_strong_token_blocks_t2_and_s06(self):
        result = self.service.sugerir_consumo({
            "prefixo": "ve",
            "marca": "Jetour",
            "modelo": "T1 Advance 1.5 Híbrido Aut.",
            "texto_modelo": "T1 Advance 1.5 Híbrido Aut. Zero km Híbrido",
            "ano": 32000,
            "ano_codigo": "32000-1",
            "texto_ano": "Zero km Híbrido",
            "combustivel": "Híbrido",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "T1 I-DM")
        self.assertEqual(result["criterio_match"], "exato")

    def test_jetour_s06_strong_token_is_dominant(self):
        result = self.service.sugerir_consumo({
            "prefixo": "ve",
            "marca": "Jetour",
            "modelo": "S06 Advance 1.5 Híbrido Aut.",
            "texto_modelo": "S06 Advance 1.5 Híbrido Aut. Zero km Híbrido",
            "ano": 32000,
            "ano_codigo": "32000-1",
            "texto_ano": "Zero km Híbrido",
            "combustivel": "Híbrido",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "S06 DM")
        self.assertTrue(result["diagnostico"]["dominante"])

    def test_song_plus_generic_hybrid_is_refined_to_plugin(self):
        result = self.service.sugerir_consumo({
            "prefixo": "ve",
            "marca": "BYD",
            "modelo": "Song Plus 1.5 Híbrido Aut.",
            "texto_modelo": "Song Plus 1.5 Híbrido Aut. Zero km Híbrido",
            "ano": 32000,
            "ano_codigo": "32000-1",
            "texto_ano": "Zero km Híbrido",
            "combustivel": "Híbrido",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["sugestoes_consumo"]["tipo"], "phev")
        self.assertEqual(result["diagnostico"]["combustivel_detectado_fipe"], "PLUG_IN")

    def test_defender_d300_uses_family_and_diesel_technical_identity(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Land Rover",
            "modelo": "Defender 110 D300 HSE Diesel Aut. Híbrido",
            "texto_modelo": "Defender 110 D300 HSE Diesel Aut. Híbrido",
            "ano": 2024,
            "ano_codigo": "2024-3",
            "texto_ano": "2024 Diesel",
            "combustivel": "Diesel",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "DEFENDER 110")
        self.assertEqual(result["sugestoes_consumo"]["tipo"], "diesel")
        self.assertEqual(result["diagnostico"]["combustivel_detectado_fipe"], "DIESEL")
        self.assertEqual(result["criterio_match"], "versoes_equivalentes")

    def test_discovery_sport_alias_p250_selects_correct_family(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Land Rover",
            "modelo": "Discovery Sp. Dyn. P250 Flex Aut.",
            "texto_modelo": "Discovery Sp. Dyn. P250 Flex Aut.",
            "ano": 2021,
            "ano_codigo": "2021-3",
            "texto_ano": "2021 Flex",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "DISCOVERY SPORT")
        self.assertIn(result["criterio_match"], {"ano_modelo_adjacente", "versoes_equivalentes"})

    def test_towner_pickup_alias_prefers_pickup_over_van(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Hafei",
            "modelo": "Towner Jr. Pick-up Baú 1.0 Gasolina Mec.",
            "texto_modelo": "Towner Jr. Pick-up Baú 1.0 Gasolina Mec.",
            "ano": 2014,
            "ano_codigo": "2014-1",
            "texto_ano": "2014 Gasolina",
            "combustivel": "Gasolina",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "Start Pickup")
        self.assertEqual(result["diagnostico"]["carroceria_pbev"], ["PICKUP"])

    def test_huracan_missing_trim_uses_conservative_family_criterion(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Lamborghini",
            "modelo": "Huracán Sterrato 5.2 V10 Gasolina Aut.",
            "texto_modelo": "Huracán Sterrato 5.2 V10 Gasolina Aut.",
            "ano": 2024,
            "ano_codigo": "2024-1",
            "texto_ano": "2024 Gasolina",
            "combustivel": "Gasolina",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["criterio_match"], "conservador_por_familia")
        self.assertTrue(result["sugestoes_consumo"]["criterio_conservador_versoes_compativeis"])

    def test_aventador_distant_year_stays_confirmable_not_blind_autofill(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Lamborghini",
            "modelo": "Aventador SVJ Roadster 6.5 V12 Gasolina Aut.",
            "texto_modelo": "Aventador SVJ Roadster 6.5 V12 Gasolina Aut.",
            "ano": 2021,
            "ano_codigo": "2021-1",
            "texto_ano": "2021 Gasolina",
            "combustivel": "Gasolina",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "medio")
        self.assertFalse(result["autopreencher"])
        self.assertEqual(result["criterio_match"], "aproximacao_com_observacao")



if __name__ == "__main__":
    unittest.main()
