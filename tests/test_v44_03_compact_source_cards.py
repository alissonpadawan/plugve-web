import re
import unittest
from pathlib import Path


class V4403CompactSourceCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_single_fuel_summary_is_percentage_only(self):
        self.assertIn('<span id="fuel_compact_left">100% gasolina</span>', self.template)
        self.assertIn(
            '<span id="fuel_compact_right" class="hidden" aria-hidden="true"></span>',
            self.template,
        )
        function = re.search(
            r"function renderizarCardCombustivelTCO\(\) \{.*?\n    \}",
            self.template,
            re.S,
        )
        self.assertIsNotNone(function)
        body = function.group(0)
        self.assertIn('compactLeft.textContent = "100% gasolina";', body)
        self.assertIn('compactLeft.textContent = "100% etanol";', body)
        self.assertIn('compactLeft.textContent = "100% diesel";', body)
        self.assertIn('compactRight.textContent = "";', body)
        self.assertIn('compactRight.classList.add("hidden");', body)
        self.assertIn('compactRight.setAttribute("aria-hidden", "true");', body)

    def test_flex_summary_keeps_both_sides_visible(self):
        function = re.search(
            r"function renderizarCardCombustivelTCO\(\) \{.*?\n    \}",
            self.template,
            re.S,
        )
        self.assertIsNotNone(function)
        body = function.group(0)
        self.assertIn('compactRight.classList.remove("hidden");', body)
        self.assertIn('compactRight.removeAttribute("aria-hidden");', body)
        self.assertIn('textoResumoPrecoFlexTCO("gasolina", gasolinaPct, precoGas)', body)

    def test_energy_and_single_fuel_cards_share_dimensions(self):
        self.assertIn(
            '#plugve_energy_card,#plugve_fuel_card{box-sizing:border-box;min-height:7.85rem;padding:.8rem .9rem}',
            self.template,
        )
        self.assertIn(
            '#plugve_energy_card .plugve-fuel-compact-top,#plugve_fuel_card .plugve-fuel-compact-top{display:grid;grid-template-columns:minmax(0,1fr) 9.6rem;align-items:center;gap:.8rem}',
            self.template,
        )
        self.assertIn(
            '#plugve_energy_card .plugve-energy-input-wrap,#plugve_fuel_card .plugve-field-source-wrap{width:9.6rem;min-width:9.6rem;max-width:9.6rem}',
            self.template,
        )
        self.assertIn(
            '#plugve_energy_card .plugve-fuel-title small,#plugve_fuel_card .plugve-fuel-title small{white-space:nowrap}',
            self.template,
        )
        self.assertIn(
            '#plugve_fuel_card[data-fuel-mode="flex"] .plugve-fuel-compact-top{grid-template-columns:1fr}',
            self.template,
        )

    def test_inmetro_consumption_logo_has_no_visible_button_shell(self):
        self.assertIn(
            'status.innerHTML = `<button type="button" class="plugve-pbev-proof-btn-main"',
            self.template,
        )
        self.assertIn(
            '.plugve-pbev-field-wrap>.plugve-pbev-status .plugve-pbev-proof-btn-main{width:1.9rem;height:1.9rem;border:0;background:transparent;border-radius:0;padding:.22rem;box-shadow:none;transform:none}',
            self.template,
        )
        self.assertIn(
            '.plugve-pbev-inline-status .plugve-pbev-proof-btn-main{width:1.7rem;height:1.7rem;border:0;background:transparent;border-radius:0;padding:.16rem;box-shadow:none;transform:none}',
            self.template,
        )
        self.assertIn('cursor:pointer', self.template)
        self.assertIn(':focus-visible{outline:2px solid #2563eb', self.template)


if __name__ == "__main__":
    unittest.main()
