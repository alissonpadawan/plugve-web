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

    def _marcas_bloqueadas_path(self) -> Path:
        return self._cache_dir() / "marcas_bloqueadas.json"

    def _ler_marcas_bloqueadas(self) -> dict:
        path = self._marcas_bloqueadas_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _salvar_marcas_bloqueadas(self, dados: dict) -> None:
        path = self._marcas_bloqueadas_path()
        path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def marca_bloqueada(self, codigo_marca: str) -> bool:
        return str(codigo_marca) in set(map(str, self._ler_marcas_bloqueadas().keys()))

    def bloquear_marca_antiga(self, codigo_marca: str, nome_marca: str = "", motivo: str = "sem_modelos_2012_ou_zero_km") -> dict:
        dados = self._ler_marcas_bloqueadas()
        marca_key = str(codigo_marca)
        dados[marca_key] = {
            "codigo_marca": marca_key,
            "marca": nome_marca,
            "motivo": motivo,
        }
        self._salvar_marcas_bloqueadas(dados)
        return {"ok": True, "marca_bloqueada": dados[marca_key]}

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

        marca_bloqueada = False
        try:
            modelos_data = self._get_json(f"marcas/{marca_key}/modelos")
            modelos = modelos_data.get("modelos", []) if isinstance(modelos_data, dict) else []
            codigos_modelos = {str(m.get("codigo")) for m in modelos if m.get("codigo") is not None}
            bloqueados_marca = set(map(str, dados.get(marca_key, {}).keys()))
            if codigos_modelos and codigos_modelos.issubset(bloqueados_marca):
                self.bloquear_marca_antiga(marca_key, nome_marca, "todos_modelos_sem_ano_2012_ou_zero_km")
                marca_bloqueada = True
        except Exception:
            marca_bloqueada = False

        return {"ok": True, "bloqueado": dados[marca_key][modelo_key], "marca_bloqueada": marca_bloqueada}

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
        marcas = self._get_json("marcas")
        bloqueadas = self._ler_marcas_bloqueadas()
        if not bloqueadas or not isinstance(marcas, list):
            return marcas
        return [m for m in marcas if str(m.get("codigo")) not in bloqueadas]

    def listar_modelos(self, codigo_marca: str, filtrar_bloqueados: bool = True):
        data = self._get_json(f"marcas/{codigo_marca}/modelos")
        if not filtrar_bloqueados:
            return data
        bloqueados = self._ler_bloqueados().get(str(codigo_marca), {})
        modelos = data.get("modelos", []) if isinstance(data, dict) else []
        if not bloqueados:
            return data
        data = dict(data)
        data["modelos"] = [m for m in modelos if str(m.get("codigo")) not in bloqueados]
        data["modelos_bloqueados_ocultos"] = len(modelos) - len(data["modelos"])

        # Se todos os modelos da marca já foram bloqueados por não terem Zero km
        # nem ano/modelo >= 2012, a própria marca vira ruído para o usuário.
        # Ela é bloqueada para não aparecer mais no seletor de marcas.
        if modelos and not data["modelos"]:
            nome_marca = ""
            for marca in self._get_json("marcas"):
                if str(marca.get("codigo")) == str(codigo_marca):
                    nome_marca = marca.get("nome", "")
                    break
            self.bloquear_marca_antiga(str(codigo_marca), nome_marca)
            data["marca_bloqueada"] = True
        return data

    def listar_anos(self, codigo_marca: str, codigo_modelo: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos")

    def consultar_preco(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str):
        return self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}")
