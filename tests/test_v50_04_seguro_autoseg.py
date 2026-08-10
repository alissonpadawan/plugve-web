import unittest

from services.seguro_autoseg_service import (
    carregar_taxas_uf,
    estimar_seguro_autoseg_referencia,
)


class SeguroAutosegUfV1Tests(unittest.TestCase):
    def test_go_uses_observed_premium_over_is_rate(self):
        est = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", ano_modelo="Zero km")
        esperado = 1290.0 / 41872.0
        self.assertAlmostEqual(est.taxa_efetiva, esperado, places=10)
        self.assertAlmostEqual(est.valor_anual, 100_000 * esperado, places=2)

    def test_rates_vary_by_state_without_authorial_factors(self):
        go = estimar_seguro_autoseg_referencia(valor_fipe=120_000, uf="GO", ano_modelo="Zero km")
        rj = estimar_seguro_autoseg_referencia(valor_fipe=120_000, uf="RJ", ano_modelo="Zero km")
        sc = estimar_seguro_autoseg_referencia(valor_fipe=120_000, uf="SC", ano_modelo="Zero km")
        self.assertGreater(rj.valor_anual, go.valor_anual)
        self.assertGreater(go.valor_anual, sc.valor_anual)

    def test_year_does_not_invent_adjustment_in_v1(self):
        novo = estimar_seguro_autoseg_referencia(valor_fipe=120_000, uf="GO", ano_modelo="Zero km")
        usado = estimar_seguro_autoseg_referencia(valor_fipe=120_000, uf="GO", ano_modelo="2016")
        self.assertAlmostEqual(novo.taxa_efetiva, usado.taxa_efetiva, places=12)

    def test_value_scales_linearly_at_same_state_rate(self):
        a = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO")
        b = estimar_seguro_autoseg_referencia(valor_fipe=200_000, uf="GO")
        self.assertAlmostEqual(b.valor_anual, a.valor_anual * 2, places=2)
        self.assertAlmostEqual(a.taxa_efetiva, b.taxa_efetiva, places=12)

    def test_unknown_state_uses_national_reference(self):
        est = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="XX")
        esperado = 1207.0 / 39425.0
        self.assertEqual(est.uf_referencia, "BR")
        self.assertAlmostEqual(est.taxa_efetiva, esperado, places=10)
        self.assertEqual(est.to_dict()["nivel_agregacao"], "Brasil — automóvel (fallback)")

    def test_metadata_is_explicit_and_not_quote(self):
        est = estimar_seguro_autoseg_referencia(valor_fipe=150_000, uf="GO").to_dict()
        self.assertIn("AUTOSEG/SUSEP", est["fonte"])
        self.assertEqual(est["data_base"], "1º semestre de 2020")
        self.assertEqual(est["nivel_agregacao"], "UF — automóvel")
        self.assertEqual(est["metodo"], "premio_medio_dividido_por_importancia_segurada_media")
        self.assertIn("não representa cotação", est["observacao"].lower())

    def test_reference_table_contains_brazil_and_all_27_ufs(self):
        taxas = carregar_taxas_uf()
        self.assertEqual(len(taxas), 28)
        self.assertIn("BR", taxas)
        self.assertIn("GO", taxas)
        self.assertIn("SP", taxas)


if __name__ == "__main__":
    unittest.main()
