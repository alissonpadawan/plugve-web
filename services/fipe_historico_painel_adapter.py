from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import re

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
            saida.append({"code": code, "month": month, "data_ref": data_ref})
        # Se a data foi parseada, usa data. Se não, mantém ordem por código.
        saida.sort(key=lambda x: (x["data_ref"] or datetime.min, int(x["code"]) if x["code"].isdigit() else 0))
        return saida

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
