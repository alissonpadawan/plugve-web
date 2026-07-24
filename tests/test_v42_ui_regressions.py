import unittest
from pathlib import Path


class V42UiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_zero_km_combobox_uses_visual_label(self):
        js = (self.root / "static" / "js" / "fipe_combobox.js").read_text(encoding="utf-8")
        self.assertIn('codigo.startsWith("32000")', js)
        self.assertIn('replace(/^\\s*32000\\b/i, "Zero km")', js)

    def test_simular_uses_optimized_preloaded_webp_images(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('rel="preload" as="image" type="image/webp"', html)
        self.assertIn("simular-stage-vehicle.webp", html)
        self.assertIn("simular-stage-vehicle-icev.webp", html)
        self.assertTrue((self.root / "static" / "img" / "simular-stage-vehicle.webp").exists())
        self.assertTrue((self.root / "static" / "img" / "simular-stage-vehicle-icev.webp").exists())

    def test_flex_skip_restores_snapshot_and_consumption_edit_is_separate_from_proof(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn("function restaurarSnapshotModalCombustivelTCO(snapshot)", html)
        self.assertIn("restaurarSnapshotModalCombustivelTCO(snapshot);", html)
        self.assertIn("abrirModalCombustivelTCO({ somenteConsumo: true, prefixo });", html)
        self.assertIn("pbevAbrirComprovacaoTCO(prefixo);", html)
        self.assertIn("ev.stopPropagation();", html)
        self.assertNotIn('campo.setAttribute("title", "Clique para ver os dados Inmetro/PBEV considerados")', html)


if __name__ == "__main__":
    unittest.main()
