import unittest
from pathlib import Path


class SeguroV23FechamentoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.template = (cls.root / "templates" / "simular.html").read_text(encoding="utf-8")
        cls.route = (cls.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")

    def test_formulario_tem_estado_explicito_seguro_considerado(self):
        for prefixo in ("atual", "ve", "icev"):
            self.assertIn(
                f'name="seguro_{prefixo}_considerado" id="seguro_{prefixo}_considerado" value="1"',
                self.template,
            )
        self.assertIn("function marcarSeguroConsiderado(prefixo, considerado)", self.template)
        self.assertIn('marcarSeguroConsiderado(prefixo, String(this.value || "").trim() !== "");', self.template)

    def test_status_manual_permanece_visivel_e_distingue_exclusao(self):
        self.assertIn('atualizarStatusSeguroManualTCO(prefixo);', self.template)
        self.assertIn('"Valor informado pelo usuário."', self.template)
        self.assertIn('"Seguro não considerado."', self.template)
        self.assertNotIn('if (jaManual && !forcar) {\n        if (status) {\n          status.classList.add("hidden")', self.template)

    def test_backend_registra_nao_considerado_sem_confundir_com_zero_manual(self):
        self.assertIn('def _seguro_considerado_formulario', self.route)
        self.assertIn('"origem": "nao_considerado"', self.route)
        self.assertIn('"considerado": False', self.route)
        self.assertIn('if not seguro_considerado:', self.route)
        self.assertIn('seguro_ano = 0.0', self.route)
        self.assertIn('"Seguro_n (não considerado) = 0"', self.route)

    def test_resultado_e_pdf_mostram_nao_considerado_sem_quebrar_snapshot_antigo(self):
        self.assertIn('item.seguro_considerado is defined and not item.seguro_considerado', self.template)
        self.assertIn('comp.detalhes[0].seguro_considerado is defined and not comp.detalhes[0].seguro_considerado', self.template)
        # O backend continua assumindo considerado=True quando o campo não existe em snapshot antigo.
        self.assertIn('"seguro_considerado": bool(v.get("seguro_considerado", True))', self.route)

    def test_metodologia_do_estimador_nao_foi_tocada_nesta_rodada(self):
        service = self.root / "services" / "seguro_v2_service.py"
        self.assertTrue(service.exists())
        self.assertIn('CURVE_VERSION = "V50.28"', (self.root / "config.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
