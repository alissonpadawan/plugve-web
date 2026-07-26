import re
import unittest
from pathlib import Path


class V44SourceFieldProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")

    def test_all_aneel_and_anp_images_are_inside_source_money_fields(self):
        for match in re.finditer(r"img/fontes/(?:aneel|anp)\.png", self.template):
            before = self.template[max(0, match.start() - 1800):match.start()]
            self.assertRegex(before, r'plugve-money-field(?:--source|[^\n>]*plugve-fuel-money-field)')

    def test_badges_start_hidden_and_tooltip_panels_start_hidden(self):
        self.assertGreaterEqual(self.template.count('data-plugve-source-for='), 6)
        self.assertGreaterEqual(self.template.count('plugve-aneel-tooltip hidden'), 2)
        self.assertGreaterEqual(self.template.count('role="tooltip" hidden'), 2)
        self.assertIn('.plugve-energy-tooltip-panel[hidden]{display:none!important}', self.template)

    def test_aneel_badge_depends_on_official_source_and_manual_state(self):
        self.assertIn('fonteOficialAplicada: false', self.template)
        self.assertIn('plugveEnergiaResumoAtual.fonteOficialAplicada = true;', self.template)
        self.assertIn('plugveEnergiaResumoAtual.fonteOficialAplicada = false;', self.template)
        self.assertIn('marcarTarifaEnergiaManualPlugVE(true);', self.template)
        self.assertIn('definirVisibilidadeFonteCampoPlugVE("energia_input", oficial);', self.template)

    def test_anp_badges_have_per_fuel_manual_provenance(self):
        for fuel in ('gasolina', 'etanol', 'diesel_s10'):
            self.assertIn(f'id="fuel_preco_{fuel}_editado_usuario"', self.template)
        self.assertIn('plugveFontesAutomaticasTCO.anp.gasolina', self.template)
        self.assertIn('marcarPrecoCombustivelEditadoUsuarioTCO(true, "etanol")', self.template)
        self.assertIn('marcarPrecoCombustivelEditadoUsuarioTCO(true, "gasolina")', self.template)

    def test_phev_price_sources_are_invalidated_only_after_user_edit(self):
        self.assertIn('id="phev_preco_combustivel_editado_usuario"', self.template)
        self.assertIn('this.dataset.plugveFonteEditada = "1";', self.template)
        self.assertIn('aplicarEdicoesFontesModalPhevPlugVE();', self.template)

    def test_inmetro_badge_is_removed_after_consumption_edit(self):
        marker = re.search(
            r'function pbevMarcarConsumoEditadoUsuarioTCO\(prefixo\).*?\n    }',
            self.template,
            re.S,
        )
        self.assertIsNotNone(marker)
        self.assertIn('pbevDesativarComprovacaoTCO(prefixo);', marker.group(0))
        self.assertNotIn('pbevAtivarComprovacaoTCO(prefixo', marker.group(0))
        self.assertIn('const editado = document.getElementById(`pbev_${prefixo}_editado_usuario`)', self.template)

    def test_tooltip_is_closed_on_profile_close_and_vehicle_change(self):
        self.assertRegex(self.template, r'function fecharModalPhevTCO\(\) \{\s+fecharTooltipsAneelPlugVE\(\);')
        self.assertRegex(self.template, r'function limparEstadoVeiculoSelecionadoTCO\(prefixo\) \{\s+fecharTooltipsAneelPlugVE\(\);')
        self.assertIn('if (!ativo) {\n        fecharTooltipsAneelPlugVE();', self.template)


if __name__ == "__main__":
    unittest.main()
