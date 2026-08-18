import sqlite3
import unittest
from pathlib import Path

from services.seguro_v2_service import (
    ARQUIVO_AUTOSEG_V2,
    DATA_BASE_V2,
    estimar_seguro_v2,
    referencias_ipsa_aplicaveis,
    status_seguro_v2,
)


class SeguroV2Tests(unittest.TestCase):
    def test_base_autoseg_compacta_integra(self):
        self.assertTrue(ARQUIVO_AUTOSEG_V2.exists())
        with sqlite3.connect(f"file:{ARQUIVO_AUTOSEG_V2.as_posix()}?mode=ro", uri=True) as con:
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertGreater(con.execute("SELECT COUNT(*) FROM modelo_catalogo").fetchone()[0], 8000)

    def test_ipsa_maio_2026_eletrico_zero_km_usa_idade_valor_tecnologia(self):
        refs, info = referencias_ipsa_aplicaveis(
            valor_fipe=117_012, ano_modelo="Zero km", tecnologia="eletrico"
        )
        self.assertTrue(info["zero_km"])
        self.assertEqual({r.dimensao for r in refs}, {"idade", "valor_fipe", "tecnologia"})
        taxas = {r.dimensao: r.taxa_percentual for r in refs}
        self.assertEqual(taxas["idade"], 3.0)
        self.assertEqual(taxas["valor_fipe"], 3.8)
        self.assertEqual(taxas["tecnologia"], 3.7)
        est = estimar_seguro_v2(
            valor_fipe=117_012, uf="GO", municipio="Goiânia", ano_modelo="Zero km",
            tecnologia="eletrico", codigo_fipe="095010-6",
        )
        self.assertAlmostEqual(est["taxa_ipsa_base"], 3.7, places=3)
        self.assertEqual(est["confianca"], "referencia")
        self.assertEqual(est["fator_modelo"], 1.0)
        self.assertEqual(est["fator_regiao"], 1.0)
        self.assertIn("maio de 2026", DATA_BASE_V2)

    def test_tecnologia_ipsa_nao_e_aplicada_acima_de_dois_anos(self):
        refs, _ = referencias_ipsa_aplicaveis(
            valor_fipe=100_000, ano_modelo="2019", tecnologia="eletrico"
        )
        self.assertNotIn("tecnologia", {r.dimensao for r in refs})

    def test_corolla_goiania_recebe_fatores_regiao_modelo_e_cidade(self):
        est = estimar_seguro_v2(
            valor_fipe=103_110, uf="GO", municipio="Goiânia", ano_modelo="2021",
            tecnologia="gasolina", codigo_fipe="002111-3",
        )
        self.assertLess(est["fator_modelo"], 1.0)
        self.assertLess(est["fator_regiao"], 1.0)
        self.assertGreater(est["fator_cidade"], 1.0)
        self.assertEqual(est["confianca"], "media")
        self.assertIn("código FIPE histórico AUTOSEG", est["nivel_agregacao"])
        self.assertIn("ajuste regional AUTOSEG", est["nivel_agregacao"])
        self.assertIn("ajuste municipal AUTOSEG", est["nivel_agregacao"])
        self.assertEqual(est["autoseg"]["fator_modelo"]["classe"], "ALTA")
        self.assertEqual(est["autoseg"]["fator_regiao"]["classe"], "ALTA")

    def test_kwid_goias_historicamente_acima_da_categoria(self):
        est = estimar_seguro_v2(
            valor_fipe=74_000, uf="GO", municipio="Goiânia", ano_modelo="2021",
            tecnologia="gasolina", codigo_fipe="025266-2",
        )
        self.assertGreater(est["fator_modelo"], 1.0)
        self.assertGreater(est["taxa_efetiva"], 0)

    def test_codigo_novo_sem_autoseg_continua_com_ipsa(self):
        est = estimar_seguro_v2(
            valor_fipe=150_000, uf="GO", municipio="Goiânia", ano_modelo="Zero km",
            tecnologia="hibrido", codigo_fipe="096001-2",
        )
        self.assertGreater(est["valor_anual"], 0)
        self.assertEqual(est["confianca"], "referencia")
        self.assertEqual(est["nivel_agregacao"], "IPSA maio/2026")
        self.assertEqual(est["fator_modelo"], 1.0)
        self.assertEqual(est["fator_regiao"], 1.0)

    def test_veiculo_acima_de_10_anos_nao_inventa_faixa_etaria_nem_volta_ao_legado(self):
        est = estimar_seguro_v2(
            valor_fipe=60_000, uf="GO", municipio="Goiânia", ano_modelo="2012",
            tecnologia="gasolina", codigo_fipe="002111-3", ano_referencia=2026,
        )
        self.assertEqual(est["confianca"], "referencia")
        self.assertEqual(est["versao_estimador"], "seguro_v2")
        self.assertIn("sem faixa etária específica >10 anos", est["nivel_agregacao"])
        self.assertNotIn("idade", {r["dimensao"] for r in est["referencias_ipsa"]})
        self.assertIn("mercado", {r["dimensao"] for r in est["referencias_ipsa"]})

    def test_referencia_v2_muda_com_idade_e_faixa_de_valor_no_horizonte(self):
        inicial = estimar_seguro_v2(
            valor_fipe=117_012, uf="GO", municipio="Goiânia", ano_modelo="2026",
            tecnologia="eletrico", codigo_fipe="095010-6", ano_referencia=2026,
        )
        futuro = estimar_seguro_v2(
            valor_fipe=78_000, uf="GO", municipio="Goiânia", ano_modelo="2026",
            tecnologia="eletrico", codigo_fipe="095010-6", ano_referencia=2030,
        )
        self.assertNotEqual(inicial["taxa_ipsa_base"], futuro["taxa_ipsa_base"])
        self.assertEqual(inicial["confianca"], "referencia")
        self.assertEqual(futuro["confianca"], "referencia")

    def test_status_v2(self):
        st = status_seguro_v2()
        self.assertTrue(st["configured"])
        self.assertTrue(st["autoseg"])
        self.assertGreaterEqual(st["modelos_autoseg"], 8000)
        self.assertGreaterEqual(st["ipsa_referencias"], 10)

    def test_frontend_envia_codigo_fipe_e_exibe_confianca(self):
        text = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn('codigo_fipe: document.getElementById(`codigo_fipe_${prefixo}`)', text)
        self.assertIn('id="seguro_ve_confianca"', text)
        self.assertIn('confianca: estimativa?.confianca', text)
        self.assertIn("Seguro estimado", text)

    def test_zero_km_da_fipe_e_preservado_ate_o_estimador(self):
        template = (Path(__file__).resolve().parents[1] / "templates" / "simular.html").read_text(encoding="utf-8")
        backend = (Path(__file__).resolve().parents[1] / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        self.assertIn('return `Zero km ${valorAnoModelo || new Date().getFullYear()}`', template)
        self.assertIn('def _ano_modelo_seguro_formulario', backend)
        self.assertIn('return f"Zero km {ano_num}"', backend)

    def test_tco_reestima_seguro_automatico_ano_a_ano_sem_mudar_manual(self):
        text = (Path(__file__).resolve().parents[1] / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        self.assertIn("seguro_automatico_v2", text)
        self.assertIn("ano_referencia=datetime.now().year + (ano - 1)", text)
        self.assertIn("est_seguro_ano = estimar_seguro_v2", text)
        self.assertIn("seguro_ano = valor_mercado * taxa_seguro", text)
        self.assertIn('"taxa_seguro": taxa_seguro_ano', text)


if __name__ == "__main__":
    unittest.main()
