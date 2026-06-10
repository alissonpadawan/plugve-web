from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from flask import current_app

from core.modelos import VeiculoSelecionado
from services.text_utils import parse_float_seguro


SLEEP_API = 0.10
MAX_RETRIES_API = 2


class FipeHistoricoService:
    """Cliente para montar histórico FIPE mensal usando a API v2/fipe.online.

    Importante V23:
    - Não usa mais veiculos.fipe.org.br/api/veiculos, pois esse endpoint retornou 403.
    - Usa /references e /cars/brands/{brand}/models/{model}/years/{year}
      com query parameter reference, sempre com X-Subscription-Token quando houver.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    def montar_historico_mensal(self, veiculo: VeiculoSelecionado, limite_meses: int = 84) -> list[dict[str, Any]]:
        if not veiculo.codigo_marca or not veiculo.codigo_modelo or not veiculo.codigo_ano:
            raise ValueError("Códigos FIPE incompletos para baixar histórico sob demanda.")

        referencias = self._consultar_referencias()
        if not referencias:
            raise ValueError("Não foi possível obter referências mensais da FIPE API v2.")

        refs_consulta = referencias[-max(3, int(limite_meses)):]
        historico: dict[str, dict[str, Any]] = {}

        for ref in refs_consulta:
            try:
                detalhe = self._consultar_valor_v2(
                    codigo_marca=str(veiculo.codigo_marca),
                    codigo_modelo=str(veiculo.codigo_modelo),
                    codigo_ano=str(veiculo.codigo_ano),
                    referencia=ref["codigo_tabela_referencia"],
                )
                valor = parse_float_seguro(detalhe.get("price") or detalhe.get("Valor"), 0.0)
                if valor <= 0:
                    continue

                data_ref = ref["data_referencia"]
                historico[data_ref] = {
                    "data_referencia": data_ref,
                    "valor_fipe": round(float(valor), 2),
                    "codigo_fipe": str(detalhe.get("codeFipe") or detalhe.get("CodigoFipe") or veiculo.codigo_fipe or "").strip(),
                    "marca": str(detalhe.get("brand") or detalhe.get("Marca") or veiculo.marca or "").strip(),
                    "modelo": str(detalhe.get("model") or detalhe.get("Modelo") or veiculo.modelo or "").strip(),
                    "ano_modelo": str(detalhe.get("modelYear") or detalhe.get("AnoModelo") or veiculo.ano_modelo or "").strip(),
                    "combustivel": str(detalhe.get("fuel") or detalhe.get("Combustivel") or veiculo.combustivel or "").strip(),
                    "codigo_marca": str(veiculo.codigo_marca),
                    "codigo_modelo": str(veiculo.codigo_modelo),
                    "codigo_ano": str(veiculo.codigo_ano),
                    "referencia": str(ref.get("codigo_tabela_referencia", "")),
                    "origem": "fipe_api_v2_referencia_mensal",
                }
            except Exception:
                # Alguns meses realmente não possuem esse veículo; isso não deve derrubar o fluxo.
                continue

        saida = list(historico.values())
        saida.sort(key=lambda x: str(x.get("data_referencia", "")))
        return saida

    def listar_codigos_ano_usados_mesmo_modelo(self, veiculo: VeiculoSelecionado) -> list[dict[str, Any]]:
        if not veiculo.codigo_marca or not veiculo.codigo_modelo:
            return []

        try:
            anos = self._get_json_v2(f"cars/brands/{veiculo.codigo_marca}/models/{veiculo.codigo_modelo}/years")
        except Exception:
            return []

        combustivel_alvo = ""
        partes_atual = str(veiculo.codigo_ano or "").split("-", 1)
        if len(partes_atual) == 2:
            combustivel_alvo = partes_atual[1].strip()

        candidatos: list[dict[str, Any]] = []
        for item in anos or []:
            codigo = str(item.get("code", item.get("codigo", "")) or "").strip()
            nome = str(item.get("name", item.get("nome", "")) or "").strip()
            partes = codigo.split("-", 1)
            if len(partes) != 2:
                continue
            ano_txt, combustivel_txt = partes[0].strip(), partes[1].strip()
            if ano_txt == "32000" or not ano_txt.isdigit():
                continue
            mesmo_combustivel = bool(combustivel_alvo and combustivel_txt == combustivel_alvo)
            candidatos.append({
                "codigo_ano": codigo,
                "nome": nome,
                "ano_modelo": int(ano_txt),
                "codigo_combustivel": combustivel_txt,
                "mesmo_combustivel": mesmo_combustivel,
            })

        candidatos.sort(key=lambda x: (0 if x["mesmo_combustivel"] else 1, -int(x["ano_modelo"])))
        return candidatos

    def _api_root(self) -> str:
        base = str(current_app.config.get("FIPE_BASE_URL") or "https://fipe.parallelum.com.br/api/v2/cars").rstrip("/")
        if base.endswith("/cars"):
            return base[:-5]
        return base.rsplit("/cars", 1)[0] if "/cars" in base else base

    def _token(self) -> str:
        token = os.environ.get("FIPE_TOKEN", "").strip()
        if token:
            return token
        try:
            token_file = Path(current_app.config["PERSISTENT_DIR"]) / "fipe_token.txt"
            if token_file.exists():
                return token_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        token = self._token()
        if token:
            headers["X-Subscription-Token"] = token
        return headers

    def _get_json_v2(self, endpoint: str, params: dict[str, Any] | None = None):
        url = f"{self._api_root().rstrip('/')}/{endpoint.strip('/')}"
        timeout = int(current_app.config.get("REQUEST_TIMEOUT", 15))
        ultimo_erro = None
        for tentativa in range(1, MAX_RETRIES_API + 1):
            try:
                # Também conta estas consultas no contador provisório da aba técnica.
                try:
                    from services.fipe_service import FipeService
                    cache_dir = Path(current_app.config.get("FIPE_CACHE_DIR") or (current_app.config["PERSISTENT_DIR"] / "fipe_cache"))
                    FipeService._registrar_requisicao_static(cache_dir, token_ativo=bool(self._token()))
                except Exception:
                    pass

                resp = self.session.get(url, params=params or {}, headers=self._headers(), timeout=timeout)
                if resp.status_code >= 400:
                    try:
                        from services.fipe_service import FipeService
                        cache_dir = Path(current_app.config.get("FIPE_CACHE_DIR") or (current_app.config["PERSISTENT_DIR"] / "fipe_cache"))
                        FipeService._registrar_erro_static(cache_dir, resp.status_code, url, resp.text[:300])
                    except Exception:
                        pass
                resp.raise_for_status()
                time.sleep(SLEEP_API)
                return resp.json()
            except Exception as exc:
                ultimo_erro = exc
                if tentativa < MAX_RETRIES_API:
                    time.sleep(0.35 * tentativa)
                else:
                    raise ultimo_erro

    def _consultar_referencias(self) -> list[dict[str, Any]]:
        payload = self._get_json_v2("references")
        itens = self._normalizar_lista(payload)
        saida = []
        for item in itens:
            codigo = item.get("code", item.get("Codigo"))
            mes = str(item.get("month", item.get("Mes", ""))).strip()
            data_ref = self._parse_mes_ano(mes)
            if codigo is None or data_ref is None:
                continue
            try:
                codigo_int = int(str(codigo))
            except Exception:
                continue
            saida.append({
                "codigo_tabela_referencia": codigo_int,
                "mes_referencia": mes,
                "data_referencia": data_ref.strftime("%Y-%m"),
            })
        # Ordenar por data, não pelo código, para garantir janela cronológica.
        saida.sort(key=lambda x: x["data_referencia"])
        return saida

    def _consultar_valor_v2(self, *, codigo_marca: str, codigo_modelo: str, codigo_ano: str, referencia: int):
        return self._get_json_v2(
            f"cars/brands/{codigo_marca}/models/{codigo_modelo}/years/{codigo_ano}",
            params={"reference": int(referencia)},
        )

    @staticmethod
    def _normalizar_lista(payload):
        if payload is None:
            return []
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for chave in ("d", "items", "Items", "result", "results"):
                valor = payload.get(chave)
                if isinstance(valor, list):
                    return [x for x in valor if isinstance(x, dict)]
                if isinstance(valor, str):
                    try:
                        obj = json.loads(valor)
                    except Exception:
                        obj = None
                    if isinstance(obj, list):
                        return [x for x in obj if isinstance(x, dict)]
            return [payload]
        return []

    @staticmethod
    def _parse_mes_ano(texto: str) -> datetime | None:
        txt = str(texto).strip().lower()
        trocas = {
            "á": "a", "à": "a", "ã": "a", "â": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u", "ç": "c",
        }
        for a, b in trocas.items():
            txt = txt.replace(a, b)
        meses = {
            "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
        }
        import re
        m = re.search(r"([a-z]+)\s+de\s+((?:19|20)\d{2})", txt)
        if not m:
            m = re.search(r"([a-z]+)/((?:19|20)\d{2})", txt)
        if not m:
            return None
        mes = meses.get(m.group(1).strip())
        ano = int(m.group(2))
        if not mes:
            return None
        return datetime(ano, mes, 1)
