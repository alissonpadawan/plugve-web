import re
import unittest
from pathlib import Path


class V4315PhevProfileRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_phev_modal_shows_energy_price_and_uses_live_energy_value(self):
        self.assertIn('id="phev_modal_preco_energia"', self.template)
        self.assertIn('for="phev_modal_preco_energia">Preço (R$/kWh)', self.template)
        self.assertIn('const precoEnergia = document.getElementById("energia_input")?.value || "";', self.template)
        self.assertIn('setValorPhevTCO("phev_modal_preco_energia", precoEnergia);', self.template)
        self.assertIn('"phev_modal_preco_energia", "phev_modal_preco_combustivel"', self.template)

    def test_phev_compact_card_shows_energy_and_fuel_prices(self):
        self.assertIn('`${eletricoPct}% elétrico${precoEnergiaTexto}`', self.template)
        self.assertIn('`${combustPct}% combustível${precoCombustivelTexto}`', self.template)
        self.assertIn('/kWh`', self.template)
        self.assertIn('/L`', self.template)
        self.assertIn('#plugve_phev_card .plugve-phev-compact-row span{white-space:normal', self.template)

    def test_skip_preserves_an_already_saved_phev_profile(self):
        cancel = re.search(
            r'function cancelarModalPhevTCO\(\) \{(?P<body>.*?)\n    \}\n\n    function salvarModalPhevTCO',
            self.template,
            flags=re.S,
        )
        self.assertIsNotNone(cancel)
        body = cancel.group('body')
        self.assertIn('const jaConfigurado = document.getElementById("phev_configurado")?.value === "1";', body)
        self.assertIn('if (jaConfigurado) {', body)
        self.assertIn('prepararModalPhevTCO();', body)
        self.assertIn('return;', body)

        slider = re.search(
            r'const slider = document.getElementById\("phev_mix_slider"\);\n      slider\?\.addEventListener\("input", function \(\) \{(?P<body>.*?)\n      \}\);',
            self.template,
            flags=re.S,
        )
        self.assertIsNotNone(slider)
        self.assertNotIn('setValorPhevTCO("phev_percent_eletrico"', slider.group('body'))

    def test_obsolete_fuel_heading_is_removed(self):
        self.assertNotIn('>Valor do combustível (R$/L)</label>', self.template)


if __name__ == "__main__":
    unittest.main()
