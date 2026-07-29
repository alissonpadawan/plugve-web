from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from services.pbev_matching_v46.matcher import PbevMultiviewMatcher


class _FakeService:
    @staticmethod
    def _marca_key(value):
        return str(value or "").strip().upper()


class PbevMatchingV46BrandCacheTests(unittest.TestCase):
    def setUp(self):
        self.previous_prepare = os.environ.get("PLUGVE_PBEV_V46_PREPARE_BY_BRAND")
        self.previous_limit = os.environ.get("PLUGVE_PBEV_V46_BRAND_CACHE_SIZE")

    def tearDown(self):
        if self.previous_prepare is None:
            os.environ.pop("PLUGVE_PBEV_V46_PREPARE_BY_BRAND", None)
        else:
            os.environ["PLUGVE_PBEV_V46_PREPARE_BY_BRAND"] = self.previous_prepare
        if self.previous_limit is None:
            os.environ.pop("PLUGVE_PBEV_V46_BRAND_CACHE_SIZE", None)
        else:
            os.environ["PLUGVE_PBEV_V46_BRAND_CACHE_SIZE"] = self.previous_limit

    @staticmethod
    def _record(record_id: str, brand: str, model: str):
        return {
            "id_pbev_preliminar": record_id,
            "marca_normalizada": brand,
            "modelo_normalizado": model,
            "versao_normalizada": "1.0 AUTO",
            "motor_normalizado": "1.0",
            "transmissao_normalizada": "AUTO",
            "tipo_propulsao_normalizado": "COMBUSTAO",
            "combustivel_normalizado": "GASOLINA",
            "ano_tabela": 2026,
        }

    def _cache(self, *, mtime=1.0):
        records = [
            self._record("a1", "A", "ALFA"),
            self._record("a2", "A", "ALFA PLUS"),
            self._record("b1", "B", "BETA"),
            self._record("b2", "B", "BETA PLUS"),
            self._record("c1", "C", "GAMA"),
        ]
        index = {
            "A": records[0:2],
            "B": records[2:4],
            "C": records[4:5],
        }
        return SimpleNamespace(path="base.json", mtime=mtime, registros=records, indice_marca=index)

    def test_default_prepares_only_requested_brand(self):
        os.environ.pop("PLUGVE_PBEV_V46_PREPARE_BY_BRAND", None)
        os.environ["PLUGVE_PBEV_V46_BRAND_CACHE_SIZE"] = "2"
        matcher = PbevMultiviewMatcher(_FakeService())
        cache = self._cache()

        matcher._prepare_records(
            cache,
            brand_key="A",
            brand_keys=["A"],
            records=cache.indice_marca["A"],
        )

        self.assertEqual(set(matcher._record_cache), {"a1", "a2"})
        self.assertEqual(set(matcher._idf_by_brand), {"A"})
        self.assertFalse(matcher._prepared_globally)

    def test_lru_evicts_old_brand_scope(self):
        os.environ["PLUGVE_PBEV_V46_PREPARE_BY_BRAND"] = "1"
        os.environ["PLUGVE_PBEV_V46_BRAND_CACHE_SIZE"] = "2"
        matcher = PbevMultiviewMatcher(_FakeService())
        cache = self._cache()

        for brand in ("A", "B", "C"):
            matcher._prepare_records(
                cache,
                brand_key=brand,
                brand_keys=[brand],
                records=cache.indice_marca[brand],
            )

        self.assertEqual(list(matcher._brand_scopes), ["B", "C"])
        self.assertEqual(set(matcher._record_cache), {"b1", "b2", "c1"})
        self.assertEqual(set(matcher._idf_by_brand), {"B", "C"})

    def test_environment_variable_restores_global_preparation(self):
        os.environ["PLUGVE_PBEV_V46_PREPARE_BY_BRAND"] = "0"
        matcher = PbevMultiviewMatcher(_FakeService())
        cache = self._cache()

        matcher._prepare_records(
            cache,
            brand_key="A",
            brand_keys=["A"],
            records=cache.indice_marca["A"],
        )

        self.assertEqual(len(matcher._record_cache), len(cache.registros))
        self.assertEqual(set(matcher._idf_by_brand), {"A", "B", "C"})
        self.assertTrue(matcher._prepared_globally)

    def test_base_change_invalidates_prepared_scopes(self):
        os.environ["PLUGVE_PBEV_V46_PREPARE_BY_BRAND"] = "1"
        matcher = PbevMultiviewMatcher(_FakeService())
        first = self._cache(mtime=1.0)
        second = self._cache(mtime=2.0)

        matcher._prepare_records(
            first,
            brand_key="A",
            brand_keys=["A"],
            records=first.indice_marca["A"],
        )
        matcher._prepare_records(
            second,
            brand_key="B",
            brand_keys=["B"],
            records=second.indice_marca["B"],
        )

        self.assertEqual(list(matcher._brand_scopes), ["B"])
        self.assertEqual(set(matcher._record_cache), {"b1", "b2"})
        self.assertEqual(set(matcher._idf_by_brand), {"B"})


if __name__ == "__main__":
    unittest.main()
