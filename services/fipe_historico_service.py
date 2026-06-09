from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import requests
from flask import current_app

from core.modelos import VeiculoSelecionado
from services.text_utils import parse_float_seguro


FIPE_WEB_BASE = "https://veiculos.fipe.org.br/api/veiculos"
HEADERS_WEB = {
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://veiculos.fipe.org.br/",
    "Origin": "https://veiculos.fipe.org.br",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}
CODIGO_TIPO_VEICULO_WEB = 1
SLEEP_WEB = 0.08
MAX_RETRIES_WEB = 2


class FipeHistoricoService:
    """Cliente mínimo para baixar histórico mensal direto da FIPE web.

    Esta classe fica separada do FipeService público porque o endpoint usado
    para histórico é outro: veiculos.fipe.org.br/api/veiculos.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS_WEB)

    def montar_historico_mensal(self, veiculo: VeiculoSelecionado, limite_meses: int = 48) -> list[dict[str, Any]]:
        if not veiculo.codigo_marca or not veiculo.codigo_modelo or not veiculo.codigo_ano:
            raise ValueError("Códigos FIPE incompletos para baixar histórico sob demanda.")

        ano_str, codigo_combustivel, ano_modelo = self._parse_codigo_ano(veiculo.codigo_ano)
        referencias = self._consultar_referencias()
        if not referencias:
            raise ValueError("Não foi possível obter referências mensais da FIPE.")

        # Referências vêm ordenadas da mais antiga para a mais nova.
        refs_consulta = referencias[-max(3, int(limite_meses)):]
        historico: dict[str, dict[str, Any]] = {}

        for ref in refs_consulta:
            try:
                detalhe = self._consultar_valor(
                    codigo_tabela_referencia=int(ref["codigo_tabela_referencia"]),
                    codigo_marca=str(veiculo.codigo_marca),
                    codigo_modelo=str(veiculo.codigo_modelo),
                    ano_str=ano_str,
                    codigo_tipo_combustivel=codigo_combustivel,
                    ano_modelo=ano_modelo,
                )
                valor = parse_float_seguro(detalhe.get("Valor"), 0.0)
                if valor <= 0:
                    continue

                data_ref = ref["data_referencia"]
                historico[data_ref] = {
                    "data_referencia": data_ref,
                    "valor_fipe": round(float(valor), 2),
                    "codigo_fipe": str(detalhe.get("CodigoFipe") or veiculo.codigo_fipe or "").strip(),
                    "marca": str(detalhe.get("Marca") or veiculo.marca or "").strip(),
                    "modelo": str(detalhe.get("Modelo") or veiculo.modelo or "").strip(),
                    "ano_modelo": str(detalhe.get("AnoModelo") or veiculo.ano_modelo or "").strip(),
                    "combustivel": str(detalhe.get("Combustivel") or veiculo.combustivel or "").strip(),
                    "codigo_marca": str(veiculo.codigo_marca),
                    "codigo_modelo": str(veiculo.codigo_modelo),
                    "codigo_ano": str(veiculo.codigo_ano),
                    "origem": "fipe_web_sob_demanda",
                }
            except Exception:
                # Alguns meses podem não ter aquele ano/modelo/combustível.
                # O fluxo não deve morrer por causa de um mês isolado.
                continue

        saida = list(historico.values())
        saida.sort(key=lambda x: str(x.get("data_referencia", "")))
        return saida



    def listar_codigos_ano_usados_mesmo_modelo(self, veiculo: VeiculoSelecionado) -> list[dict[str, Any]]:
        """Lista anos usados do mesmo modelo para servir como proxy de zero km.

        Preferimos o mesmo código de combustível do veículo selecionado e
        ignoramos o código 32000, porque ele representa zero km/tabela do novo.
        """
        if not veiculo.codigo_marca or not veiculo.codigo_modelo:
            return []

        url = f"https://parallelum.com.br/fipe/api/v1/carros/marcas/{veiculo.codigo_marca}/modelos/{veiculo.codigo_modelo}/anos"
        timeout = int(current_app.config.get("REQUEST_TIMEOUT", 15))
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            resp.raise_for_status()
            anos = resp.json()
        except Exception:
            return []

        combustivel_alvo = ""
        partes_atual = str(veiculo.codigo_ano or "").split("-", 1)
        if len(partes_atual) == 2:
            combustivel_alvo = partes_atual[1].strip()

        candidatos: list[dict[str, Any]] = []
        for item in anos or []:
            codigo = str(item.get("codigo", "") or "").strip()
            nome = str(item.get("nome", "") or "").strip()
            partes = codigo.split("-", 1)
            if len(partes) != 2:
                continue
            ano_txt, combustivel_txt = partes[0].strip(), partes[1].strip()
            if ano_txt == "32000":
                continue
            if not ano_txt.isdigit():
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

    def _post(self, endpoint: str, payload: dict[str, Any] | None = None):
        url = f"{FIPE_WEB_BASE}/{endpoint}"
        ultimo_erro = None
        timeout = int(current_app.config.get("REQUEST_TIMEOUT", 15))

        for tentativa in range(1, MAX_RETRIES_WEB + 1):
            try:
                resp = self.session.post(url, json=payload or {}, timeout=timeout)
                resp.raise_for_status()
                dados = resp.json()
                time.sleep(SLEEP_WEB)
                return dados
            except Exception as exc:
                ultimo_erro = exc
                if tentativa < MAX_RETRIES_WEB:
                    time.sleep(0.4 * tentativa)
                else:
                    raise ultimo_erro

    def _consultar_referencias(self) -> list[dict[str, Any]]:
        payload = self._post("ConsultarTabelaDeReferencia")
        itens = self._normalizar_lista(payload)
        saida = []
        for item in itens:
            codigo = item.get("Codigo")
            mes = str(item.get("Mes", "")).strip()
            data_ref = self._parse_mes_ano_dropdown(mes)
            if codigo is None or data_ref is None:
                continue
            saida.append({
                "codigo_tabela_referencia": int(codigo),
                "mes_referencia": mes,
                "data_referencia": data_ref.strftime("%Y-%m"),
            })
        saida.sort(key=lambda x: x["data_referencia"])
        return saida

    def _consultar_valor(
        self,
        *,
        codigo_tabela_referencia: int,
        codigo_marca: str,
        codigo_modelo: str,
        ano_str: str,
        codigo_tipo_combustivel: int,
        ano_modelo: int,
    ):
        return self._post(
            "ConsultarValorComTodosParametros",
            {
                "codigoTabelaReferencia": codigo_tabela_referencia,
                "codigoTipoVeiculo": CODIGO_TIPO_VEICULO_WEB,
                "codigoMarca": codigo_marca,
                "codigoModelo": codigo_modelo,
                "ano": ano_str,
                "codigoTipoCombustivel": codigo_tipo_combustivel,
                "anoModelo": ano_modelo,
                "tipoConsulta": "tradicional",
            },
        )

    def _parse_codigo_ano(self, codigo_ano: str) -> tuple[str, int, int]:
        partes = str(codigo_ano or "").strip().split("-", 1)
        if len(partes) != 2:
            raise ValueError(f"Código de ano FIPE inválido: {codigo_ano}")
        ano_txt = partes[0].strip()
        combustivel_txt = partes[1].strip()
        if not ano_txt.isdigit() or not combustivel_txt.isdigit():
            raise ValueError(f"Código de ano FIPE inválido: {codigo_ano}")
        return f"{ano_txt}-{combustivel_txt}", int(combustivel_txt), int(ano_txt)

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
    def _parse_mes_ano_dropdown(texto: str) -> datetime | None:
        txt = str(texto).strip().lower()
        trocas = {
            "á": "a", "à": "a", "ã": "a", "â": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u",
            "ç": "c",
        }
        for a, b in trocas.items():
            txt = txt.replace(a, b)
        meses = {
            "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
        }
        if "/" not in txt:
            return None
        mes_txt, ano_txt = txt.split("/", 1)
        mes = meses.get(mes_txt.strip())
        try:
            ano = int(ano_txt.strip())
        except Exception:
            return None
        if not mes:
            return None
        return datetime(ano, mes, 1)
