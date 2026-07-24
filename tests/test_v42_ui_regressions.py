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

    def test_manual_fuel_origin_and_currency_prefixes_are_present(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('id="fuel_preco_editado_usuario" value="0"', html)
        self.assertIn('return precoCombustivelEditadoUsuarioTCO() ? "Ajustado pelo usuário" : "Valor médio ANP";', html)
        self.assertIn('<span class="plugve-money-prefix">R$</span>', html)
        self.assertIn('.plugve-energy-input-wrap .plugve-money-prefix{display:block}', html)
        self.assertIn('class="plugve-money-field plugve-fuel-money-field"', html)

    def test_manual_blank_insurance_is_signaled_to_backend(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        route = (self.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        for prefixo in ("atual", "ve", "icev"):
            self.assertIn(f'name="seguro_{prefixo}_manual" id="seguro_{prefixo}_manual" value="0"', html)
        self.assertIn('marcarSeguroManual(prefixo, true);', html)
        self.assertIn('if (jaManual && !forcar)', html)
        self.assertIn('if _flag_formulario_ativo(dados_form, f"{campo}_manual"):', route)
        self.assertIn('return max(0.0, conv(valor_bruto))', route)

    def test_hybrid_flex_requires_profile_before_unlocking_tco(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('id="fuel_flex_perfil_obrigatorio" value="0"', html)
        self.assertIn('String(sugestao.tipo || "") === "hibrido_flex"', html)
        self.assertIn('function perfilFlexObrigatorioTCO(prefixoPreferido)', html)
        self.assertIn('function configurarObrigatoriedadePerfilFlexTCO(prefixoPreferido, somenteConsumo = false)', html)
        self.assertIn('return obrigatorio && chaveSalva === chaveFlexAtualTCO(prefixo);', html)
        self.assertIn('if (modo === "flex") return document.getElementById("fuel_flex_configurado")?.value === "1";', html)
        self.assertIn('btn.classList.toggle("hidden", obrigatorio);', html)
        self.assertIn('const perfilObrigatorio = perfilFlexObrigatorioTCO(prefixo)', html)
        self.assertIn('setValorInputTCO("fuel_flex_configurado", "0");', html)

    def test_refined_pbev_fuel_mode_is_bound_to_current_vehicle_key(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('const modoRefinado = document.getElementById("fuel_tipo_detectado")?.value || "";', html)
        self.assertIn('if (chaveSalva === chaveAtual && ["flex", "diesel", "etanol", "gasolina"].includes(modoRefinado))', html)


if __name__ == "__main__":
    unittest.main()
