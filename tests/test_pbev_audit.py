import unittest

from scripts.auditar_matching_pbev import validar_invariantes


class PbevAuditInvariantTests(unittest.TestCase):
    def test_flags_covered_candidate_not_autofilled(self):
        resultado = {
            "autopreencher": False,
            "diagnostico": {"ambiguidade_proxima": False},
            "debug": {
                "candidatos_top": [{
                    "flags_ok": True,
                    "fuel_ok": True,
                    "tem_sugestao_consumo": True,
                    "ano_compativel_fipe_pbev": True,
                    "tecnica_suficiente_para_consumo": True,
                    "modelo_score": 32,
                    "token_forte_divergente": False,
                    "familia_textual_divergente": False,
                }]
            },
        }
        erros = validar_invariantes(resultado)
        self.assertTrue(any("não foi autopreenchido" in erro for erro in erros))

    def test_rejects_autofill_with_wrong_family(self):
        resultado = {
            "autopreencher": True,
            "sugestoes_consumo": {"tipo": "gasolina"},
            "diagnostico": {"ambiguidade_proxima": False},
            "debug": {
                "candidatos_top": [{
                    "token_forte_divergente": True,
                    "familia_textual_divergente": False,
                }]
            },
        }
        erros = validar_invariantes(resultado)
        self.assertTrue(any("família/modelo divergente" in erro for erro in erros))

    def test_conservative_match_has_explicit_memory(self):
        resultado = {
            "autopreencher": True,
            "criterio_match": "conservador_por_familia",
            "sugestoes_consumo": {
                "tipo": "gasolina",
                "criterio_conservador_versoes_compativeis": True,
            },
            "diagnostico": {"ambiguidade_proxima": False},
            "debug": {"candidatos_top": [{}]},
        }
        self.assertEqual(validar_invariantes(resultado), [])


if __name__ == "__main__":
    unittest.main()
