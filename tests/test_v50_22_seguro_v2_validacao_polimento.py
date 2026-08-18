import unittest
from pathlib import Path

from services.seguro_v2_service import estimar_seguro_v2, referencias_ipsa_aplicaveis


class SeguroV22ValidacaoPolimentoTests(unittest.TestCase):
    def _taxa(self, valor, ano="2023"):
        return estimar_seguro_v2(
            valor_fipe=valor,
            uf="GO",
            municipio="Goiânia",
            ano_modelo=ano,
            tecnologia="gasolina",
            codigo_fipe="002111-3",
            ano_referencia=2026,
        )["taxa_efetiva"]

    def test_transicao_fipe_nao_tem_salto_de_um_real_nos_limites(self):
        for limite in (50_000, 80_000, 150_000):
            antes = self._taxa(limite)
            depois = self._taxa(limite + 1)
            self.assertLess(abs(antes - depois), 0.01, (limite, antes, depois))

    def test_fora_da_janela_preserva_taxa_publicada_da_faixa(self):
        refs, _ = referencias_ipsa_aplicaveis(
            valor_fipe=60_000, ano_modelo="2023", tecnologia="gasolina", ano_referencia=2026
        )
        valor_ref = next(r for r in refs if r.dimensao == "valor_fipe")
        self.assertEqual(valor_ref.chave, "51_80")
        self.assertAlmostEqual(valor_ref.taxa_percentual, 6.1, places=6)

    def test_dentro_da_janela_documenta_transicao_sem_inventar_nova_fonte(self):
        refs, _ = referencias_ipsa_aplicaveis(
            valor_fipe=80_000, ano_modelo="2023", tecnologia="gasolina", ano_referencia=2026
        )
        valor_ref = next(r for r in refs if r.dimensao == "valor_fipe")
        self.assertTrue(valor_ref.chave.startswith("transicao_"))
        self.assertAlmostEqual(valor_ref.taxa_percentual, (6.1 + 3.8) / 2, places=6)
        self.assertIn("transição contínua", valor_ref.recorte)

    def test_idade_10_para_11_nao_despenca_para_estimador_antigo(self):
        dez = estimar_seguro_v2(
            valor_fipe=60_000, uf="GO", municipio="Goiânia", ano_modelo="2016",
            tecnologia="gasolina", codigo_fipe="002111-3", ano_referencia=2026,
        )
        onze = estimar_seguro_v2(
            valor_fipe=60_000, uf="GO", municipio="Goiânia", ano_modelo="2015",
            tecnologia="gasolina", codigo_fipe="002111-3", ano_referencia=2026,
        )
        self.assertEqual(onze["versao_estimador"], "seguro_v2")
        self.assertEqual(onze["confianca"], "referencia")
        self.assertLess(abs(dez["taxa_efetiva"] - onze["taxa_efetiva"]), 2.0)

    def test_amostra_tecnologias_novas_sem_autoseg_continua_funcional(self):
        casos = [
            ("eletrico", "095010-6", 117_012),
            ("hibrido", "096001-2", 150_000),
            ("diesel", "999999-9", 250_000),
            ("gasolina", "999998-0", 100_000),
        ]
        for tecnologia, codigo, valor in casos:
            est = estimar_seguro_v2(
                valor_fipe=valor, uf="GO", municipio="Goiânia", ano_modelo="Zero km 2026",
                tecnologia=tecnologia, codigo_fipe=codigo, ano_referencia=2026,
            )
            self.assertGreater(est["valor_anual"], 0)
            self.assertGreaterEqual(est["taxa_efetiva"], 1.0)
            self.assertLessEqual(est["taxa_efetiva"], 12.0)


    def test_regiao_ipsa_atual_diferencia_veiculo_novo_sem_historico_autoseg(self):
        kwargs = dict(
            valor_fipe=117_012, ano_modelo="Zero km 2026", tecnologia="eletrico",
            codigo_fipe="095010-6", ano_referencia=2026,
        )
        rio = estimar_seguro_v2(uf="RJ", municipio="Rio de Janeiro", **kwargs)
        curitiba = estimar_seguro_v2(uf="PR", municipio="Curitiba", **kwargs)
        goiania = estimar_seguro_v2(uf="GO", municipio="Goiânia", **kwargs)
        self.assertGreater(rio["taxa_efetiva"], goiania["taxa_efetiva"])
        self.assertGreater(goiania["taxa_efetiva"], curitiba["taxa_efetiva"])
        self.assertEqual(rio["fator_regiao_fonte"], "IPSA maio/2026")
        self.assertEqual(curitiba["fator_regiao_fonte"], "IPSA maio/2026")
        self.assertIsNone(goiania["regiao_ipsa"])

    def test_regiao_ipsa_atual_substitui_geografia_autoseg_sem_apagar_fator_modelo(self):
        est = estimar_seguro_v2(
            valor_fipe=103_110, uf="SP", municipio="São Paulo", ano_modelo="2021",
            tecnologia="gasolina", codigo_fipe="002111-3", ano_referencia=2026,
        )
        self.assertEqual(est["fator_regiao_fonte"], "IPSA maio/2026")
        self.assertIsNotNone(est["regiao_ipsa"])
        self.assertNotEqual(est["fator_modelo"], 1.0)
        self.assertEqual(est["fator_cidade"], 1.0)
        self.assertIn("Região Metropolitana de São Paulo", est["nivel_agregacao"])
        self.assertNotIn("ajuste regional AUTOSEG", est["nivel_agregacao"])
        self.assertNotIn("ajuste municipal AUTOSEG", est["nivel_agregacao"])

    def test_status_visual_e_curto_e_fonte_fica_em_tooltip(self):
        text = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn("Seguro estimado · confiança", text)
        self.assertIn("status.title = [estimativa?.fonte", text)
        self.assertNotIn("Estimativa IPSA + AUTOSEG · confiança", text)


if __name__ == "__main__":
    unittest.main()
