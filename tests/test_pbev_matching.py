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

    def test_hybrid_flex_label_does_not_become_plain_combustion_flex(self):
        resolved = self.service.resolver_propulsao_real({
            "marca": "Toyota",
            "modelo": "Corolla Cross XRX 1.8 Híbrido Flex",
            "texto_modelo": "Corolla Cross XRX 1.8 Híbrido Flex",
            "combustivel": "Flex",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(resolved, "HIBRIDO")

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


    def test_trim_before_decimal_engine_is_not_compound_model_token(self):
        fortes = self.service.extrair_tokens_fortes_modelo("Etios HB X 1.3-16V M-5")
        self.assertNotIn("X1", fortes)

    def test_power_and_door_tokens_are_not_model_identity(self):
        self.assertNotIn("720CV", self.service.extrair_tokens_fortes_modelo("F8 Spider 3.9 V8 720cv"))
        self.assertNotIn("620CV", self.service.extrair_tokens_fortes_modelo("Roma 3.9 V8 620cv"))
        self.assertNotIn("252CV", self.service.extrair_tokens_fortes_modelo("XC 40 T5 252cv"))
        self.assertNotIn("5P", self.service.extrair_tokens_fortes_modelo("XC 60 T5 5p"))

    def test_split_composite_identifiers_are_canonical(self):
        self.assertIn("XC40", self.service.extrair_tokens_fortes_modelo("XC 40 T5"))
        self.assertIn("XC60", self.service.extrair_tokens_fortes_modelo("XC 60 T5"))
        self.assertIn("SF90", self.service.extrair_tokens_fortes_modelo("SF 90 Spider"))
        self.assertIn("RAM2500", self.service.extrair_tokens_fortes_modelo("RAM 2500 Laramie"))

    def test_durango_family_beats_exact_year_journey_and_uses_safe_fallback(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Dodge",
            "modelo": "Durango Crew 3.6 24V 4x4 Aut.",
            "texto_modelo": "Durango Crew 3.6 24V 4x4 Aut. 2013 Gasolina",
            "ano": 2013, "texto_ano": "2013 Gasolina", "ano_codigo": "2013-1",
            "combustivel": "Gasolina", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"].upper(), "DURANGO")
        self.assertNotIn("JOURNEY", result["candidato"]["modelo"].upper())
        self.assertEqual(result["criterio_match"], "conservador_por_familia")
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 6.5)

    def test_dodge_ram_query_expands_search_to_ram_brand_group(self):
        keys = self.service._marca_keys_busca({
            "marca": "Dodge",
            "modelo": "Ram 2500 Laramie 6.7 TDI",
            "texto_modelo": "Ram 2500 Laramie 6.7 TDI Diesel",
        })
        self.assertEqual(keys, ["DODGE", "RAM"])

    def test_ram_2500_absent_does_not_receive_other_ram_or_dodge_consumption(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Dodge",
            "modelo": "Ram 2500 LARAMIE 6.7 TDI CD 4x4 Dies",
            "texto_modelo": "Ram 2500 LARAMIE 6.7 TDI CD 4x4 Dies 2012 Diesel",
            "ano": 2012, "texto_ano": "2012 Diesel", "ano_codigo": "2012-3",
            "combustivel": "Diesel", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "sem_match")
        self.assertFalse(result["autopreencher"])
        self.assertIsNone(result["candidato"])
        self.assertEqual(result["cobertura_pbev"], "ausente")

    def test_sf90_absent_does_not_fallback_to_ferrari_296(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Ferrari",
            "modelo": "SF 90 SPIDER 4.0 V8 Bi-Turbo (Híbrido)",
            "texto_modelo": "SF 90 SPIDER 4.0 V8 Bi-Turbo (Híbrido) 2023",
            "ano": 2023, "texto_ano": "2023 Híbrido", "ano_codigo": "2023-6",
            "combustivel": "Híbrido", "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "sem_match")
        self.assertFalse(result["autopreencher"])
        self.assertIsNone(result["candidato"])

    def test_f8_spider_power_is_secondary_and_exact_candidate_autofills(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Ferrari",
            "modelo": "F8 Spider 3.9 V8 Bi-Turbo 720cv",
            "texto_modelo": "F8 Spider 3.9 V8 Bi-Turbo 720cv 2022 Gasolina",
            "ano": 2022, "texto_ano": "2022 Gasolina", "ano_codigo": "2022-1",
            "combustivel": "Gasolina", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("F8 SPIDER", f"{result["candidato"]["modelo"]} {result["candidato"].get("versao") or ""}".upper())
        self.assertEqual(result["ano_tabela_pbev"], 2022)
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 5.6)

    def test_ferrari_roma_power_is_secondary_and_exact_candidate_autofills(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Ferrari",
            "modelo": "Roma 3.9 V8 620cv",
            "texto_modelo": "Roma 3.9 V8 620cv 2024 Gasolina",
            "ano": 2024, "texto_ano": "2024 Gasolina", "ano_codigo": "2024-1",
            "combustivel": "Gasolina", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "ROMA")
        self.assertEqual(result["ano_tabela_pbev"], 2024)
        self.assertEqual(result["sugestoes_consumo"]["gasolina_cidade_km_l"], 6.9)

    def test_wey_07_positive_equivalent_versions_remain_autofill(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "GWM",
            "modelo": "Wey 07 Dark Edition 1.5 Turbo AWD",
            "texto_modelo": "Wey 07 Dark Edition 1.5 Turbo AWD Zero km Híbrido",
            "ano": 2026, "texto_ano": "Zero km Híbrido", "ano_codigo": "32000-6",
            "combustivel": "Híbrido", "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("WEY 07", f"{result["candidato"]["modelo"]} {result["candidato"].get("versao") or ""}".upper())
        self.assertEqual(result["sugestoes_consumo"]["tipo"], "phev")
        self.assertEqual(result["sugestoes_consumo"]["gasolina_diesel_cidade_km_l"], 10.8)

    def test_xc40_composite_family_beats_v40_and_ignores_power(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Volvo",
            "modelo": "XC 40 T-5 MOMENT FIRST ED. 2.0 252cv AWD",
            "texto_modelo": "XC 40 T-5 MOMENT FIRST ED. 2.0 252cv AWD 2018 Gasolina",
            "ano": 2018, "texto_ano": "2018 Gasolina", "ano_codigo": "2018-1",
            "combustivel": "Gasolina", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertIn("XC40", result["candidato"]["modelo"].replace(" ", ""))
        self.assertNotIn("V40", result["candidato"]["modelo"].replace("XC40", ""))
        self.assertEqual(result["ano_tabela_pbev"], 2018)

    def test_xc60_composite_family_beats_v60_and_ignores_5p(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev", "marca": "Volvo",
            "modelo": "XC 60 T-5 R-DESIGN 2.0 FWD 5p",
            "texto_modelo": "XC 60 T-5 R-DESIGN 2.0 FWD 5p 2017 Gasolina",
            "ano": 2017, "texto_ano": "2017 Gasolina", "ano_codigo": "2017-1",
            "combustivel": "Gasolina", "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertEqual(result["candidato"]["modelo"], "XC60")
        self.assertEqual(result["ano_tabela_pbev"], 2017)
        self.assertNotIn("V60", result["candidato"]["modelo"])



if __name__ == "__main__":
    unittest.main()
