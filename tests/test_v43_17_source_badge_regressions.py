import re
import unittest
from pathlib import Path


class V4317SourceBadgeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")

    def _between(self, start: str, end: str) -> str:
        i = self.template.index(start)
        j = self.template.index(end, i)
        return self.template[i:j]

    def test_energy_heading_above_card_was_removed(self):
        self.assertNotIn("Custo energia elétrica (R$/kWh)", self.template)

    def test_summary_cards_do_not_show_source_logos(self):
        phev_summary = self._between('id="plugve_phev_card"', 'id="phev_bar_eletrico"')
        self.assertNotIn("img/fontes/aneel.png", phev_summary)
        self.assertNotIn("img/fontes/anp.png", phev_summary)

        flex_header = self._between('data-fuel-mode="flex">', '<div class="plugve-fuel-prices">')
        self.assertNotIn("img/fontes/anp.png", flex_header)

    def test_pure_ev_aneel_logo_is_inside_editable_price(self):
        energy_input = self._between(
            '<div class="plugve-energy-input-wrap"',
            '<div class="plugve-phev-mini-bar"',
        )
        self.assertIn('class="plugve-money-field plugve-money-field--source"', energy_input)
        self.assertIn('id="energia_input"', energy_input)
        self.assertIn('data-plugve-source-for="energia_input"', energy_input)
        self.assertIn("img/fontes/aneel.png", energy_input)
        self.assertIn("plugve-aneel-tooltip-panel", energy_input)

    def test_sources_are_inside_price_fields(self):
        for field_id in (
            "fuel_modal_preco_etanol",
            "fuel_modal_preco_gasolina",
            "phev_modal_preco_combustivel",
        ):
            pattern = re.compile(
                rf'<div class="plugve-money-field plugve-money-field--source">.*?id="{field_id}".*?data-plugve-source-for="{field_id}".*?img/fontes/anp\.png.*?</div>',
                re.S,
            )
            self.assertRegex(self.template, pattern)

        phev_energy = re.compile(
            r'<div class="plugve-money-field plugve-money-field--source">.*?id="phev_modal_preco_energia".*?data-plugve-source-for="phev_modal_preco_energia".*?img/fontes/aneel\.png.*?</div>',
            re.S,
        )
        self.assertRegex(self.template, phev_energy)

    def test_desktop_hover_is_bound_only_to_logo_and_cannot_stick(self):
        self.assertIn('.plugve-energy-tooltip-panel[hidden]{display:none!important}', self.template)
        self.assertIn('.plugve-source-tooltip.is-open > .plugve-energy-tooltip-panel', self.template)
        self.assertNotIn('.plugve-source-tooltip:hover > .plugve-energy-tooltip-panel', self.template)
        self.assertIn('btn.addEventListener("mouseenter", abrirDesktop)', self.template)
        self.assertIn('btn.addEventListener("mouseleave", fecharDesktop)', self.template)
        self.assertIn('definirTooltipAneelAbertoPlugVE(wrapper, false)', self.template)

    def test_touch_keeps_explicit_toggle_and_outside_close(self):
        self.assertIn('definirTooltipAneelAbertoPlugVE(wrapper, abrir)', self.template)
        self.assertIn('document.addEventListener("click", function (ev)', self.template)
        self.assertIn('if (ev.target.closest?.(".plugve-aneel-tooltip")) return;', self.template)
        self.assertIn('fecharTooltipsAneelPlugVE();', self.template)

    def test_manual_price_hides_source_without_deleting_breakdown(self):
        self.assertIn('marcarTarifaEnergiaManualPlugVE(true)', self.template)
        self.assertIn('const oficial = plugveEnergiaResumoAtual.fonteOficialAplicada === true && !tarifaEnergiaManualPlugVE();', self.template)
        manual_branch = self._between('if (manual) {', 'status.textContent = "Buscando tarifa de energia')
        self.assertIn('plugveEnergiaResumoAtual.detalhe', manual_branch)
        self.assertIn('atualizarLogosAneelPlugVE();', manual_branch)
        self.assertNotIn('plugveEnergiaResumoAtual.detalhe = null', manual_branch)


if __name__ == "__main__":
    unittest.main()
