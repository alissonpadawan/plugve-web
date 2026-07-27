import unittest
from pathlib import Path

from services.pbev_service import PbevService


class PbevConfirmationFlowV45Tests(unittest.TestCase):
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

    def test_medium_match_exposes_safe_confirmation_options(self):
        result = self.service.sugerir_consumo(dict(self.aventador))
        self.assertEqual(result["nivel_match"], "medio")
        self.assertFalse(result["autopreencher"])
        self.assertTrue(result["requer_confirmacao"])
        self.assertGreaterEqual(len(result["opcoes_confirmacao"]), 1)
        self.assertLessEqual(len(result["opcoes_confirmacao"]), 6)
        for option in result["opcoes_confirmacao"]:
            self.assertTrue(option["id_pbev"])
            self.assertTrue(option["candidato"])
            self.assertTrue(option["sugestoes_consumo"])
            self.assertTrue(option["confirmavel"])

    def test_confirmed_medium_candidate_returns_auditable_high_match(self):
        initial = self.service.sugerir_consumo(dict(self.aventador))
        chosen_id = initial["opcoes_confirmacao"][0]["id_pbev"]
        confirmed = self.service.sugerir_consumo({**self.aventador, "confirmar_id_pbev": chosen_id})
        self.assertEqual(confirmed["nivel_match"], "alto")
        self.assertTrue(confirmed["autopreencher"])
        self.assertTrue(confirmed["confirmado_usuario"])
        self.assertFalse(confirmed["requer_confirmacao"])
        self.assertEqual(confirmed["criterio_match"], "confirmacao_usuario")
        self.assertEqual(confirmed["candidato"]["id_pbev"], chosen_id)
        self.assertTrue(confirmed["sugestoes_consumo"])
        self.assertIn("confirmada pelo usuário", confirmed["motivo"].lower())
        self.assertTrue(confirmed["diagnostico"]["confirmacao_usuario"])

    def test_invalid_confirmation_id_never_autofills(self):
        result = self.service.sugerir_consumo({**self.aventador, "confirmar_id_pbev": "PBEV-INEXISTENTE"})
        self.assertFalse(result["autopreencher"])
        self.assertFalse(result.get("confirmado_usuario", False))
        self.assertTrue(result["requer_confirmacao"])
        self.assertIn("não pertence", result["motivo_confirmacao"].lower())

    def test_high_match_does_not_request_confirmation(self):
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

    def test_true_absence_does_not_offer_confirmation(self):
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
        self.assertFalse(result["requer_confirmacao"])
        self.assertEqual(result["opcoes_confirmacao"], [])

    def test_simular_contains_confirmation_flow_without_removing_provenance_rules(self):
        html = (self.root / "templates" / "simular.html").read_text(encoding="utf-8")
        self.assertIn("confirmar_id_pbev", html)
        self.assertIn("plugve-pbev-confirm-modal", html)
        self.assertIn("Confirmar versão Inmetro", html)
        self.assertIn("pbevAplicarSugestaoConsumoTCO", html)
        self.assertIn("pbevDesativarComprovacaoTCO", html)


    def test_endpoint_and_proof_keep_confirmation_auditable(self):
        route = (self.root / "routes" / "pbev_routes.py").read_text(encoding="utf-8")
        proof = (self.root / "templates" / "pbev_comprovacao.html").read_text(encoding="utf-8")
        self.assertIn('payload.get("confirmar_id_pbev")', route)
        self.assertIn('Cache-Control"] = "no-store"', route)
        self.assertIn("Configuração selecionada pelo usuário", proof)
        self.assertIn("criterio_match", proof)

    def test_fipe_plus_exposes_confirmation_options(self):
        html = (self.root / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
        self.assertIn("confirmar_id_pbev", html)
        self.assertIn("confirmarOpcaoPbev", html)
        self.assertIn("Configurações compatíveis encontradas", html)


if __name__ == "__main__":
    unittest.main()
