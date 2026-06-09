from __future__ import annotations

import requests
from functools import lru_cache
from flask import current_app


class FipeService:
    def _base_url(self) -> str:
        return current_app.config["FIPE_BASE_URL"]

    def _timeout(self) -> int:
        return int(current_app.config.get("REQUEST_TIMEOUT", 15))

    def _get_json(self, endpoint: str):
        return self._get_json_cached(self._base_url(), endpoint, self._timeout())

    @staticmethod
    @lru_cache(maxsize=512)
    def _get_json_cached(base_url: str, endpoint: str, timeout: int):
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def listar_marcas(self):
        return self._get_json("marcas")

    def listar_modelos(self, codigo_marca: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos")

    def listar_anos(self, codigo_marca: str, codigo_modelo: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos")

    def consultar_preco(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}")
