import unittest

from services.pbev_matching_v2.identity import build_query_identity, build_record_identity
from services.pbev_matching_v2.normalizer import AutomotiveNormalizer


class PbevMatchingV2ParserTests(unittest.TestCase):
    def query(self, model, *, brand="Teste", fuel="Flex", prefix="icev", year=2026):
        return build_query_identity({
            "prefixo": prefix,
            "marca": brand,
            "modelo": model,
            "texto_modelo": model,
            "ano": year,
            "texto_ano": f"{year} {fuel}",
            "combustivel": fuel,
            "tipo_veiculo": "hibrido" if fuel == "Híbrido" else "combustao",
        })

    def test_tb12v_is_split_into_technical_facts(self):
        norm = AutomotiveNormalizer.normalize("Creta 1.0 TB12V Aut.")
        self.assertIn("TURBO", norm.token_set)
        self.assertIn("12V", norm.token_set)
        self.assertNotIn("TB12V", norm.token_set)

    def test_6v_is_valves_not_family(self):
        ident = self.query("C3 Live Plus 1.0 6V 5p Mec.", brand="Citroën")
        self.assertEqual(ident.valves, frozenset({6}))
        self.assertIn("C3", ident.model_core_tokens)
        self.assertNotIn("6V", ident.model_core_tokens)

    def test_style10_is_separated_without_style1_token(self):
        ident = self.query("HB20S C.Plus/C.Style1.0 Flex 12V Mec.", brand="Hyundai", year=2019)
        self.assertIn(1.0, ident.displacements)
        self.assertIn("STYLE", ident.trim_tokens)
        self.assertNotIn("STYLE1", ident.normalized.token_set)

    def test_xdrive40i_colocated_and_separated_are_equivalent(self):
        a = self.query("X7 XDRIVE 40i M Sport 3.0 Aut.", brand="BMW", fuel="Híbrido")
        b = self.query("X7 xDrive40i M Sport 3.0 A-8", brand="BMW", fuel="Híbrido")
        self.assertIn("X7", a.model_alnum_anchors)
        self.assertIn("X7", b.model_alnum_anchors)
        self.assertIn("40I", a.commercial_power)
        self.assertIn("40I", b.commercial_power)

    def test_general_alpha_number_model_composition(self):
        for separated, compact in (("CLA 200", "CLA200"), ("SERES 3", "SERES3"), ("SLC 300", "SLC300"), ("TIGGO 5X", "TIGGO5X")):
            with self.subTest(separated=separated):
                a = AutomotiveNormalizer.normalize(separated)
                b = AutomotiveNormalizer.normalize(compact)
                self.assertTrue(a.token_set & b.token_set, (a, b))
                self.assertIn(compact, a.token_set)

    def test_commercial_200_does_not_replace_c3_family(self):
        ident = self.query("C3 YOU! 1.0 Flex Turbo 200 Aut.", brand="Citroën")
        self.assertIn("C3", ident.model_core_tokens)
        self.assertNotIn("200", ident.model_core_tokens)
        self.assertIn("200", ident.commercial_power)

    def test_record_cla_200_and_query_cla200_share_anchor(self):
        record = build_record_identity({
            "marca": "Mercedes-Benz", "modelo": "CLA 200", "versao_corrigida": "AMG LINE",
            "motor_corrigido": "1.3-16V", "transmissao": "DCT-7", "ano_tabela": 2025,
            "combustivel_normalizado": "GASOLINA", "tipo_propulsao_normalizado": "HIBRIDO",
        })
        query = self.query("CLA200 AMG LINE 1.3-16V DCT-7", brand="Mercedes-Benz", fuel="Gasolina", year=2025)
        self.assertIn("CLA200", record.model_alnum_anchors)
        self.assertIn("CLA200", query.model_alnum_anchors)


if __name__ == "__main__":
    unittest.main()
