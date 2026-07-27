import unittest
from pathlib import Path

from services.pbev_service import PbevService


class PbevAutomaticDecisionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.service = PbevService(
            base_path=root / "data" / "pbev" / "pbev_base_saneada_v1.json",
            manifest_path=root / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
        )
        cls.aventador = {
            "prefixo": "icev",
            "marca": "Lamborghini",
            "modelo": "Aventador SVJ Roadster 6.5 V12 Gasolina Aut.",
            "texto_modelo": "Aventador SVJ Roadster 6.5 V12 Gasolina Aut.",
            "ano": 2021,
            "ano_codigo": "2021-1",
            "texto_ano": "2021 Gasolina",
            "combustivel": "Gasolina",
            "tipo_veiculo": "combustao",
        }

    def test_medium_match_never_requests_manual_confirmation(self):
        result = self.service.sugerir_consumo(dict(self.aventador))
        self.assertEqual(result["nivel_match"], "medio")
        self.assertFalse(result["autopreencher"])
        self.assertFalse(result["requer_confirmacao"])
        self.assertEqual(result["opcoes_confirmacao"], [])
        self.assertFalse(result["confirmado_usuario"])

    def test_confirmation_identifier_is_ignored_by_motor_v2(self):
        baseline = self.service.sugerir_consumo(dict(self.aventador))
        attempted = self.service.sugerir_consumo({**self.aventador, "confirmar_id_pbev": "PBEV-INEXISTENTE"})
        self.assertEqual(attempted["nivel_match"], baseline["nivel_match"])
        self.assertEqual(attempted["autopreencher"], baseline["autopreencher"])
        self.assertFalse(attempted["requer_confirmacao"])
        self.assertEqual(attempted["opcoes_confirmacao"], [])
        self.assertFalse(attempted["confirmado_usuario"])

    def test_high_match_is_automatic(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Hyundai",
            "modelo": "Creta Comfort 1.0 TB 12V Flex Aut.",
            "texto_modelo": "Creta Comfort 1.0 TB 12V Flex Aut. Zero km Flex",
            "ano": 2026,
            "texto_ano": "Zero km Flex",
            "ano_codigo": "32000-5",
            "combustivel": "Flex",
            "tipo_veiculo": "combustao",
        })
        self.assertEqual(result["nivel_match"], "alto")
        self.assertTrue(result["autopreencher"])
        self.assertFalse(result["requer_confirmacao"])
        self.assertEqual(result["opcoes_confirmacao"], [])

    def test_true_absence_stays_manual_without_confirmation(self):
        result = self.service.sugerir_consumo({
            "prefixo": "icev",
            "marca": "Ferrari",
            "modelo": "SF 90 SPIDER 4.0 V8 Bi-Turbo (Híbrido)",
            "texto_modelo": "SF 90 SPIDER 4.0 V8 Bi-Turbo (Híbrido) 2023",
            "ano": 2023,
            "ano_codigo": "2023-6",
            "texto_ano": "2023 Híbrido",
            "combustivel": "Híbrido",
            "tipo_veiculo": "hibrido",
        })
        self.assertEqual(result["nivel_match"], "sem_match")
        self.assertFalse(result["autopreencher"])
        self.assertFalse(result["requer_confirmacao"])
        self.assertEqual(result["opcoes_confirmacao"], [])

    def test_simular_has_no_manual_pbev_confirmation_ui(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertNotIn("confirmar_id_pbev", html)
        self.assertNotIn("plugve-pbev-confirm-modal", html)
        self.assertNotIn("Confirmar versão Inmetro", html)
        self.assertIn("pbevAplicarSugestaoConsumoTCO", html)
        self.assertIn("pbevDesativarComprovacaoTCO", html)

    def test_endpoint_is_automatic_and_cacheable(self):
        route = (self.root / "routes" / "pbev_routes.py").read_text(encoding="utf-8")
        proof = (self.root / "templates" / "pbev_comprovacao.html").read_text(encoding="utf-8")
        self.assertNotIn('payload.get("confirmar_id_pbev")', route)
        self.assertNotIn('Cache-Control"] = "no-store"', route)
        self.assertIn("não existe seleção manual", route)
        self.assertNotIn("Configuração selecionada pelo usuário", proof)
        self.assertIn("criterio_match", proof)

    def test_fipe_plus_has_no_manual_pbev_confirmation_ui(self):
        html = (self.root / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
        self.assertNotIn("confirmar_id_pbev", html)
        self.assertNotIn("confirmarOpcaoPbev", html)
        self.assertNotIn("Configurações compatíveis encontradas", html)


if __name__ == "__main__":
    unittest.main()
