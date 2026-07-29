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


class AneelOperationalHotfixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = Path(self.tmp.name) / "aneel_cache" / "tarifas_b1.json"
        self.old_cache_file = energia.ANEEL_CACHE_FILE
        self.old_budget = energia.ANEEL_TOTAL_BUDGET_SECONDS
        energia.ANEEL_CACHE_FILE = self.cache_path
        energia.ANEEL_TOTAL_BUDGET_SECONDS = 8.0
        self._reset_state()

    def tearDown(self):
        energia.ANEEL_CACHE_FILE = self.old_cache_file
        energia.ANEEL_TOTAL_BUDGET_SECONDS = self.old_budget
        self._reset_state()

    @staticmethod
    def _reset_state():
        with energia._ANEEL_CACHE_LOCK:
            energia._ANEEL_CACHE_CARREGADO = False
            energia._ANEEL_CACHE_MEMORIA = {}
            energia._ANEEL_FALHA_ATE = {}

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

    def test_success_is_persisted_and_second_call_uses_official_cache(self):
        response = _FakeResponse({"success": True, "result": {"records": [self._record()]}})
        with patch.object(energia.requests, "post", return_value=response) as post, patch.object(
            energia.requests, "get"
        ) as get:
            first = energia.obter_tarifa_energia_por_distribuidora("Equatorial GO")
            second = energia.obter_tarifa_energia_por_distribuidora("Equatorial GO")

        self.assertEqual(first["tarifa_base_kwh"], 0.89181)
        self.assertEqual(second["tarifa_base_kwh"], 0.89181)
        self.assertEqual(second["_cache_status"], "fresh")
        self.assertEqual(post.call_count, 1)
        get.assert_not_called()
        self.assertTrue(self.cache_path.exists())
        saved = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("EQUATORIAL GO", saved["tarifas"])

    def test_network_failure_returns_local_fallback_and_opens_cooldown(self):
        def fail(*args, **kwargs):
            raise requests.Timeout("simulated timeout")

        with patch.object(energia.requests, "post", side_effect=fail) as post, patch.object(
            energia.requests, "get", side_effect=fail
        ) as get, patch.object(
            energia, "obter_distribuidora_por_municipio", return_value="Equatorial GO"
        ):
            first = energia.obter_tarifa_energia("GO", "Goiânia")
            calls_after_first = post.call_count + get.call_count
            second = energia.obter_tarifa_energia("GO", "Goiânia")

        self.assertEqual(first["tarifa_kwh"], 0.86)
        self.assertIn("estimativa local", first["mensagem"].lower())
        self.assertEqual(second["tarifa_kwh"], 0.86)
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(post.call_count + get.call_count, calls_after_first)

    def test_stale_official_cache_is_used_when_aneel_is_unavailable(self):
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

        impostos = {"icms": 10.0, "pis": 1.0, "cofins": 2.0}
        with patch.object(energia.requests, "post", side_effect=fail), patch.object(
            energia.requests, "get", side_effect=fail
        ), patch.object(
            energia, "obter_distribuidora_por_municipio", return_value="Equatorial GO"
        ), patch.object(
            energia, "obter_impostos_por_uf", return_value=impostos
        ):
            result = energia.obter_tarifa_energia("GO", "Goiânia")

        self.assertAlmostEqual(result["tarifa_kwh"], round(0.89181 * 1.13, 5))
        self.assertIn("último valor oficial aneel", result["mensagem"].lower())
        self.assertEqual(result["detalhe"]["tusd_kwh"], 0.56767)

    def test_request_timeouts_are_below_gunicorn_limit(self):
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
