from __future__ import annotations

import json
import requests
from functools import lru_cache
from pathlib import Path
from flask import current_app


class FipeService:
    def _cache_dir(self) -> Path:
        path = current_app.config["DATA_DIR"] / "fipe_cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _bloqueados_path(self) -> Path:
        return self._cache_dir() / "modelos_bloqueados.json"

    def _ler_bloqueados(self) -> dict:
        path = self._bloqueados_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _salvar_bloqueados(self, dados: dict) -> None:
        path = self._bloqueados_path()
        path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def modelo_bloqueado(self, codigo_marca: str, codigo_modelo: str) -> bool:
        dados = self._ler_bloqueados()
        return str(codigo_modelo) in set(map(str, dados.get(str(codigo_marca), {}).keys()))

    def bloquear_modelo_antigo(self, codigo_marca: str, codigo_modelo: str, nome_marca: str = "", nome_modelo: str = "", motivo: str = "sem_ano_2012_ou_zero_km") -> dict:
        dados = self._ler_bloqueados()
        marca_key = str(codigo_marca)
        modelo_key = str(codigo_modelo)
        dados.setdefault(marca_key, {})[modelo_key] = {
            "codigo_marca": marca_key,
            "codigo_modelo": modelo_key,
            "marca": nome_marca,
            "modelo": nome_modelo,
            "motivo": motivo,
        }
        self._salvar_bloqueados(dados)
        return {"ok": True, "bloqueado": dados[marca_key][modelo_key]}

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

    def listar_modelos(self, codigo_marca: str, filtrar_bloqueados: bool = True):
        data = self._get_json(f"marcas/{codigo_marca}/modelos")
        if not filtrar_bloqueados:
            return data
        bloqueados = self._ler_bloqueados().get(str(codigo_marca), {})
        if not bloqueados:
            return data
        modelos = data.get("modelos", []) if isinstance(data, dict) else []
        data = dict(data)
        data["modelos"] = [m for m in modelos if str(m.get("codigo")) not in bloqueados]
        data["modelos_bloqueados_ocultos"] = len(modelos) - len(data["modelos"])
        return data

    def listar_anos(self, codigo_marca: str, codigo_modelo: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos")

    def consultar_preco(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}")
