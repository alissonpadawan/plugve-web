import unittest
from pathlib import Path


class V4316AneelAnpSourceBadgesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_official_source_assets_are_packaged(self):
        self.assertTrue((self.root / "static" / "img" / "fontes" / "aneel.png").is_file())
        self.assertTrue((self.root / "static" / "img" / "fontes" / "anp.png").is_file())

    def test_source_logos_are_subtle_and_anp_links_to_official_source(self):
        self.assertGreaterEqual(self.template.count("img/fontes/aneel.png"), 2)
        self.assertGreaterEqual(self.template.count("img/fontes/anp.png"), 4)
        self.assertIn(".plugve-source-logo{", self.template)
        self.assertNotIn('href="https://www.gov.br/aneel', self.template.lower())
        self.assertGreaterEqual(self.template.lower().count('href="https://www.gov.br/anp'), 4)
        self.assertGreaterEqual(self.template.count('target="_blank" rel="noopener noreferrer"'), 4)

    def test_aneel_logo_reuses_tariff_breakdown(self):
        self.assertIn("plugve-aneel-tooltip-trigger", self.template)
        self.assertIn("Composição da tarifa de energia", self.template)
        self.assertIn("plugve-aneel-distribuidora", self.template)
        self.assertIn("plugve-aneel-tarifa", self.template)
        self.assertIn("plugve-aneel-bar", self.template)
        self.assertIn("plugve-aneel-legenda", self.template)
        self.assertIn('document.querySelectorAll(".plugve-aneel-tooltip-panel")', self.template)
        self.assertIn("TUSD (Distribuição)", self.template)
        self.assertIn("TE (Energia)", self.template)
        self.assertIn("ICMS", self.template)
        self.assertIn("PIS", self.template)
        self.assertIn("COFINS", self.template)

    def test_touch_keyboard_and_logo_only_hover_are_available(self):
        self.assertIn("inicializarTooltipsFontesPlugVE();", self.template)
        self.assertIn('btn.setAttribute("aria-expanded", "false")', self.template)
        self.assertIn('(hover: none), (pointer: coarse)', self.template)
        self.assertIn('btn.addEventListener("mouseenter", abrirDesktop)', self.template)
        self.assertIn('btn.addEventListener("mouseleave", fecharDesktop)', self.template)
        self.assertIn('btn.addEventListener("focus"', self.template)
        self.assertIn('btn.addEventListener("blur"', self.template)
        self.assertNotIn('.plugve-source-tooltip:hover > .plugve-energy-tooltip-panel', self.template)
        self.assertNotIn('.plugve-aneel-tooltip-trigger:focus-visible + .plugve-energy-tooltip-panel', self.template)


if __name__ == "__main__":
    unittest.main()
