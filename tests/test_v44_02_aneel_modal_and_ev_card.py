import re
import unittest
from pathlib import Path


class V4402AneelModalAndEvCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_edit_modal_tooltip_is_floated_to_document_body(self):
        self.assertIn("plugve-energy-tooltip-panel--floating", self.template)
        self.assertIn("wrapper?.closest(\".plugve-edit-modal\")", self.template)
        self.assertIn("document.body.appendChild(painel);", self.template)
        self.assertIn("wrapper.appendChild(painel);", self.template)

    def test_floating_tooltip_is_clamped_to_viewport(self):
        self.assertIn("gatilho.getBoundingClientRect()", self.template)
        self.assertIn("painel.getBoundingClientRect()", self.template)
        self.assertIn("viewportLargura - largura - margem", self.template)
        self.assertIn("viewportAltura - altura - margem", self.template)
        self.assertIn('document.addEventListener("scroll", fecharTooltipsAneelPlugVE, true);', self.template)

    def test_ev_energy_value_reserves_space_for_aneel_logo(self):
        self.assertIn(
            ".plugve-energy-input-wrap .plugve-money-field--source input{padding-right:4.15rem!important}",
            self.template,
        )

    def test_ev_energy_summary_is_100_percent_for_bev_and_syncs_when_phev(self):
        row = re.search(
            r'<div class="plugve-phev-compact-row plugve-energy-row">(.*?)</div>',
            self.template,
            re.S,
        )
        self.assertIsNotNone(row)
        self.assertIn("100% elétrico", row.group(1))
        self.assertIn('id="energia_compact_right" class="hidden"', row.group(1))
        self.assertNotIn("Tarifa ANEEL", row.group(1))
        self.assertIn('function renderizarParticipacaoEnergiaPhevPlugVE(eletricoPctOverride = null)', self.template)
        self.assertIn('const eletricoPct = phevAtivo', self.template)
        self.assertIn('barEletrico.style.width = `${eletricoPct}%`', self.template)
        self.assertIn('barCombustivel.style.width = `${combustPct}%`', self.template)
        self.assertIn('direita.classList.toggle("hidden", !phevAtivo)', self.template)


if __name__ == "__main__":
    unittest.main()
