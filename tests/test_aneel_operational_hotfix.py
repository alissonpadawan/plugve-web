from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from services import energia_service as energia


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class AneelOriginalCalculationOperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = Path(self.tmp.name) / "aneel_cache" / "tarifas_b1.json"
        self.old_cache_file = energia.ANEEL_CACHE_FILE
        self.old_budget = energia.ANEEL_TOTAL_BUDGET_SECONDS
        self.old_cooldown = energia.ANEEL_FAILURE_COOLDOWN_SECONDS
        energia.ANEEL_CACHE_FILE = self.cache_path
        energia.ANEEL_TOTAL_BUDGET_SECONDS = 8.0
        energia.ANEEL_FAILURE_COOLDOWN_SECONDS = 60.0
        self._reset_state()

    def tearDown(self):
        energia.ANEEL_CACHE_FILE = self.old_cache_file
        energia.ANEEL_TOTAL_BUDGET_SECONDS = self.old_budget
        energia.ANEEL_FAILURE_COOLDOWN_SECONDS = self.old_cooldown
        self._reset_state()

    @staticmethod
    def _reset_state():
        with energia._ANEEL_CACHE_LOCK:
            energia._ANEEL_CACHE_CARREGADO = False
            energia._ANEEL_CACHE_MEMORIA = {}
            energia._ANEEL_FALHA_ATE = {}
        energia.carregar_df_municipios.cache_clear()
        energia.carregar_impostos_uf.cache_clear()

    @staticmethod
    def _record():
        return {
            "SigAgente": "Equatorial GO",
            "DscSubGrupo": "B1",
            "DscClasse": "Residencial",
            "DscModalidadeTarifaria": "Convencional",
            "DscSubClasse": "Residencial",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscDetalhe": "Não se aplica",
            "DscUnidadeTerciaria": "MWH",
            "VlrTUSD": "567.67",
            "VlrTE": "324.14",
            "DatInicioVigencia": "2026-01-01",
            "DatFimVigencia": "2026-12-31",
        }

    def test_goiania_uses_original_spreadsheet_mapping_and_state_taxes(self):
        self.assertEqual(energia.obter_distribuidora_por_municipio("GO", "Goiânia"), "EQUATORIAL GO")
        self.assertEqual(
            energia.obter_impostos_por_uf("GO"),
            {"icms": 19.0, "pis": 1.65, "cofins": 7.6},
        )
        self.assertEqual(
            energia.calcular_tarifa_com_impostos(0.89181, "GO")["tarifa_total_kwh"],
            1.14375,
        )

    def test_live_official_components_reproduce_original_go_calculation(self):
        response = _FakeResponse({"success": True, "result": {"records": [self._record()]}})
        with patch.object(energia.requests, "post", return_value=response) as post, patch.object(
            energia.requests, "get"
        ) as get:
            result = energia.obter_tarifa_energia("GO", "Goiânia")

        self.assertEqual(result["distribuidora"], "EQUATORIAL GO")
        self.assertEqual(result["tarifa_base_kwh"], 0.89181)
        self.assertEqual(result["tarifa_kwh"], 1.14375)
        self.assertEqual(result["detalhe"]["tusd_kwh"], 0.56767)
        self.assertEqual(result["detalhe"]["te_kwh"], 0.32414)
        self.assertEqual(result["detalhe"]["icms_pct"], 19.0)
        self.assertEqual(result["detalhe"]["pis_pct"], 1.65)
        self.assertEqual(result["detalhe"]["cofins_pct"], 7.6)
        self.assertTrue(result["fonte_oficial"])
        self.assertEqual(post.call_count, 1)
        get.assert_not_called()

    def test_cache_persists_only_official_components_and_reapplies_uf_taxes(self):
        response = _FakeResponse({"success": True, "result": {"records": [self._record()]}})
        with patch.object(energia.requests, "post", return_value=response), patch.object(
            energia.requests, "get"
        ):
            energia.obter_tarifa_energia("GO", "Goiânia")

        saved = json.loads(self.cache_path.read_text(encoding="utf-8"))
        cached_data = saved["tarifas"]["EQUATORIAL GO"]["dados"]
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(cached_data["tarifa_base_kwh"], 0.89181)
        self.assertNotIn("tarifa_total_kwh", cached_data)
        self.assertNotIn("icms_pct", cached_data)
        self.assertNotIn("pis_pct", cached_data)
        self.assertNotIn("cofins_pct", cached_data)

        # O mesmo componente oficial precisa produzir totais distintos quando a UF muda.
        with patch.object(energia, "obter_distribuidora_por_municipio", return_value="Equatorial GO"), patch.object(
            energia, "obter_impostos_por_uf", return_value={"icms": 10.0, "pis": 1.0, "cofins": 2.0}
        ):
            outra_uf = energia.obter_tarifa_energia("XX", "Município")
        self.assertEqual(outra_uf["tarifa_kwh"], round(0.89181 * 1.13, 5))

    def test_existing_package06_cache_is_compatible_but_taxes_are_recalculated(self):
        cached = {
            "sigagente": "Equatorial GO",
            "tarifa_base_kwh": 0.89181,
            "tusd_kwh": 0.56767,
            "te_kwh": 0.32414,
            "inicio_vig": "2026-01-01",
            "fim_vig": "2026-12-31",
            "base_tarifaria": "Tarifa de Aplicação",
            "detalhe": "Não se aplica",
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tarifas": {
                        "EQUATORIAL GO": {"salvo_em": time.time(), "dados": cached}
                    },
                }
            ),
            encoding="utf-8",
        )
        self._reset_state()

        with patch.object(energia.requests, "post") as post, patch.object(energia.requests, "get") as get:
            result = energia.obter_tarifa_energia("GO", "Goiânia")

        self.assertEqual(result["tarifa_kwh"], 1.14375)
        self.assertTrue(result["fonte_oficial"])
        post.assert_not_called()
        get.assert_not_called()

    def test_network_failure_without_official_cache_does_not_masquerade_fixed_value_as_aneel(self):
        def fail(*args, **kwargs):
            raise requests.Timeout("simulated timeout")

        with patch.object(energia.requests, "post", side_effect=fail) as post, patch.object(
            energia.requests, "get", side_effect=fail
        ) as get:
            first = energia.obter_tarifa_energia("GO", "Goiânia")
            calls_after_first = post.call_count + get.call_count
            second = energia.obter_tarifa_energia("GO", "Goiânia")

        self.assertIsNone(first["tarifa_kwh"])
        self.assertFalse(first["fonte_oficial"])
        self.assertIsNone(first["detalhe"])
        self.assertIsNone(second["tarifa_kwh"])
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(post.call_count + get.call_count, calls_after_first)

    def test_stale_official_components_are_used_and_state_taxes_reapplied(self):
        cached = {
            "sigagente": "Equatorial GO",
            "tarifa_base_kwh": 0.89181,
            "tusd_kwh": 0.56767,
            "te_kwh": 0.32414,
            "inicio_vig": "2026-01-01",
            "fim_vig": "2026-12-31",
            "base_tarifaria": "Tarifa de Aplicação",
            "detalhe": "Não se aplica",
        }
        energia._ANEEL_CACHE_CARREGADO = True
        energia._ANEEL_CACHE_MEMORIA = {
            "EQUATORIAL GO": {
                "salvo_em": time.time() - energia.ANEEL_CACHE_TTL_SECONDS - 10,
                "dados": cached,
            }
        }

        def fail(*args, **kwargs):
            raise requests.Timeout("simulated timeout")

        with patch.object(energia.requests, "post", side_effect=fail), patch.object(
            energia.requests, "get", side_effect=fail
        ), patch.object(
            energia, "obter_distribuidora_por_municipio", return_value="Equatorial GO"
        ), patch.object(
            energia, "obter_impostos_por_uf", return_value={"icms": 10.0, "pis": 1.0, "cofins": 2.0}
        ):
            result = energia.obter_tarifa_energia("XX", "Município")

        self.assertEqual(result["tarifa_kwh"], round(0.89181 * 1.13, 5))
        self.assertTrue(result["fonte_oficial"])
        self.assertIn("componentes oficiais", result["mensagem"].lower())

    def test_request_timeouts_remain_below_gunicorn_limit(self):
        captured = []

        def fail(*args, **kwargs):
            captured.append(kwargs["timeout"])
            raise requests.Timeout("simulated timeout")

        deadline = time.monotonic() + 8.0
        with patch.object(energia.requests, "post", side_effect=fail), patch.object(
            energia.requests, "get", side_effect=fail
        ):
            result = energia._aneel_datastore_search({"resource_id": "x"}, deadline=deadline)

        self.assertIsNone(result)
        self.assertEqual(len(captured), 2)
        for timeout in captured:
            self.assertLessEqual(float(timeout.total), 8.0)
            self.assertLessEqual(float(timeout.connect_timeout), 2.0)
            self.assertLessEqual(float(timeout.read_timeout), 4.0)


if __name__ == "__main__":
    unittest.main()
