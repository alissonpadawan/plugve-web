from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import ast
import json
import re
import time

import requests

from services.fipe_service import FipeService, FipeApiError
from services.text_utils import normalizar_texto, parse_float_seguro


MESES_PT = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "marco": 3, "mar": 3,
    "março": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}


FIPE_WEB_BASE = "https://veiculos.fipe.org.br/api/veiculos"
HEADERS_WEB_V1917 = {
    # V24.7: headers legados do painel local; mantidos apenas como fallback, pois o Render usa API PRO v2.
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://veiculos.fipe.org.br/",
    "Origin": "https://veiculos.fipe.org.br",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
}
TIMEOUT_WEB_V1917 = 30
SLEEP_WEB_V1917 = 0.06
MAX_RETRIES_WEB_V1917 = 3
CODIGO_TIPO_VEICULO_WEB_CARRO = 1


def normalizar_payload_fipe_web_lista(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("d", "items", "Items", "result", "results", "Resultados", "Modelos", "Marcas", "Anos"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
            if isinstance(val, dict):
                nested = normalizar_payload_fipe_web_lista(val)
                if nested:
                    return nested
            if isinstance(val, str):
                try:
                    obj = json.loads(val)
                except Exception:
                    try:
                        obj = ast.literal_eval(val)
                    except Exception:
                        obj = None
                nested = normalizar_payload_fipe_web_lista(obj)
                if nested:
                    return nested
        if any(k in payload for k in ("Label", "Value", "Codigo", "Mes", "codigo", "nome")):
            return [payload]
    if isinstance(payload, str):
        try:
            obj = json.loads(payload)
        except Exception:
            try:
                obj = ast.literal_eval(payload)
            except Exception:
                return []
        return normalizar_payload_fipe_web_lista(obj)
    return []


def normalizar_payload_fipe_web_modelos(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if payload is None:
        return {"Modelos": []}
    if isinstance(payload, dict):
        if isinstance(payload.get("Modelos"), list):
            return {"Modelos": [x for x in payload.get("Modelos", []) if isinstance(x, dict)]}
        if isinstance(payload.get("d"), str):
            try:
                obj = json.loads(payload.get("d"))
            except Exception:
                try:
                    obj = ast.literal_eval(payload.get("d"))
                except Exception:
                    obj = None
            if isinstance(obj, dict) and isinstance(obj.get("Modelos"), list):
                return {"Modelos": [x for x in obj.get("Modelos", []) if isinstance(x, dict)]}
        modelos = normalizar_payload_fipe_web_lista(payload)
        return {"Modelos": modelos}
    if isinstance(payload, str):
        try:
            obj = json.loads(payload)
        except Exception:
            try:
                obj = ast.literal_eval(payload)
            except Exception:
                obj = None
        return normalizar_payload_fipe_web_modelos(obj)
    if isinstance(payload, list):
        return {"Modelos": [x for x in payload if isinstance(x, dict)]}
    return {"Modelos": []}


class FipeWebHistoricoV1917Client:
    """Cliente fiel ao painel local V19.17 para histórico FIPE mensal.

    Usa o mesmo fluxo do aplicativo local:
    ConsultarTabelaDeReferencia -> ConsultarMarcas -> ConsultarModelos ->
    ConsultarAnoModelo -> ConsultarValorComTodosParametros.

    Não substitui as rotas FIPE atuais do site; é usado apenas pelo diagnóstico
    V19.17 em lotes pequenos.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS_WEB_V1917)
        self._sessao_preparada = False

    def preparar_sessao(self) -> None:
        """Abre a página pública antes do POST, como um navegador.

        O painel local fazia POST direto e funcionava no Windows. No Render,
        alguns bloqueios 403 podem ocorrer sem cookies/sessão inicial. Este
        aquecimento mantém a mesma estratégia pública, sem token e sem API paga.
        """
        if self._sessao_preparada:
            return
        self._sessao_preparada = True
        try:
            self.session.get(
                "https://veiculos.fipe.org.br/",
                timeout=min(TIMEOUT_WEB_V1917, 12),
                headers={
                    "User-Agent": HEADERS_WEB_V1917["User-Agent"],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": HEADERS_WEB_V1917["Accept-Language"],
                },
            )
            time.sleep(SLEEP_WEB_V1917)
        except Exception:
            # Se o GET falhar, ainda tentamos o POST exatamente como no painel.
            pass

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{FIPE_WEB_BASE}/{endpoint}"
        ultimo_erro: Exception | None = None
        for tentativa in range(1, MAX_RETRIES_WEB_V1917 + 1):
            try:
                self.preparar_sessao()
                resposta = self.session.post(url, json=payload or {}, timeout=TIMEOUT_WEB_V1917)
                resposta.raise_for_status()
                dados = resposta.json()
                time.sleep(SLEEP_WEB_V1917)
                return dados
            except Exception as exc:
                ultimo_erro = exc
                # Em 403, renova a sessão uma vez antes da próxima tentativa.
                if getattr(getattr(exc, "response", None), "status_code", None) == 403:
                    self._sessao_preparada = False
                if tentativa < MAX_RETRIES_WEB_V1917:
                    time.sleep(0.4 * tentativa)
                else:
                    raise ultimo_erro
        return None

    def consultar_tabela_referencia(self) -> Any:
        return self.post("ConsultarTabelaDeReferencia")

    def consultar_marcas(self, codigo_tabela_referencia: int) -> Any:
        return self.post("ConsultarMarcas", {
            "codigoTabelaReferencia": int(codigo_tabela_referencia),
            "codigoTipoVeiculo": CODIGO_TIPO_VEICULO_WEB_CARRO,
        })

    def consultar_modelos(self, codigo_tabela_referencia: int, codigo_marca: str) -> Any:
        return self.post("ConsultarModelos", {
            "codigoTabelaReferencia": int(codigo_tabela_referencia),
            "codigoTipoVeiculo": CODIGO_TIPO_VEICULO_WEB_CARRO,
            "codigoMarca": str(codigo_marca),
        })

    def consultar_ano_modelo(self, codigo_tabela_referencia: int, codigo_marca: str, codigo_modelo: str) -> Any:
        return self.post("ConsultarAnoModelo", {
            "codigoTabelaReferencia": int(codigo_tabela_referencia),
            "codigoTipoVeiculo": CODIGO_TIPO_VEICULO_WEB_CARRO,
            "codigoMarca": str(codigo_marca),
            "codigoModelo": str(codigo_modelo),
        })

    def consultar_valor(
        self,
        codigo_tabela_referencia: int,
        codigo_marca: str,
        codigo_modelo: str,
        ano_str: str,
        codigo_tipo_combustivel: int,
        ano_modelo: int,
    ) -> Any:
        return self.post("ConsultarValorComTodosParametros", {
            "codigoTabelaReferencia": int(codigo_tabela_referencia),
            "codigoTipoVeiculo": CODIGO_TIPO_VEICULO_WEB_CARRO,
            "codigoMarca": str(codigo_marca),
            "codigoModelo": str(codigo_modelo),
            "ano": str(ano_str),
            "codigoTipoCombustivel": int(codigo_tipo_combustivel),
            "anoModelo": int(ano_modelo),
            "tipoConsulta": "tradicional",
        })


@dataclass
class PontoHistoricoPainel:
    ok: bool
    reference: str
    mes: str
    data_referencia: str | None = None
    valor: float | None = None
    valor_formatado: str = ""
    codigo_marca_referencia: str = ""
    codigo_modelo_referencia: str = ""
    modelo_referencia: str = ""
    codigo_ano_referencia: str = ""
    ano_referencia: str = ""
    codigo_tipo_combustivel: int | None = None
    ano_modelo_referencia: int | None = None
    estrategia: str = ""
    motivo: str = ""
    debug: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reference": self.reference,
            "mes": self.mes,
            "data_referencia": self.data_referencia,
            "valor": self.valor,
            "valor_formatado": self.valor_formatado,
            "codigo_marca_referencia": self.codigo_marca_referencia,
            "codigo_modelo_referencia": self.codigo_modelo_referencia,
            "modelo_referencia": self.modelo_referencia,
            "codigo_ano_referencia": self.codigo_ano_referencia,
            "ano_referencia": self.ano_referencia,
            "codigo_tipo_combustivel": self.codigo_tipo_combustivel,
            "ano_modelo_referencia": self.ano_modelo_referencia,
            "estrategia": self.estrategia,
            "motivo": self.motivo,
            "debug": self.debug or {},
        }


class FipeHistoricoPainelAdapter:
    """Adaptador do fluxo antigo do Painel de Depreciação para a API FIPE v2.

    Ideia herdada do painel local:
    - primeiro entra no mês de referência;
    - dentro daquele mês reconstrói marca/modelo/ano;
    - só depois consulta valor.

    O objetivo aqui é não usar cegamente os códigos atuais no passado.
    """

    def __init__(self, fipe: FipeService | None = None) -> None:
        self.fipe = fipe or FipeService()
        self.web_client = FipeWebHistoricoV1917Client()

    @staticmethod
    def parse_mes_referencia(mes: str) -> datetime | None:
        txt = normalizar_texto(str(mes or ""))
        if not txt:
            return None
        ano_match = re.search(r"(19|20)\d{2}", txt)
        if not ano_match:
            return None
        ano = int(ano_match.group(0))
        mes_num = None
        for nome, num in MESES_PT.items():
            if normalizar_texto(nome) in txt:
                mes_num = num
                break
        if mes_num is None:
            # tenta formatos numéricos tipo 06/2026
            m = re.search(r"\b(0?[1-9]|1[0-2])\D+(19|20)\d{2}\b", txt)
            if m:
                mes_num = int(m.group(1))
        if mes_num is None:
            return None
        return datetime(ano, mes_num, 1)

    def referencias_ordenadas(self) -> list[dict[str, Any]]:
        refs = self.fipe.listar_referencias()
        saida = []
        for r in refs or []:
            code = str(r.get("code") or r.get("codigo") or "").strip()
            month = str(r.get("month") or r.get("mes") or "").strip()
            data_ref = self.parse_mes_referencia(month)
            if not code:
                continue
            saida.append({"code": code, "month": month, "data_ref": data_ref, "fonte": "fipe_v2"})
        # Se a data foi parseada, usa data. Se não, mantém ordem por código.
        saida.sort(key=lambda x: (x["data_ref"] or datetime.min, int(x["code"]) if x["code"].isdigit() else 0))
        return saida

    def referencias_estimadas_web_v1917(self, erro_origem: str = "") -> list[dict[str, Any]]:
        """Gera a tabela de referências FIPE quando o endpoint de tabela falha.

        A numeração pública da tabela de referência é sequencial. Pelo próprio
        teste do painel local/diagnóstico, janeiro/2016 = 187. Isso equivale à
        fórmula code = (ano - 2000) * 12 + mes - 6.

        Esta rotina não consulta API paga. Ela só reconstrói os códigos mensais
        para que o fluxo público Web continue tentando ConsultarMarcas,
        ConsultarModelos, ConsultarAnoModelo e ConsultarValorComTodosParametros.
        """
        nomes = {
            1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
            5: "maio", 6: "junho", 7: "julho", 8: "agosto",
            9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
        }
        hoje = datetime.now()
        saida: list[dict[str, Any]] = []
        ano, mes = 2001, 1
        while (ano < hoje.year) or (ano == hoje.year and mes <= hoje.month):
            codigo = (ano - 2000) * 12 + mes - 6
            if codigo > 0:
                mes_txt = f"{nomes[mes]}/{ano}"
                saida.append({
                    "code": str(codigo),
                    "codigo_tabela_referencia": int(codigo),
                    "month": mes_txt,
                    "data_ref": datetime(ano, mes, 1),
                    "fonte": "fipe_web_v1917",
                    "referencias_estimadas": True,
                    "aviso_referencias": erro_origem,
                })
            mes += 1
            if mes == 13:
                mes = 1
                ano += 1
        return saida

    def referencias_ordenadas_web_v1917(self) -> list[dict[str, Any]]:
        try:
            refs = normalizar_payload_fipe_web_lista(self.web_client.consultar_tabela_referencia())
        except Exception as exc:
            erro = f"Falha ao consultar tabela pública Web FIPE; referências geradas localmente: {type(exc).__name__}: {str(exc)[:180]}"
            return self.referencias_estimadas_web_v1917(erro)

        saida: list[dict[str, Any]] = []
        for item in refs:
            codigo = item.get("Codigo") or item.get("codigo") or item.get("Value") or item.get("code")
            mes = str(item.get("Mes") or item.get("mes") or item.get("Label") or item.get("month") or "").strip()
            data_ref = self.parse_mes_referencia(mes)
            if codigo is None or not mes or data_ref is None:
                continue
            saida.append({
                "code": str(codigo).strip(),
                "codigo_tabela_referencia": int(codigo),
                "month": mes,
                "data_ref": data_ref,
                "fonte": "fipe_web_v1917",
                "referencias_estimadas": False,
                "aviso_referencias": "",
            })
        saida.sort(key=lambda x: x["data_ref"])
        if not saida:
            return self.referencias_estimadas_web_v1917("Tabela pública Web FIPE retornou vazia; referências geradas localmente.")
        return saida

    @staticmethod
    def _valor_item_web(item: dict[str, Any]) -> str:
        return str(item.get("Value") or item.get("value") or item.get("Codigo") or item.get("codigo") or item.get("code") or "").strip()

    @staticmethod
    def _label_item_web(item: dict[str, Any]) -> str:
        return str(item.get("Label") or item.get("label") or item.get("Nome") or item.get("nome") or item.get("name") or "").strip()

    @staticmethod
    def _codigo_tipo_combustivel_do_codigo_ano(codigo_ano: str) -> int | None:
        partes = str(codigo_ano or "").split("-", 1)
        if len(partes) != 2:
            return None
        try:
            return int(partes[1])
        except Exception:
            return None

    @staticmethod
    def _ano_modelo_do_codigo_ano(codigo_ano: str) -> int | None:
        ano_txt = str(codigo_ano or "").split("-", 1)[0]
        try:
            return int(ano_txt)
        except Exception:
            return None

    def _preco_do_detalhe_v2(self, detalhe: dict[str, Any]) -> tuple[float, str]:
        valor_txt = str(detalhe.get("Valor") or detalhe.get("price") or "").strip()
        valor = parse_float_seguro(valor_txt)
        return float(valor or 0.0), valor_txt

    def escolher_ano_codigo_fipe_na_referencia(
        self,
        anos: list[dict[str, Any]],
        *,
        ano_base: int | None = None,
        codigo_ano_preferido: str = "",
        combustivel_alvo: str = "",
        codigo_tipo_combustivel_preferido: int | None = None,
    ) -> dict[str, Any] | None:
        """Escolhe o yearCode correto dentro de UMA referência mensal.

        Esta é a correção central da V24.7: no histórico antigo não usamos
        cegamente o código de ano atual. Primeiro listamos os anos disponíveis
        na referência mensal e só então escolhemos a coorte/base.
        """
        itens = [a for a in (anos or []) if isinstance(a, dict)]
        if not itens:
            return None

        preferido = str(codigo_ano_preferido or "").strip()
        suffix_preferido = ""
        if "-" in preferido:
            suffix_preferido = preferido.split("-", 1)[1].strip()

        candidatos: list[dict[str, Any]] = []
        for item in itens:
            codigo = str(item.get("codigo") or item.get("code") or "").strip()
            ano_codigo = self._ano_modelo_do_codigo_ano(codigo)
            if codigo.startswith("32000"):
                continue
            if ano_base is not None and ano_codigo != int(ano_base):
                continue
            candidatos.append(item)

        if not candidatos and preferido:
            for item in itens:
                codigo = str(item.get("codigo") or item.get("code") or "").strip()
                if codigo == preferido:
                    candidatos.append(item)
                    break

        if not candidatos:
            return None

        if suffix_preferido:
            for item in candidatos:
                codigo = str(item.get("codigo") or item.get("code") or "").strip()
                if codigo.endswith(f"-{suffix_preferido}"):
                    return item

        if codigo_tipo_combustivel_preferido is not None:
            for item in candidatos:
                codigo = str(item.get("codigo") or item.get("code") or "").strip()
                tipo = self._codigo_tipo_combustivel_do_codigo_ano(codigo)
                if tipo is not None and int(tipo) == int(codigo_tipo_combustivel_preferido):
                    return item

        compativeis = [
            item for item in candidatos
            if self._combustivel_compativel(str(item.get("nome") or item.get("name") or ""), combustivel_alvo)
        ]
        return (compativeis or candidatos)[0]

    def consultar_ponto_codigo_fipe_v1917(
        self,
        *,
        reference: str,
        mes_referencia: str,
        codigo_fipe: str,
        codigo_ano: str,
        nome_modelo: str = "",
        ano_base: int | None = None,
        combustivel: str = "",
        codigo_tipo_combustivel_preferido: int | None = None,
    ) -> PontoHistoricoPainel:
        """Consulta um ponto mensal pela API v2 usando código FIPE.

        V24.7: tenta primeiro o detalhe direto por código FIPE + yearCode da
        coorte. Isso economiza uma chamada lenta a /years em referências antigas.
        Se o detalhe direto retornar 404, aí sim redescobre o yearCode dentro da
        referência mensal, como no painel local.
        """
        reference = str(reference or "").strip()
        mes_referencia = str(mes_referencia or "").strip()
        codigo_fipe = str(codigo_fipe or "").strip()
        codigo_ano_preferido = str(codigo_ano or "").strip()
        ano_base_resolvido = int(ano_base) if ano_base is not None else self._ano_modelo_do_codigo_ano(codigo_ano_preferido)
        debug = {
            "reference": reference,
            "mes": mes_referencia,
            "codigo_fipe": codigo_fipe,
            "codigo_ano_preferido": codigo_ano_preferido,
            "ano_base": ano_base_resolvido,
            "fluxo": "fipe_v2_codigo_fipe_direto_com_fallback_redescobre_ano_v1917",
        }
        if not codigo_fipe:
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo="codigo_fipe_ausente", debug=debug)

        def _montar_ponto_ok(detalhe: dict[str, Any], codigo_ano_resolvido: str, estrategia: str, debug_extra: dict[str, Any] | None = None) -> PontoHistoricoPainel:
            valor, valor_txt = self._preco_do_detalhe_v2(detalhe)
            if not valor or valor <= 0:
                return PontoHistoricoPainel(
                    False,
                    reference,
                    mes_referencia,
                    motivo="preco_invalido_codigo_fipe_referencia",
                    debug={**debug, **(debug_extra or {}), "codigo_ano_resolvido": codigo_ano_resolvido, "detalhe_keys": sorted(detalhe.keys())[:12] if isinstance(detalhe, dict) else []},
                )
            data_dt = self.parse_mes_referencia(mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""))
            ano_modelo = self._ano_modelo_do_codigo_ano(codigo_ano_resolvido)
            codigo_tipo_combustivel = self._codigo_tipo_combustivel_do_codigo_ano(codigo_ano_resolvido)
            return PontoHistoricoPainel(
                True,
                reference,
                mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""),
                data_referencia=data_dt.strftime("%Y-%m") if data_dt else None,
                valor=float(valor),
                valor_formatado=valor_txt,
                codigo_marca_referencia="",
                codigo_modelo_referencia="",
                modelo_referencia=str(detalhe.get("Modelo") or detalhe.get("model") or nome_modelo or ""),
                codigo_ano_referencia=codigo_ano_resolvido,
                ano_referencia=str(detalhe.get("AnoModelo") or detalhe.get("modelYear") or ano_modelo or ""),
                codigo_tipo_combustivel=codigo_tipo_combustivel,
                ano_modelo_referencia=ano_modelo,
                estrategia=estrategia,
                debug={
                    **debug,
                    **(debug_extra or {}),
                    "codigo_ano_resolvido": codigo_ano_resolvido,
                    "modelo_api": str(detalhe.get("Modelo") or detalhe.get("model") or ""),
                    "combustivel_api": str(detalhe.get("Combustivel") or detalhe.get("fuel") or ""),
                    "api_base": str(detalhe.get("_plugve_api_base") or ""),
                },
            )

        # 1) Caminho rápido: detalhe direto. Para o Etios, tenta 2017-5 em cada referência.
        if codigo_ano_preferido:
            try:
                detalhe = self.fipe.consultar_detalhe_por_codigo_fipe(codigo_fipe, codigo_ano_preferido, reference=reference)
                ponto = _montar_ponto_ok(
                    detalhe,
                    codigo_ano_preferido,
                    "fipe_v2_codigo_fipe_direto_ano_preferido_v1917",
                    {"tentativa": "direto_codigo_fipe_yearcode", "endpoint": f"{codigo_fipe}/years/{codigo_ano_preferido}"},
                )
                if ponto.ok and ponto.valor:
                    return ponto
            except FipeApiError as exc:
                if exc.status_code in (401, 402, 403, 429):
                    raise
                # 404 significa apenas que a coorte ainda não existia neste mês.
                if exc.status_code == 404:
                    return PontoHistoricoPainel(
                        False,
                        reference,
                        mes_referencia,
                        motivo="ano_preferido_nao_existe_na_referencia",
                        debug={**debug, "tentativa": "direto_codigo_fipe_yearcode", "status_code": exc.status_code, "endpoint": exc.endpoint},
                    )
                # Timeout/conexão: não faz segunda chamada no mesmo lote para não estourar o Render.
                return PontoHistoricoPainel(
                    False,
                    reference,
                    mes_referencia,
                    motivo=f"erro_api_controlado:{exc.tipo}:{exc.message}",
                    debug={**debug, "tentativa": "direto_codigo_fipe_yearcode", "status_code": exc.status_code, "endpoint": exc.endpoint},
                )
            except Exception as exc:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_controlado:{type(exc).__name__}:{str(exc)[:160]}", debug={**debug, "tentativa": "direto_codigo_fipe_yearcode"})

        # 2) Caminho fiel ao local: redescobre o ano dentro da referência.
        try:
            anos = self.fipe.listar_anos_por_codigo_fipe(codigo_fipe, reference=reference)
            ano_item = self.escolher_ano_codigo_fipe_na_referencia(
                anos,
                ano_base=ano_base_resolvido,
                codigo_ano_preferido=codigo_ano_preferido,
                combustivel_alvo=combustivel,
                codigo_tipo_combustivel_preferido=codigo_tipo_combustivel_preferido,
            )
            if not ano_item:
                return PontoHistoricoPainel(
                    False,
                    reference,
                    mes_referencia,
                    motivo="ano_nao_encontrado_codigo_fipe_na_referencia",
                    debug={**debug, "tentativa": "redescobrir_yearcode", "anos_disponiveis": len(anos or []), "amostra_anos": (anos or [])[:6]},
                )
            codigo_ano_resolvido = str(ano_item.get("codigo") or ano_item.get("code") or "").strip()
            detalhe = self.fipe.consultar_detalhe_por_codigo_fipe(codigo_fipe, codigo_ano_resolvido, reference=reference)
            return _montar_ponto_ok(
                detalhe,
                codigo_ano_resolvido,
                "fipe_v2_codigo_fipe_redescobre_ano_referencia_v1917",
                {"tentativa": "redescobrir_yearcode", "endpoint": f"{codigo_fipe}/years/{codigo_ano_resolvido}", "anos_disponiveis": len(anos or [])},
            )
        except FipeApiError as exc:
            if exc.status_code in (401, 402, 403, 429):
                raise
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_api_controlado:{exc.tipo}:{exc.message}", debug={**debug, "tentativa": "redescobrir_yearcode", "status_code": exc.status_code, "endpoint": exc.endpoint})
        except Exception as exc:
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_controlado:{type(exc).__name__}:{str(exc)[:160]}", debug=debug)

    def consultar_zero_km_codigo_fipe_v1917(self, *, referencia: dict[str, Any], primeiro_usado: PontoHistoricoPainel) -> PontoHistoricoPainel | None:
        """Procura o yearCode 32000 na mesma referência usando código FIPE.

        V24.7: tenta direto 32000-sufixo antes de listar /years, porque o /years
        em referências antigas pode ser a chamada mais lenta.
        """
        reference = str(referencia.get("code") or referencia.get("codigo_tabela_referencia") or primeiro_usado.reference or "").strip()
        mes = str(referencia.get("month") or primeiro_usado.mes or "").strip()
        codigo_fipe = str((primeiro_usado.debug or {}).get("codigo_fipe") or "").strip()
        if not codigo_fipe:
            return None
        suffix_usado = ""
        if "-" in str(primeiro_usado.codigo_ano_referencia or ""):
            suffix_usado = str(primeiro_usado.codigo_ano_referencia).split("-", 1)[1].strip()

        candidatos_diretos = []
        if suffix_usado:
            candidatos_diretos.append(f"32000-{suffix_usado}")
        candidatos_diretos.extend(["32000-1", "32000-2", "32000-3", "32000-5"])

        def _montar_zero(codigo_zero: str, detalhe: dict[str, Any]) -> PontoHistoricoPainel | None:
            valor, valor_txt = self._preco_do_detalhe_v2(detalhe)
            if not valor or valor <= 0:
                return None
            data_dt = self.parse_mes_referencia(mes or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""))
            if primeiro_usado.data_referencia and data_dt and primeiro_usado.data_referencia == data_dt.strftime("%Y-%m"):
                data_dt = self._subtrair_um_mes_dt(data_dt)
                mes_local = data_dt.strftime("%m/%Y")
            else:
                mes_local = mes
            combustivel_zero = self._codigo_tipo_combustivel_do_codigo_ano(codigo_zero)
            return PontoHistoricoPainel(
                True,
                reference,
                mes_local,
                data_referencia=data_dt.strftime("%Y-%m") if data_dt else None,
                valor=float(valor),
                valor_formatado=valor_txt,
                codigo_marca_referencia="",
                codigo_modelo_referencia="",
                modelo_referencia=primeiro_usado.modelo_referencia,
                codigo_ano_referencia=codigo_zero,
                ano_referencia="Zero KM",
                codigo_tipo_combustivel=combustivel_zero,
                ano_modelo_referencia=32000,
                estrategia="fipe_v2_codigo_fipe_zero_km_direto_v1917",
                debug={"codigo_fipe": codigo_fipe, "codigo_ano_usado": primeiro_usado.codigo_ano_referencia, "codigo_ano_zero": codigo_zero, "fonte": "fipe_v2_codigo_fipe_v1917", "api_base": str(detalhe.get("_plugve_api_base") or "")},
            )

        # 1) tenta consulta direta 32000-sufixo.
        ja_testados: set[str] = set()
        for codigo_zero in candidatos_diretos:
            if not codigo_zero or codigo_zero in ja_testados:
                continue
            ja_testados.add(codigo_zero)
            try:
                detalhe = self.fipe.consultar_detalhe_por_codigo_fipe(codigo_fipe, codigo_zero, reference=reference)
                zero = _montar_zero(codigo_zero, detalhe)
                if zero:
                    return zero
            except FipeApiError as exc:
                if exc.status_code in (401, 402, 403, 429):
                    raise
                if exc.status_code is None:
                    # Timeout: não insiste no mesmo lote; evita derrubar o Render.
                    return None
                continue
            except Exception:
                continue

        # 2) fallback fiel: lista anos e procura 32000.
        try:
            anos = self.fipe.listar_anos_por_codigo_fipe(codigo_fipe, reference=reference)
            candidatos: list[str] = []
            for item in anos or []:
                codigo = str(item.get("codigo") or item.get("code") or "").strip()
                if not codigo.startswith("32000") or codigo in ja_testados:
                    continue
                if suffix_usado and codigo.endswith(f"-{suffix_usado}"):
                    candidatos.insert(0, codigo)
                else:
                    candidatos.append(codigo)
            for codigo_zero in candidatos:
                detalhe = self.fipe.consultar_detalhe_por_codigo_fipe(codigo_fipe, codigo_zero, reference=reference)
                zero = _montar_zero(codigo_zero, detalhe)
                if zero:
                    zero.estrategia = "fipe_v2_codigo_fipe_zero_km_lista_years_v1917"
                    return zero
            return None
        except FipeApiError as exc:
            if exc.status_code in (401, 402, 403, 429):
                raise
            return None
        except Exception:
            return None

    def consultar_preco_usado_codigo_fipe_v1917(self, *, referencia: dict[str, Any], primeiro_usado: PontoHistoricoPainel) -> PontoHistoricoPainel:
        reference = str(referencia.get("code") or referencia.get("codigo_tabela_referencia") or "").strip()
        mes = str(referencia.get("month") or "").strip()
        codigo_fipe = str((primeiro_usado.debug or {}).get("codigo_fipe") or "").strip()
        codigo_ano = str(primeiro_usado.codigo_ano_referencia or "").strip()
        return self.consultar_ponto_codigo_fipe_v1917(
            reference=reference,
            mes_referencia=mes,
            codigo_fipe=codigo_fipe,
            codigo_ano=codigo_ano,
            nome_modelo=primeiro_usado.modelo_referencia,
            ano_base=primeiro_usado.ano_modelo_referencia,
            codigo_tipo_combustivel_preferido=primeiro_usado.codigo_tipo_combustivel,
        )

    def escolher_marca_web_v1917(self, marcas: Any, nome_marca: str) -> dict[str, Any] | None:
        alvo = normalizar_texto(nome_marca)
        itens = normalizar_payload_fipe_web_lista(marcas)
        for item in itens:
            nome = normalizar_texto(self._label_item_web(item))
            if nome == alvo:
                return item
        for item in itens:
            nome = normalizar_texto(self._label_item_web(item))
            if alvo and (alvo in nome or nome in alvo):
                return item
        return None

    def escolher_modelo_web_v1917(self, modelos_payload: Any, nome_modelo: str) -> tuple[dict[str, Any] | None, float, dict[str, Any]]:
        modelos = normalizar_payload_fipe_web_modelos(modelos_payload).get("Modelos", [])
        alvo_norm = normalizar_texto(nome_modelo)
        alvo_tokens = self._tokenizar_modelo(nome_modelo)
        familia = self._familia_principal(nome_modelo)
        melhor = None
        melhor_score = 0.0
        debug = {"familia_alvo": familia, "tokens_alvo": sorted(alvo_tokens), "candidatos": []}
        for item in modelos:
            nome = self._label_item_web(item)
            nome_norm = normalizar_texto(nome)
            if not nome_norm:
                continue
            if nome_norm == alvo_norm:
                return item, 1.0, {**debug, "match": "exato", "modelo": nome}
            tokens = self._tokenizar_modelo(nome)
            inter = len(alvo_tokens & tokens)
            union = max(1, len(alvo_tokens | tokens))
            score = inter / union
            familia_cand = self._familia_principal(nome)
            if familia and familia_cand == familia:
                score += 0.35
            if alvo_norm in nome_norm or nome_norm in alvo_norm:
                score += 0.20
            if familia and familia_cand and familia_cand != familia:
                score -= 0.25
            debug["candidatos"].append({"nome": nome, "score": round(score, 3), "tokens": sorted(tokens)[:8]})
            if score > melhor_score:
                melhor_score = score
                melhor = item
        return (melhor, melhor_score, debug) if melhor and melhor_score >= 0.42 else (None, melhor_score, debug)

    def escolher_ano_modelo_web_v1917(self, anos: Any, ano_alvo: int) -> tuple[str, int, int, str] | None:
        for item in normalizar_payload_fipe_web_lista(anos):
            value = self._valor_item_web(item)
            partes = value.split("-")
            if len(partes) != 2:
                continue
            ano_txt, combustivel_txt = partes
            if ano_txt != str(int(ano_alvo)):
                continue
            try:
                return value, int(combustivel_txt), int(ano_txt), self._label_item_web(item)
            except Exception:
                continue
        return None

    def escolher_ano_zero_km_web_v1917(self, anos: Any, codigo_tipo_combustivel: int | None) -> tuple[str, int, int, str] | None:
        candidatos: list[tuple[str, int, int, str]] = []
        for item in normalizar_payload_fipe_web_lista(anos):
            value = self._valor_item_web(item)
            partes = value.split("-")
            if len(partes) != 2:
                continue
            ano_txt, combustivel_txt = partes
            if ano_txt != "32000":
                continue
            try:
                candidatos.append((value, int(combustivel_txt), 32000, self._label_item_web(item) or "Zero KM"))
            except Exception:
                continue
        if not candidatos:
            return None
        if codigo_tipo_combustivel is not None:
            for cand in candidatos:
                if int(cand[1]) == int(codigo_tipo_combustivel):
                    return cand
        return candidatos[0]

    def consultar_ponto_modelo_primeiro_web_v1917(self, *, reference: str, mes_referencia: str, codigo_marca_atual: str, nome_marca: str, nome_modelo: str, ano_base: int, combustivel: str = "") -> PontoHistoricoPainel:
        debug: dict[str, Any] = {"reference": reference, "mes": mes_referencia, "ano_base": ano_base, "fluxo": "fipe_web_v1917"}
        try:
            codigo_ref = int(str(reference))
            marcas = self.web_client.consultar_marcas(codigo_ref)
            marca = self.escolher_marca_web_v1917(marcas, nome_marca)
            if not marca:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="marca_nao_encontrada_na_referencia_web", debug={**debug, "marcas": len(normalizar_payload_fipe_web_lista(marcas))})
            codigo_marca = self._valor_item_web(marca)
            modelos_payload = self.web_client.consultar_modelos(codigo_ref, codigo_marca)
            modelo, score, dbg_modelo = self.escolher_modelo_web_v1917(modelos_payload, nome_modelo)
            if not modelo:
                modelos = normalizar_payload_fipe_web_modelos(modelos_payload).get("Modelos", [])
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="modelo_nao_encontrado_na_referencia_web", codigo_marca_referencia=codigo_marca, debug={**debug, "modelos": len(modelos), "score_melhor": round(score, 3), "modelo_debug": dbg_modelo})
            codigo_modelo = self._valor_item_web(modelo)
            anos = self.web_client.consultar_ano_modelo(codigo_ref, codigo_marca, codigo_modelo)
            ano_info = self.escolher_ano_modelo_web_v1917(anos, int(ano_base))
            if not ano_info:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="ano_nao_encontrado_na_referencia_web", codigo_marca_referencia=codigo_marca, codigo_modelo_referencia=codigo_modelo, modelo_referencia=self._label_item_web(modelo), debug={**debug, "anos": len(normalizar_payload_fipe_web_lista(anos))})
            ano_str, codigo_tipo_combustivel, ano_modelo, label_ano = ano_info
            valor_payload = self.web_client.consultar_valor(codigo_ref, codigo_marca, codigo_modelo, ano_str, codigo_tipo_combustivel, ano_modelo)
            valor_txt = str(valor_payload.get("Valor") or valor_payload.get("valor") or "").strip() if isinstance(valor_payload, dict) else ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="preco_invalido_na_referencia_web", codigo_marca_referencia=codigo_marca, codigo_modelo_referencia=codigo_modelo, codigo_ano_referencia=ano_str, debug=debug)
            data_dt = self.parse_mes_referencia(mes_referencia)
            return PontoHistoricoPainel(
                True,
                reference,
                mes_referencia,
                data_referencia=data_dt.strftime("%Y-%m") if data_dt else None,
                valor=float(valor),
                valor_formatado=valor_txt,
                codigo_marca_referencia=codigo_marca,
                codigo_modelo_referencia=codigo_modelo,
                modelo_referencia=self._label_item_web(modelo),
                codigo_ano_referencia=ano_str,
                ano_referencia=label_ano or str(ano_base),
                codigo_tipo_combustivel=int(codigo_tipo_combustivel),
                ano_modelo_referencia=int(ano_modelo),
                estrategia="fipe_web_v1917_referencia_marca_modelos_anos_preco",
                debug={**debug, "score_modelo": round(score, 3), "codigo_marca_web": codigo_marca, "codigo_modelo_web": codigo_modelo},
            )
        except Exception as exc:
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_web_controlado:{type(exc).__name__}:{str(exc)[:160]}", debug=debug)

    def consultar_zero_km_web_v1917(self, *, referencia: dict[str, Any], primeiro_usado: PontoHistoricoPainel) -> PontoHistoricoPainel | None:
        try:
            codigo_ref = int(str(referencia.get("code") or referencia.get("codigo_tabela_referencia") or primeiro_usado.reference))
            anos = self.web_client.consultar_ano_modelo(codigo_ref, primeiro_usado.codigo_marca_referencia, primeiro_usado.codigo_modelo_referencia)
            zero_info = self.escolher_ano_zero_km_web_v1917(anos, primeiro_usado.codigo_tipo_combustivel)
            if not zero_info:
                return None
            ano_str_zero, codigo_tipo_combustivel_zero, ano_modelo_zero, label_ano_zero = zero_info
            valor_payload = self.web_client.consultar_valor(
                codigo_ref,
                primeiro_usado.codigo_marca_referencia,
                primeiro_usado.codigo_modelo_referencia,
                ano_str_zero,
                codigo_tipo_combustivel_zero,
                ano_modelo_zero,
            )
            valor_txt = str(valor_payload.get("Valor") or valor_payload.get("valor") or "").strip() if isinstance(valor_payload, dict) else ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return None
            mes = str(referencia.get("month") or primeiro_usado.mes or "")
            data_dt = self.parse_mes_referencia(mes)
            if primeiro_usado.data_referencia and data_dt and primeiro_usado.data_referencia == data_dt.strftime("%Y-%m"):
                data_dt = self._subtrair_um_mes_dt(data_dt)
                mes = data_dt.strftime("%m/%Y")
            return PontoHistoricoPainel(
                True,
                str(codigo_ref),
                mes,
                data_referencia=data_dt.strftime("%Y-%m") if data_dt else None,
                valor=float(valor),
                valor_formatado=valor_txt,
                codigo_marca_referencia=primeiro_usado.codigo_marca_referencia,
                codigo_modelo_referencia=primeiro_usado.codigo_modelo_referencia,
                modelo_referencia=primeiro_usado.modelo_referencia,
                codigo_ano_referencia=ano_str_zero,
                ano_referencia=label_ano_zero or "Zero KM",
                codigo_tipo_combustivel=int(codigo_tipo_combustivel_zero),
                ano_modelo_referencia=int(ano_modelo_zero),
                estrategia="fipe_web_v1917_zero_km_mes_primeira_aparicao",
                debug={"tipo": "zero_km", "fonte": "fipe_web_v1917"},
            )
        except Exception:
            return None

    def consultar_preco_usado_web_v1917(self, *, referencia: dict[str, Any], primeiro_usado: PontoHistoricoPainel) -> PontoHistoricoPainel:
        reference = str(referencia.get("code") or referencia.get("codigo_tabela_referencia") or "")
        mes = str(referencia.get("month") or "")
        try:
            codigo_ref = int(reference)
            if primeiro_usado.codigo_tipo_combustivel is None or primeiro_usado.ano_modelo_referencia is None:
                return PontoHistoricoPainel(False, reference, mes, motivo="primeiro_usado_sem_codigo_combustivel_web")
            valor_payload = self.web_client.consultar_valor(
                codigo_ref,
                primeiro_usado.codigo_marca_referencia,
                primeiro_usado.codigo_modelo_referencia,
                primeiro_usado.codigo_ano_referencia,
                int(primeiro_usado.codigo_tipo_combustivel),
                int(primeiro_usado.ano_modelo_referencia),
            )
            valor_txt = str(valor_payload.get("Valor") or valor_payload.get("valor") or "").strip() if isinstance(valor_payload, dict) else ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return PontoHistoricoPainel(False, reference, mes, motivo="preco_invalido_historico_web")
            data_dt = self.parse_mes_referencia(mes)
            return PontoHistoricoPainel(
                True,
                reference,
                mes,
                data_referencia=data_dt.strftime("%Y-%m") if data_dt else None,
                valor=float(valor),
                valor_formatado=valor_txt,
                codigo_marca_referencia=primeiro_usado.codigo_marca_referencia,
                codigo_modelo_referencia=primeiro_usado.codigo_modelo_referencia,
                modelo_referencia=primeiro_usado.modelo_referencia,
                codigo_ano_referencia=primeiro_usado.codigo_ano_referencia,
                ano_referencia=primeiro_usado.ano_referencia,
                codigo_tipo_combustivel=primeiro_usado.codigo_tipo_combustivel,
                ano_modelo_referencia=primeiro_usado.ano_modelo_referencia,
                estrategia="fipe_web_v1917_reutiliza_codigos_primeira_aparicao",
                debug={"fonte": "fipe_web_v1917"},
            )
        except Exception as exc:
            return PontoHistoricoPainel(False, reference, mes, motivo=f"erro_web_controlado:{type(exc).__name__}:{str(exc)[:160]}")


    @staticmethod
    def selecionar_referencias_amostradas(referencias: list[dict[str, Any]], ano_inicio: int, ano_atual: int, max_pontos: int = 6) -> list[dict[str, Any]]:
        if not referencias:
            return []
        inicio = datetime(max(1990, int(ano_inicio)), 1, 1)
        fim = datetime(int(ano_atual), 12, 31)
        refs_com_data = [r for r in referencias if r.get("data_ref")]
        if refs_com_data:
            janela = [r for r in refs_com_data if inicio <= r["data_ref"] <= fim]
        else:
            # fallback: usa janela recente do tamanho aproximado em meses
            janela_meses = max(1, (ano_atual - ano_inicio + 1) * 12)
            janela = referencias[-min(len(referencias), janela_meses):]
        if not janela:
            janela = refs_com_data[-min(len(refs_com_data), max_pontos):] if refs_com_data else referencias[-min(len(referencias), max_pontos):]
        if len(janela) <= max_pontos:
            return janela
        idxs = sorted(set(round(i * (len(janela) - 1) / (max_pontos - 1)) for i in range(max_pontos)))
        return [janela[i] for i in idxs]

    @staticmethod
    def _tokenizar_modelo(nome: str) -> set[str]:
        txt = normalizar_texto(nome)
        # Não ignorar versão/carroceria demais. O objetivo é achar mesma família/modelo,
        # mas sem usar SUV para hatch ou versão totalmente diferente.
        fracos = {
            "flex", "gasolina", "alcool", "diesel", "eletrico", "hibrido", "hybrid",
            "aut", "auto", "automatico", "mec", "manual", "at", "mt",
            "16v", "8v", "12v", "4p", "5p", "2p", "cv",
        }
        tokens = set()
        for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", txt):
            if len(token) < 2 or token in fracos:
                continue
            tokens.add(token)
        return tokens

    @staticmethod
    def _familia_principal(nome: str) -> str:
        tokens = list(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", normalizar_texto(nome)))
        fracos_inicio = {"toyota", "hyundai", "honda", "fiat", "chevrolet", "gm", "vw", "volkswagen", "renault", "ford", "byd", "jeep", "nissan"}
        tokens = [t for t in tokens if t not in fracos_inicio]
        return tokens[0] if tokens else ""

    def escolher_marca_na_referencia(self, marcas: list[dict[str, Any]], nome_marca: str, codigo_marca_atual: str = "") -> dict[str, Any] | None:
        if not marcas:
            return None
        alvo = normalizar_texto(nome_marca)
        cod_atual = str(codigo_marca_atual or "")
        for m in marcas:
            if cod_atual and str(m.get("codigo") or m.get("code") or "") == cod_atual:
                return m
        for m in marcas:
            nome = normalizar_texto(str(m.get("nome") or m.get("name") or ""))
            if nome == alvo:
                return m
        for m in marcas:
            nome = normalizar_texto(str(m.get("nome") or m.get("name") or ""))
            if alvo and (alvo in nome or nome in alvo):
                return m
        return None

    def escolher_modelo_na_referencia(self, modelos: list[dict[str, Any]], nome_modelo: str) -> tuple[dict[str, Any] | None, float, dict[str, Any]]:
        alvo_norm = normalizar_texto(nome_modelo)
        alvo_tokens = self._tokenizar_modelo(nome_modelo)
        familia = self._familia_principal(nome_modelo)
        melhor = None
        melhor_score = 0.0
        debug = {"familia_alvo": familia, "tokens_alvo": sorted(alvo_tokens), "candidatos": []}
        for m in modelos or []:
            nome = str(m.get("nome") or m.get("name") or "")
            nome_norm = normalizar_texto(nome)
            if not nome_norm:
                continue
            if nome_norm == alvo_norm:
                return m, 1.0, {**debug, "match": "exato", "modelo": nome}
            tokens = self._tokenizar_modelo(nome)
            inter = len(alvo_tokens & tokens)
            union = max(1, len(alvo_tokens | tokens))
            score = inter / union
            familia_cand = self._familia_principal(nome)
            if familia and familia_cand == familia:
                score += 0.35
            if alvo_norm in nome_norm or nome_norm in alvo_norm:
                score += 0.20
            # Evita cruzar famílias diferentes quando existe família clara.
            if familia and familia_cand and familia_cand != familia:
                score -= 0.25
            debug["candidatos"].append({"nome": nome, "score": round(score, 3), "tokens": sorted(tokens)[:8]})
            if score > melhor_score:
                melhor_score = score
                melhor = m
        # Threshold conservador: se for baixo, melhor não retornar do que usar curva errada.
        return (melhor, melhor_score, debug) if melhor and melhor_score >= 0.45 else (None, melhor_score, debug)

    @staticmethod
    def _ano_codigo(codigo: str) -> int | None:
        txt = str(codigo or "").split("-", 1)[0]
        if txt.isdigit() and txt != "32000":
            return int(txt)
        return None

    @staticmethod
    def _combustivel_compativel(nome_ano: str, combustivel_alvo: str) -> bool:
        alvo = normalizar_texto(combustivel_alvo)
        nome = normalizar_texto(nome_ano)
        if not alvo or not nome:
            return True
        if "flex" in alvo:
            return "flex" in nome
        if "diesel" in alvo:
            return "diesel" in nome
        if "hibrido" in alvo or "hybrid" in alvo:
            return "hibrido" in nome or "hybrid" in nome
        if "eletrico" in alvo:
            return "eletrico" in nome
        return True

    def escolher_ano_na_referencia(self, anos: list[dict[str, Any]], ano_base: int, combustivel_alvo: str) -> dict[str, Any] | None:
        candidatos = []
        for a in anos or []:
            codigo = str(a.get("codigo") or a.get("code") or "")
            nome = str(a.get("nome") or a.get("name") or "")
            ano = self._ano_codigo(codigo)
            if ano == int(ano_base):
                candidatos.append(a)
        if not candidatos:
            return None
        compativeis = [a for a in candidatos if self._combustivel_compativel(str(a.get("nome") or a.get("name") or ""), combustivel_alvo)]
        return (compativeis or candidatos)[0]

    def consultar_ponto_por_referencia_painel(self, *, reference: str, mes_referencia: str, codigo_marca_atual: str, nome_marca: str, nome_modelo: str, ano_base: int, combustivel: str) -> PontoHistoricoPainel:
        debug: dict[str, Any] = {"reference": reference, "mes": mes_referencia, "ano_base": ano_base}
        try:
            marcas = self.fipe.listar_marcas_referencia(reference)
            marca_ref = self.escolher_marca_na_referencia(marcas, nome_marca, codigo_marca_atual)
            if not marca_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="marca_nao_encontrada_na_referencia", debug={**debug, "marcas": len(marcas or [])})
            codigo_marca_ref = str(marca_ref.get("codigo") or marca_ref.get("code") or codigo_marca_atual)

            # Estratégia principal: igual à lógica visual da FIPE antiga no print:
            # referência -> marca -> ano -> modelos daquele ano.
            anos_marca = self.fipe.listar_anos_marca_referencia(codigo_marca_ref, reference)
            ano_ref = self.escolher_ano_na_referencia(anos_marca, ano_base, combustivel)
            if not ano_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="ano_nao_encontrado_na_referencia", codigo_marca_referencia=codigo_marca_ref, debug={**debug, "anos_marca": len(anos_marca or [])})
            codigo_ano_ref = str(ano_ref.get("codigo") or ano_ref.get("code") or "")

            modelos_data = self.fipe.listar_modelos_por_ano_referencia(codigo_marca_ref, codigo_ano_ref, reference)
            modelos = modelos_data.get("modelos", []) if isinstance(modelos_data, dict) else []
            modelo_ref, score, dbg_modelo = self.escolher_modelo_na_referencia(modelos, nome_modelo)
            if not modelo_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="modelo_nao_encontrado_na_referencia", codigo_marca_referencia=codigo_marca_ref, codigo_ano_referencia=codigo_ano_ref, ano_referencia=str(ano_ref.get("nome") or ano_ref.get("name") or ""), debug={**debug, "modelos": len(modelos or []), "score_melhor": round(score, 3), "modelo_debug": dbg_modelo})
            codigo_modelo_ref = str(modelo_ref.get("codigo") or modelo_ref.get("code") or "")

            detalhe = self.fipe.consultar_preco_referencia(codigo_marca_ref, codigo_modelo_ref, codigo_ano_ref, reference)
            valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="preco_invalido_na_referencia", codigo_marca_referencia=codigo_marca_ref, codigo_modelo_referencia=codigo_modelo_ref, codigo_ano_referencia=codigo_ano_ref, debug=debug)
            data_dt = self.parse_mes_referencia(mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""))
            data_ref = data_dt.strftime("%Y-%m") if data_dt else None
            return PontoHistoricoPainel(
                True,
                reference,
                mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""),
                data_referencia=data_ref,
                valor=float(valor),
                valor_formatado=valor_txt if isinstance(valor_txt, str) and valor_txt else f"R$ {valor:,.2f}",
                codigo_marca_referencia=codigo_marca_ref,
                codigo_modelo_referencia=codigo_modelo_ref,
                modelo_referencia=str(modelo_ref.get("nome") or modelo_ref.get("name") or ""),
                codigo_ano_referencia=codigo_ano_ref,
                ano_referencia=str(ano_ref.get("nome") or ano_ref.get("name") or ""),
                estrategia="reference_marca_ano_modelos_preco",
                debug={**debug, "score_modelo": round(score, 3)},
            )
        except FipeApiError:
            raise
        except Exception as exc:
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_controlado:{type(exc).__name__}:{str(exc)[:160]}", debug=debug)

    def consultar_ponto_modelo_primeiro_v19(self, *, reference: str, mes_referencia: str, codigo_marca_atual: str, nome_marca: str, nome_modelo: str, ano_base: int, combustivel: str) -> PontoHistoricoPainel:
        """Fluxo V19.15 do painel local: referência -> marca -> modelos -> anos -> preço."""
        debug: dict[str, Any] = {"reference": reference, "mes": mes_referencia, "ano_base": ano_base, "fluxo": "modelo_primeiro_v19"}
        try:
            marcas = self.fipe.listar_marcas_referencia(reference)
            marca_ref = self.escolher_marca_na_referencia(marcas, nome_marca, codigo_marca_atual)
            if not marca_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="marca_nao_encontrada_na_referencia", debug={**debug, "marcas": len(marcas or [])})
            codigo_marca_ref = str(marca_ref.get("codigo") or marca_ref.get("code") or codigo_marca_atual)
            modelos_data = self.fipe.listar_modelos_referencia(codigo_marca_ref, reference)
            modelos = modelos_data.get("modelos", []) if isinstance(modelos_data, dict) else []
            modelo_ref, score, dbg_modelo = self.escolher_modelo_na_referencia(modelos, nome_modelo)
            if not modelo_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="modelo_nao_encontrado_na_referencia", codigo_marca_referencia=codigo_marca_ref, debug={**debug, "modelos": len(modelos or []), "score_melhor": round(score, 3), "modelo_debug": dbg_modelo})
            codigo_modelo_ref = str(modelo_ref.get("codigo") or modelo_ref.get("code") or "")
            anos = self.fipe.listar_anos_referencia(codigo_marca_ref, codigo_modelo_ref, reference)
            ano_ref = self.escolher_ano_na_referencia(anos, ano_base, combustivel)
            if not ano_ref:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="ano_nao_encontrado_na_referencia", codigo_marca_referencia=codigo_marca_ref, codigo_modelo_referencia=codigo_modelo_ref, modelo_referencia=str(modelo_ref.get("nome") or modelo_ref.get("name") or ""), debug={**debug, "anos": len(anos or [])})
            codigo_ano_ref = str(ano_ref.get("codigo") or ano_ref.get("code") or "")
            detalhe = self.fipe.consultar_preco_referencia(codigo_marca_ref, codigo_modelo_ref, codigo_ano_ref, reference)
            valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return PontoHistoricoPainel(False, reference, mes_referencia, motivo="preco_invalido_na_referencia", codigo_marca_referencia=codigo_marca_ref, codigo_modelo_referencia=codigo_modelo_ref, codigo_ano_referencia=codigo_ano_ref, debug=debug)
            data_dt = self.parse_mes_referencia(mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""))
            data_ref = data_dt.strftime("%Y-%m") if data_dt else None
            return PontoHistoricoPainel(True, reference, mes_referencia or str(detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""), data_referencia=data_ref, valor=float(valor), valor_formatado=valor_txt if isinstance(valor_txt, str) and valor_txt else f"R$ {valor:,.2f}", codigo_marca_referencia=codigo_marca_ref, codigo_modelo_referencia=codigo_modelo_ref, modelo_referencia=str(modelo_ref.get("nome") or modelo_ref.get("name") or ""), codigo_ano_referencia=codigo_ano_ref, ano_referencia=str(ano_ref.get("nome") or ano_ref.get("name") or ""), estrategia="v19_15_referencia_marca_modelos_anos_preco", debug={**debug, "score_modelo": round(score, 3)})
        except FipeApiError:
            raise
        except Exception as exc:
            return PontoHistoricoPainel(False, reference, mes_referencia, motivo=f"erro_controlado:{type(exc).__name__}:{str(exc)[:160]}", debug=debug)

    @staticmethod
    def _subtrair_um_mes_dt(data: datetime) -> datetime:
        if data.month == 1:
            return datetime(data.year - 1, 12, 1)
        return datetime(data.year, data.month - 1, 1)

    def _consultar_zero_km_v19(self, *, referencia: dict[str, Any], primeiro_usado: PontoHistoricoPainel) -> PontoHistoricoPainel | None:
        try:
            anos = self.fipe.listar_anos_referencia(primeiro_usado.codigo_marca_referencia, primeiro_usado.codigo_modelo_referencia, str(referencia.get("code") or ""))
            suffix = ""
            if "-" in str(primeiro_usado.codigo_ano_referencia):
                suffix = str(primeiro_usado.codigo_ano_referencia).split("-", 1)[1]
            zero = None
            for a in anos or []:
                codigo = str(a.get("codigo") or a.get("code") or "")
                if not codigo.startswith("32000"):
                    continue
                if suffix and codigo.endswith(f"-{suffix}"):
                    zero = a
                    break
                if zero is None:
                    zero = a
            if not zero:
                return None
            codigo_zero = str(zero.get("codigo") or zero.get("code") or "")
            detalhe = self.fipe.consultar_preco_referencia(primeiro_usado.codigo_marca_referencia, primeiro_usado.codigo_modelo_referencia, codigo_zero, str(referencia.get("code") or ""))
            valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
            valor = parse_float_seguro(valor_txt)
            if not valor or valor <= 0:
                return None
            mes = str(referencia.get("month") or detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or "")
            data_dt = self.parse_mes_referencia(mes)
            if primeiro_usado.data_referencia and data_dt and primeiro_usado.data_referencia == data_dt.strftime("%Y-%m"):
                data_dt = self._subtrair_um_mes_dt(data_dt)
                mes = data_dt.strftime("%m/%Y")
            return PontoHistoricoPainel(True, str(referencia.get("code") or ""), mes, data_referencia=data_dt.strftime("%Y-%m") if data_dt else None, valor=float(valor), valor_formatado=valor_txt if isinstance(valor_txt, str) and valor_txt else f"R$ {valor:,.2f}", codigo_marca_referencia=primeiro_usado.codigo_marca_referencia, codigo_modelo_referencia=primeiro_usado.codigo_modelo_referencia, modelo_referencia=primeiro_usado.modelo_referencia, codigo_ano_referencia=codigo_zero, ano_referencia=str(zero.get("nome") or zero.get("name") or "Zero km"), estrategia="v19_15_zero_km_mes_primeira_aparicao", debug={"tipo": "zero_km"})
        except Exception:
            return None

    def montar_historico_v19_15_adaptado(self, *, codigo_marca_atual: str, nome_marca: str, nome_modelo: str, ano_base: int, combustivel: str, ano_atual: int, max_pontos: int = 24) -> dict[str, Any]:
        referencias = self.referencias_ordenadas()
        if not referencias:
            return {"ok": False, "estrategia_historico": "v19_15_adaptado", "pontos_validos": 0, "erro": "sem_referencias"}
        inicio = datetime(max(int(ano_base) - 1, 1990), 1, 1)
        candidatas_primeira = [r for r in referencias if r.get("data_ref") and r["data_ref"] >= inicio]
        primeiro: PontoHistoricoPainel | None = None
        tentativas_primeira: list[dict[str, Any]] = []
        limite_primeira = 42
        for ref in candidatas_primeira[:limite_primeira]:
            try:
                p = self.consultar_ponto_modelo_primeiro_v19(reference=str(ref.get("code") or ""), mes_referencia=str(ref.get("month") or ""), codigo_marca_atual=codigo_marca_atual, nome_marca=nome_marca, nome_modelo=nome_modelo, ano_base=ano_base, combustivel=combustivel)
                if p.ok and p.valor:
                    primeiro = p
                    break
                if len(tentativas_primeira) < 8:
                    tentativas_primeira.append({"ref": ref.get("code"), "mes": ref.get("month"), "motivo": p.motivo, "debug": p.debug})
            except FipeApiError as exc:
                if exc.status_code == 429:
                    return {"ok": False, "estrategia_historico": "v19_15_adaptado", "pontos_validos": 0, "limite_interrompeu": True, "erro": exc.message}
                if len(tentativas_primeira) < 8:
                    tentativas_primeira.append({"ref": ref.get("code"), "mes": ref.get("month"), "erro": exc.message})
            except Exception as exc:
                if len(tentativas_primeira) < 8:
                    tentativas_primeira.append({"ref": ref.get("code"), "mes": ref.get("month"), "erro": f"{type(exc).__name__}: {str(exc)[:120]}"})
        if not primeiro:
            return {"ok": False, "estrategia_historico": "v19_15_adaptado_modelo_primeiro", "pontos_validos": 0, "erro": "primeira_aparicao_nao_encontrada", "tentativas_primeira_aparicao": tentativas_primeira, "referencias_testadas_primeira_aparicao": min(len(candidatas_primeira), limite_primeira)}
        ref_primeiro = next((r for r in referencias if str(r.get("code")) == str(primeiro.reference)), None)
        zero = self._consultar_zero_km_v19(referencia=ref_primeiro or {}, primeiro_usado=primeiro) if ref_primeiro else None
        data_inicio_hist = None
        if zero and zero.data_referencia:
            data_inicio_hist = self.parse_mes_referencia(zero.mes) or (ref_primeiro and ref_primeiro.get("data_ref"))
        if not data_inicio_hist and ref_primeiro:
            data_inicio_hist = ref_primeiro.get("data_ref")
        refs_hist = [r for r in referencias if r.get("data_ref") and data_inicio_hist and r["data_ref"] >= data_inicio_hist and r["data_ref"].year <= int(ano_atual)]
        if len(refs_hist) > max_pontos:
            idxs = sorted(set(round(i * (len(refs_hist) - 1) / (max_pontos - 1)) for i in range(max_pontos))) if max_pontos > 1 else [len(refs_hist)-1]
            refs_coleta = [refs_hist[i] for i in idxs]
        else:
            refs_coleta = refs_hist
        pontos: list[dict[str, Any]] = []
        if zero and zero.valor:
            z = zero.to_dict(); z["tipo"] = "zero_km"; pontos.append(z)
        falhas = 0; erros_404 = 0; limite = False
        for ref in refs_coleta:
            try:
                detalhe = self.fipe.consultar_preco_referencia(primeiro.codigo_marca_referencia, primeiro.codigo_modelo_referencia, primeiro.codigo_ano_referencia, str(ref.get("code") or ""))
                valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
                valor = parse_float_seguro(valor_txt)
                if not valor or valor <= 0:
                    falhas += 1; continue
                data_dt = self.parse_mes_referencia(str(ref.get("month") or detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""))
                pontos.append({"ok": True, "reference": str(ref.get("code") or ""), "mes": str(ref.get("month") or detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""), "data_referencia": data_dt.strftime("%Y-%m") if data_dt else None, "valor": float(valor), "valor_formatado": valor_txt if isinstance(valor_txt, str) and valor_txt else f"R$ {valor:,.2f}", "codigo_marca_referencia": primeiro.codigo_marca_referencia, "codigo_modelo_referencia": primeiro.codigo_modelo_referencia, "codigo_ano_referencia": primeiro.codigo_ano_referencia, "modelo_referencia": primeiro.modelo_referencia, "ano_referencia": primeiro.ano_referencia, "tipo": "usado", "estrategia": "v19_15_reutiliza_codigos_primeira_aparicao"})
            except FipeApiError as exc:
                if exc.status_code == 429:
                    limite = True; break
                if exc.status_code == 404:
                    erros_404 += 1; continue
                falhas += 1
            except Exception:
                falhas += 1
        uniq = {}
        for p in pontos:
            chave = (p.get("data_referencia") or p.get("reference"), p.get("tipo") or "usado")
            uniq[chave] = p
        pontos = sorted(uniq.values(), key=lambda x: x.get("data_referencia") or x.get("reference") or "")
        variacao = None
        if len(pontos) >= 2 and pontos[0].get("valor"):
            variacao = round(((float(pontos[-1]["valor"]) - float(pontos[0]["valor"])) / float(pontos[0]["valor"])) * 100, 2)
        return {"ok": True, "criterio_passo": "fluxo V19.15 do painel local: primeira aparição + zero km + reutilização dos códigos da coorte", "estrategia_historico": "painel_local_v19_15_adaptado: referencia_marca_modelos_anos_preco_reutiliza_codigos", "pontos_planejados": len(refs_coleta) + (1 if zero else 0), "pontos_validos": len(pontos), "referencias_disponiveis": len(referencias), "referencias_testadas_primeira_aparicao": min(len(candidatas_primeira), limite_primeira), "primeira_aparicao": primeiro.to_dict(), "zero_km_encontrado": zero.to_dict() if zero else None, "falhas_coleta": falhas, "erros_404_ignorados": erros_404, "limite_interrompeu": limite, "primeiro_ponto": pontos[0] if pontos else None, "ultimo_ponto": pontos[-1] if pontos else None, "variacao_percentual_observada": variacao, "amostra": pontos[:12], "pontos": pontos, "tentativas_primeira_aparicao": tentativas_primeira}

