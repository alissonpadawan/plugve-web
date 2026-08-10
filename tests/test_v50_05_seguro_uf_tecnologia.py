import unittest
from pathlib import Path

from services.seguro_autoseg_service import (
    carregar_taxas_tecnologia,
    estimar_seguro_autoseg_referencia,
    normalizar_tecnologia_seguro,
)

ROOT = Path(__file__).resolve().parents[1]


class SeguroUfTecnologiaV50_05Tests(unittest.TestCase):
    def test_technology_reference_has_four_observed_categories(self):
        taxas = carregar_taxas_tecnologia()
        self.assertEqual(set(taxas), {"gasolina", "diesel", "hibrido", "eletrico"})
        self.assertAlmostEqual(taxas["gasolina"]["ipsa_percentual"], 3.4, places=6)
        self.assertAlmostEqual(taxas["diesel"]["ipsa_percentual"], 2.7, places=6)
        self.assertAlmostEqual(taxas["hibrido"]["ipsa_percentual"], 2.5, places=6)
        self.assertAlmostEqual(taxas["eletrico"]["ipsa_percentual"], 3.7, places=6)

    def test_go_rate_now_varies_by_technology(self):
        gas = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="gasolina")
        ev = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="eletrico")
        hybrid = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="hibrido")
        diesel = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="diesel")

        self.assertGreater(ev.taxa_efetiva, gas.taxa_efetiva)
        self.assertLess(hybrid.taxa_efetiva, diesel.taxa_efetiva)
        self.assertLess(diesel.taxa_efetiva, gas.taxa_efetiva)

    def test_relative_factors_are_data_derived_against_gasoline(self):
        gas = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="gasolina")
        ev = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="eletrico")
        hybrid = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="hibrido")
        diesel = estimar_seguro_autoseg_referencia(valor_fipe=100_000, uf="GO", tecnologia="diesel")

        self.assertAlmostEqual(ev.taxa_efetiva / gas.taxa_efetiva, 3.7 / 3.4, places=7)
        self.assertAlmostEqual(hybrid.taxa_efetiva / gas.taxa_efetiva, 2.5 / 3.4, places=7)
        self.assertAlmostEqual(diesel.taxa_efetiva / gas.taxa_efetiva, 2.7 / 3.4, places=7)

    def test_aliases_map_to_four_reference_categories(self):
        self.assertEqual(normalizar_tecnologia_seguro("BEV"), "eletrico")
        self.assertEqual(normalizar_tecnologia_seguro("PHEV"), "hibrido")
        self.assertEqual(normalizar_tecnologia_seguro("HEV"), "hibrido")
        self.assertEqual(normalizar_tecnologia_seguro("flex"), "gasolina")
        self.assertEqual(normalizar_tecnologia_seguro("diesel"), "diesel")

    def test_frontend_sends_technology_and_does_not_render_text_below_field(self):
        text = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn("tecnologia: tecnologiaSeguroPorPrefixoTCO(prefixo)", text)
        self.assertIn('if (tipo === "eletrico") return "eletrico";', text)
        self.assertIn('if (/\\bDIESEL\\b/.test(texto)) return "diesel";', text)
        self.assertNotIn("Estimativa SUSEP/AUTOSEG —", text)
        self.assertNotIn("Seguro automático indisponível. Informe um valor", text)

    def test_backend_fallback_classifies_prefix_and_fuel(self):
        text = (ROOT / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        self.assertIn("def tecnologia_seguro_formulario", text)
        self.assertIn('return "hibrido" if hibrido else "eletrico"', text)
        self.assertIn('if "DIESEL" in texto:', text)
        self.assertIn('classificador = globals().get("tecnologia_seguro_formulario")', text)
        self.assertIn("tecnologia=tecnologia,", text)

    def test_metadata_exposes_both_sources_and_technology(self):
        est = estimar_seguro_autoseg_referencia(
            valor_fipe=147_988,
            uf="GO",
            tecnologia="eletrico",
        ).to_dict()
        self.assertIn("AUTOSEG/SUSEP", est["fonte"])
        self.assertIn("IPSA/TEx", est["fonte"])
        self.assertEqual(est["tecnologia_referencia"], "eletrico")
        self.assertIn("Elétrico", est["nivel_agregacao"])
        self.assertIn("Abril de 2026", est["data_base"])


if __name__ == "__main__":
    unittest.main()
