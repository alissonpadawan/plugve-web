from __future__ import annotations

from typing import Any
from statistics import median
import math
from datetime import datetime

from core.modelos import VeiculoSelecionado, ResumoDepreciacao
from repositories.curvas_repository import CurvasRepository
from repositories.historico_repository import HistoricoRepository
from repositories.ipca_repository import IpcaRepository
from core.motor_combustao_web import calcular_curva_combustao_por_historico, CalculoCombustaoInvalido
from services.text_utils import detectar_eletrico, parse_float_seguro, parse_int_seguro
from services.fipe_historico_service import FipeHistoricoService
from services.fipe_service import FipeService, FipeApiError


class DepreciacaoService:
    def __init__(self) -> None:
        self.curvas = CurvasRepository()
        self.historico = HistoricoRepository()
        self.ipca = IpcaRepository()
        self.fipe = FipeService()

    def status_bases(self) -> dict[str, Any]:
        return self.curvas.status_bases()

    def obter_resumo(self, payload: dict[str, Any]) -> dict[str, Any]:
        veiculo = VeiculoSelecionado.from_payload(payload)
        tipo_detectado = self._detectar_tipo_por_veiculo(veiculo)
        tipo = self._resolver_tipo(veiculo, tipo_detectado)
        aviso_tipo = self._montar_aviso_tipo(veiculo.tipo, tipo_detectado, tipo)

        if tipo == "eletrico":
            resultado = self.curvas.buscar_curva_eletrico(veiculo)
            tipo_label = "Elétrico ou híbrido"
        else:
            resultado = self.curvas.buscar_curva_combustao(veiculo)
            tipo_label = "Combustão"

        if not resultado:
            mensagem = "Nenhuma curva salva encontrada para este veículo."
            if aviso_tipo:
                mensagem = f"{mensagem} {aviso_tipo}"

            return ResumoDepreciacao(
                encontrado=False,
                status="nao_encontrado",
                mensagem=mensagem,
                tipo_curva=tipo,
                valor_atual=veiculo.valor_atual,
                horizonte_anos=veiculo.horizonte_anos,
                detalhes={
                    "veiculo": veiculo.to_dict(),
                    "tipo_detectado": tipo_detectado,
                    "tipo_utilizado": tipo,
                    "tipo_label": tipo_label,
                    "aviso_tipo": aviso_tipo,
                },
            ).to_dict()

        mensagem = "Curva salva encontrada e carregada com sucesso."
        if tipo == "eletrico":
            mensagem = "Curva EV salva encontrada e carregada com sucesso."
        elif tipo == "combustao":
            mensagem = "Curva de combustão salva encontrada e carregada com sucesso."

        if aviso_tipo:
            mensagem = f"{mensagem} {aviso_tipo}"

        resumo = ResumoDepreciacao(
            encontrado=True,
            status="encontrado",
            mensagem=mensagem,
            tipo_curva=tipo,
            origem_curva=str(resultado.get("origem_curva", "curva salva")),
            confianca=str(resultado.get("confianca", "")),
            valor_atual=float(resultado.get("valor_atual", 0.0)),
            valor_futuro=float(resultado.get("valor_futuro", 0.0)),
            depreciacao_percentual=float(resultado.get("depreciacao_percentual", 0.0)),
            taxa_anual_percentual=float(resultado.get("taxa_anual_percentual", 0.0)),
            horizonte_anos=veiculo.horizonte_anos,
            pontos_historicos=int(resultado.get("pontos_historicos", 0)),
            janela_historica_meses=int(resultado.get("janela_historica_meses", 0)),
            detalhes={
                "veiculo": veiculo.to_dict(),
                "tipo_detectado": tipo_detectado,
                "tipo_utilizado": tipo,
                "tipo_label": tipo_label,
                "tipo_match": resultado.get("tipo_match"),
                "origem_curva": resultado.get("origem_curva"),
                "confianca": resultado.get("confianca"),
                "pontos_historicos": resultado.get("pontos_historicos"),
                "janela_historica_meses": resultado.get("janela_historica_meses"),
                "curva": self._filtrar_curva_para_detalhes(resultado.get("curva") or {}),
                "familia": resultado.get("familia"),
                "aviso_tipo": aviso_tipo,
            },
        )
        return resumo.to_dict()


    def apagar_curva_manual(self, payload: dict[str, Any]) -> dict[str, Any]:
        veiculo = VeiculoSelecionado.from_payload(payload)
        tipo_detectado = self._detectar_tipo_por_veiculo(veiculo)
        tipo = self._resolver_tipo(veiculo, tipo_detectado)
        return self.curvas.apagar_curva_calculada(veiculo, tipo)


    def painel_dados(self) -> dict[str, Any]:
        """Retorna dados consolidados para o painel web de depreciação.

        A tela de depreciação precisa se aproximar do painel original, mas sem
        carregar Tkinter para dentro do Flask. Por isso este método entrega
        apenas dados resumidos de bases, curvas e históricos para o frontend.
        """
        status = self.status_bases()
        curvas_combustao = self.curvas._ler_csv(self.curvas._arquivo_curvas_combustao())
        curvas_eletrico = self.curvas._ler_csv(self.curvas._arquivo_curvas_eletrico())
        hist_combustao = self.historico.carregar_historico_combustao()
        hist_eletrico = self.historico.carregar_historico_eletrico()
        familias = self.curvas.familias.carregar_familias()

        marcas = set()
        familias_ids = set()
        curvas_prontas_combustao_planilha = 0
        curvas_prontas_eletrico_planilha = 0
        historico_pronto_combustao_planilha = 0
        historico_pronto_eletrico_planilha = 0

        for item in familias:
            marca = str(item.get("marca_nome", "") or "").strip()
            if marca:
                marcas.add(marca)
            family_id = str(item.get("family_id", "") or "").strip()
            if family_id:
                familias_ids.add(family_id)
            if self._valor_verdadeiro_painel(item.get("curva_pronta_combustao") or item.get("curva_pronta")):
                curvas_prontas_combustao_planilha += 1
            if self._valor_verdadeiro_painel(item.get("curva_pronta_eletrico")):
                curvas_prontas_eletrico_planilha += 1
            if self._valor_verdadeiro_painel(item.get("historico_baixado_combustao")):
                historico_pronto_combustao_planilha += 1
            if self._valor_verdadeiro_painel(item.get("historico_baixado_eletrico")):
                historico_pronto_eletrico_planilha += 1

        return {
            "status": {
                **status,
                "modelos_cadastrados": len(familias),
                "marcas_cadastradas": len(marcas),
                "familias_cadastradas": len(familias_ids),
                "curvas_prontas_combustao_planilha": curvas_prontas_combustao_planilha,
                "curvas_prontas_eletrico_planilha": curvas_prontas_eletrico_planilha,
                "historico_pronto_combustao_planilha": historico_pronto_combustao_planilha,
                "historico_pronto_eletrico_planilha": historico_pronto_eletrico_planilha,
            },
            "curvas_combustao": [self._resumir_curva(row, "combustao") for row in curvas_combustao[-120:]][::-1],
            "curvas_eletrico": [self._resumir_curva(row, "eletrico") for row in curvas_eletrico[-120:]][::-1],
            "historico_combustao": self._resumir_historico(hist_combustao, "combustao"),
            "historico_eletrico": self._resumir_historico(hist_eletrico, "eletrico"),
        }

    @staticmethod
    def _valor_verdadeiro_painel(valor: Any) -> bool:
        texto = str(valor or "").strip().lower()
        return texto in {"1", "sim", "true", "x", "ok", "pronto"}

    @staticmethod
    def _primeiro_valor(row: dict[str, Any], chaves: list[str], padrao: Any = "") -> Any:
        for chave in chaves:
            valor = row.get(chave)
            if valor not in (None, ""):
                return valor
        return padrao

    def _resumir_curva(self, row: dict[str, Any], tipo: str) -> dict[str, Any]:
        taxa = self._primeiro_valor(row, [
            "depreciacao_media_anual_principal_percentual",
            "depreciacao_media_anual_percentual",
            "taxa_anual_percentual",
            "taxa_anual_base_efetiva",
        ], 0)
        pontos = self._primeiro_valor(row, ["observacoes_total", "pontos_historicos", "numero_observacoes_total"], 0)
        janela = self._primeiro_valor(row, ["janela_historica_meses", "janela_meses"], 0)
        titulo = self._primeiro_valor(row, ["titulo", "veiculo", "modelo"], "Curva salva")
        marca = self._primeiro_valor(row, ["marca", "brand"], "")
        modelo = self._primeiro_valor(row, ["modelo", "model"], "")
        if marca and modelo:
            titulo_final = f"{marca} {modelo}".strip()
        else:
            titulo_final = str(titulo or "Curva salva").strip()

        return {
            "tipo": tipo,
            "titulo": titulo_final,
            "marca": str(marca or ""),
            "modelo": str(modelo or ""),
            "ano_modelo": str(self._primeiro_valor(row, ["ano_modelo", "ano_base_curva", "ano_modelo_proxy"], "")),
            "codigo_fipe": str(self._primeiro_valor(row, ["codigo_fipe", "codeFipe"], "")),
            "taxa_anual_percentual": parse_float_seguro(taxa, 0.0),
            "depreciacao_percentual": parse_float_seguro(self._primeiro_valor(row, ["depreciacao_percentual_base", "depreciacao_percentual", "depreciacao_acumulada_percentual"], 0), 0.0),
            "valor_atual": parse_float_seguro(self._primeiro_valor(row, ["valor_fipe_atual", "valor_atual", "preco_atual_real"], 0), 0.0),
            "valor_futuro": parse_float_seguro(self._primeiro_valor(row, ["valor_futuro_base", "valor_futuro", "valor_estimado_futuro_principal"], 0), 0.0),
            "confianca": str(self._primeiro_valor(row, ["confianca", "confianca_ev", "status_final"], "-")),
            "origem": str(self._primeiro_valor(row, ["origem_curva", "fonte_ajuste", "fonte"], "curva salva")),
            "pontos_historicos": parse_int_seguro(pontos, 0),
            "janela_historica_meses": parse_int_seguro(janela, 0),
            "periodo_inicial": str(self._primeiro_valor(row, ["periodo_inicial", "data_inicial"], "")),
            "periodo_final": str(self._primeiro_valor(row, ["periodo_final", "data_final"], "")),
        }

    def _resumir_historico(self, linhas: list[dict[str, Any]], tipo: str) -> list[dict[str, Any]]:
        grupos: dict[str, dict[str, Any]] = {}
        for row in linhas:
            codigo = str(self._primeiro_valor(row, ["codigo_fipe", "CodigoFipe", "titulo"], "")).strip()
            marca = str(self._primeiro_valor(row, ["marca", "brand"], "")).strip()
            modelo = str(self._primeiro_valor(row, ["modelo", "model", "titulo", "veiculo"], "")).strip()
            codigo_ano = str(self._primeiro_valor(row, ["codigo_ano", "ano_fipe_codigo"], "")).strip()
            chave = "|".join([codigo, codigo_ano, marca, modelo])
            if not chave.strip("|"):
                continue
            data_ref = str(self._primeiro_valor(row, ["data_referencia", "mes_referencia"], ""))[:7]
            valor = parse_float_seguro(self._primeiro_valor(row, ["valor_fipe", "preco", "preco_corrigido"], 0), 0.0)
            item = grupos.setdefault(chave, {
                "tipo": tipo,
                "codigo_fipe": codigo,
                "codigo_ano": codigo_ano,
                "marca": marca,
                "modelo": modelo,
                "titulo": f"{marca} {modelo}".strip() or modelo or codigo or "Histórico",
                "pontos": 0,
                "periodo_inicial": data_ref,
                "periodo_final": data_ref,
                "primeiro_valor": valor,
                "ultimo_valor": valor,
            })
            item["pontos"] += 1
            if data_ref and (not item["periodo_inicial"] or data_ref < item["periodo_inicial"]):
                item["periodo_inicial"] = data_ref
                item["primeiro_valor"] = valor
            if data_ref and (not item["periodo_final"] or data_ref > item["periodo_final"]):
                item["periodo_final"] = data_ref
                item["ultimo_valor"] = valor

        saida = list(grupos.values())
        saida.sort(key=lambda x: (x.get("periodo_final") or "", x.get("pontos") or 0), reverse=True)
        return saida[:120]


    def preparar_calculo_sob_demanda(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calcula depreciação sob demanda e salva a curva para uso futuro.

        Fluxo V23:
        - se existir motor/histórico real de combustão, usa esse caminho;
        - se o histórico for insuficiente, usa proxy técnico por curvas cadastradas;
        - para elétricos/híbridos, usa proxy técnico EV baseado nas curvas EV locais;
        - após calcular, salva no CSV correspondente para a próxima consulta carregar automático.
        """
        veiculo = VeiculoSelecionado.from_payload(payload)
        tipo_detectado = self._detectar_tipo_por_veiculo(veiculo)
        tipo = self._resolver_tipo(veiculo, tipo_detectado)
        aviso_tipo = self._montar_aviso_tipo(veiculo.tipo, tipo_detectado, tipo)

        if tipo == "eletrico":
            resultado_motor = self._calcular_eletrico_por_historico_ou_proxy(veiculo)
            curva_salva = self.curvas.salvar_curva_eletrica_calculada(veiculo, resultado_motor)
            resumo = self._montar_resumo_calculado(
                veiculo=veiculo,
                resultado_motor=resultado_motor,
                curva_salva=curva_salva,
                tipo="eletrico",
                tipo_label="Elétrico ou híbrido",
                origem=str(resultado_motor.get("origem_curva") or "cálculo sob demanda EV"),
                aviso_tipo=aviso_tipo,
            )
            return {
                "ok": True,
                "status": "calculado",
                "mensagem": "Curva EV/híbrida calculada e salva com sucesso.",
                "tipo_detectado": tipo_detectado,
                "tipo_utilizado": tipo,
                "tipo_label": "Elétrico ou híbrido",
                "aviso_tipo": aviso_tipo,
                "veiculo": veiculo.to_dict(),
                "resultado": resumo,
                "motor": resultado_motor,
                "proxima_etapa": "Curva salva. Na próxima consulta, o carregamento será automático.",
            }

        try:
            if self._veiculo_zero_km(veiculo):
                resultado_motor = self._calcular_combustao_zero_km_por_proxy(veiculo)
            else:
                historico_api, origem_api, ref_api = self._historico_api_v2_price_history(veiculo)
                historico = historico_api if len(historico_api) >= 2 else self.historico.buscar_historico_combustao_veiculo(veiculo)
                resultado_motor = calcular_curva_combustao_por_historico(
                    veiculo=veiculo,
                    historico=historico,
                ).to_dict()
                if len(historico_api) >= 2:
                    resultado_motor["origem_curva"] = origem_api
                    resultado_motor["tipo_match"] = "historico_fipe_api_v2_price_history"
                    auditoria = dict(resultado_motor.get("auditoria_historico") or {})
                    auditoria.update(ref_api or {})
                    auditoria["proxy_aplicado"] = False
                    auditoria["fonte_historico"] = "priceHistory API v2"
                    resultado_motor["auditoria_historico"] = auditoria
        except CalculoCombustaoInvalido as exc:
            resultado_motor = self._calcular_proxy_tecnico(veiculo, tipo="combustao", auditoria_origem=exc.auditoria, mensagem_origem=str(exc))
        except Exception as exc:
            resultado_motor = self._calcular_proxy_tecnico(veiculo, tipo="combustao", auditoria_origem={}, mensagem_origem=str(exc))

        curva_salva = self.curvas.salvar_curva_combustao_calculada(veiculo, resultado_motor)
        resumo = self._montar_resumo_calculado(
            veiculo=veiculo,
            resultado_motor=resultado_motor,
            curva_salva=curva_salva,
            tipo="combustao",
            tipo_label="Combustão",
            origem=str(resultado_motor.get("origem_curva") or "cálculo sob demanda combustão"),
            aviso_tipo=aviso_tipo,
        )

        return {
            "ok": True,
            "status": "calculado",
            "mensagem": "Curva de combustão calculada e salva com sucesso.",
            "tipo_detectado": tipo_detectado,
            "tipo_utilizado": tipo,
            "tipo_label": "Combustão",
            "aviso_tipo": aviso_tipo,
            "veiculo": veiculo.to_dict(),
            "resultado": resumo,
            "motor": resultado_motor,
            "proxima_etapa": "Curva salva. Na próxima consulta, o carregamento será automático.",
        }

    def _montar_resumo_calculado(
        self,
        *,
        veiculo: VeiculoSelecionado,
        resultado_motor: dict[str, Any],
        curva_salva: dict[str, Any],
        tipo: str,
        tipo_label: str,
        origem: str,
        aviso_tipo: str = "",
    ) -> dict[str, Any]:
        return ResumoDepreciacao(
            encontrado=True,
            status="calculado",
            mensagem="Curva calculada e salva com sucesso.",
            tipo_curva=tipo,
            origem_curva=origem,
            confianca=str(resultado_motor.get("confianca", "")),
            valor_atual=float(resultado_motor.get("valor_atual", 0.0)),
            valor_futuro=float(resultado_motor.get("valor_futuro", 0.0)),
            depreciacao_percentual=float(resultado_motor.get("depreciacao_percentual", 0.0)),
            taxa_anual_percentual=float(resultado_motor.get("taxa_anual_percentual", 0.0)),
            horizonte_anos=veiculo.horizonte_anos,
            pontos_historicos=int(resultado_motor.get("pontos_historicos", 0)),
            janela_historica_meses=int(resultado_motor.get("janela_historica_meses", 0)),
            detalhes={
                "veiculo": veiculo.to_dict(),
                "tipo_detectado": tipo,
                "tipo_utilizado": tipo,
                "tipo_label": tipo_label,
                "tipo_match": resultado_motor.get("tipo_match"),
                "origem_curva": origem,
                "confianca": resultado_motor.get("confianca"),
                "pontos_historicos": resultado_motor.get("pontos_historicos"),
                "janela_historica_meses": resultado_motor.get("janela_historica_meses"),
                "periodo_inicial": resultado_motor.get("periodo_inicial"),
                "periodo_final": resultado_motor.get("periodo_final"),
                "valor_futuro_otimista": resultado_motor.get("valor_futuro_otimista"),
                "valor_futuro_pessimista": resultado_motor.get("valor_futuro_pessimista"),
                "auditoria_historico": resultado_motor.get("auditoria_historico"),
                "curva": self._filtrar_curva_para_detalhes(curva_salva),
                "familia": None,
                "aviso_tipo": aviso_tipo,
            },
        ).to_dict()



    def _historico_api_v2_price_history(self, veiculo: VeiculoSelecionado) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
        """Busca histórico mensal retornado pela API FIPE v2/fipe.online.

        A API nova pode devolver priceHistory junto com o detalhe do veículo.
        Para seleção Zero km, preferimos usar o ano usado mais recente do mesmo
        modelo como curva histórica e aplicar essa curva ao valor zero km atual.
        Isso evita tratar variação de preço de tabela do carro novo como
        depreciação real.
        """
        if not veiculo.codigo_marca or not veiculo.codigo_modelo or not veiculo.codigo_ano:
            return [], "histórico FIPE API v2 não consultado: códigos incompletos", None

        codigo_ano_original = str(veiculo.codigo_ano or "").strip()
        codigo_ano_consulta = codigo_ano_original
        proxy_ano = None

        try:
            if self._veiculo_zero_km(veiculo):
                anos = self.fipe.listar_anos(str(veiculo.codigo_marca), str(veiculo.codigo_modelo))
                candidatos = []
                for item in anos or []:
                    cod = str(item.get("codigo", "") or "").strip()
                    nome = str(item.get("nome", "") or "").strip()
                    ano_txt = cod.split("-", 1)[0]
                    if ano_txt == "32000" or not ano_txt.isdigit():
                        continue
                    ano_int = int(ano_txt)
                    if ano_int >= 2012:
                        candidatos.append((ano_int, cod, nome))
                if candidatos:
                    candidatos.sort(reverse=True)
                    ano_int, cod, nome = candidatos[0]
                    codigo_ano_consulta = cod
                    proxy_ano = {"codigo_ano_proxy": cod, "ano_modelo_proxy": ano_int, "nome_proxy": nome}

            detalhe = self.fipe.consultar_preco(str(veiculo.codigo_marca), str(veiculo.codigo_modelo), codigo_ano_consulta)
        except Exception as exc:
            return [], f"histórico FIPE API v2 indisponível: {exc}", None

        historico_bruto = detalhe.get("HistoricoPreco") or detalhe.get("priceHistory") or []
        saida = []
        vistos = set()
        for row in historico_bruto if isinstance(historico_bruto, list) else []:
            data_ref = self._parse_mes_referencia_api(row.get("month") or row.get("mes") or row.get("referenceMonth") or "")
            if not data_ref:
                ref_num = str(row.get("reference") or row.get("referencia") or "").strip()
                if ref_num.isdigit():
                    # Sem mês legível, não força data falsa para não contaminar IPCA.
                    continue
            valor = parse_float_seguro(row.get("price") or row.get("preco") or row.get("Valor"), 0.0)
            if not data_ref or valor <= 0:
                continue
            if data_ref in vistos:
                continue
            vistos.add(data_ref)
            saida.append({
                "data_referencia": data_ref,
                "valor_fipe": round(float(valor), 2),
                "codigo_fipe": str(detalhe.get("CodigoFipe") or detalhe.get("codeFipe") or veiculo.codigo_fipe or "").strip(),
                "marca": str(detalhe.get("Marca") or detalhe.get("brand") or veiculo.marca or "").strip(),
                "modelo": str(detalhe.get("Modelo") or detalhe.get("model") or veiculo.modelo or "").strip(),
                "ano_modelo": str(detalhe.get("AnoModelo") or detalhe.get("modelYear") or veiculo.ano_modelo or "").strip(),
                "combustivel": str(detalhe.get("Combustivel") or detalhe.get("fuel") or veiculo.combustivel or "").strip(),
                "codigo_marca": str(veiculo.codigo_marca),
                "codigo_modelo": str(veiculo.codigo_modelo),
                "codigo_ano": codigo_ano_consulta,
                "origem": "fipe_api_v2_price_history",
            })

        saida.sort(key=lambda x: str(x.get("data_referencia", "")))
        if len(saida) >= 2:
            if proxy_ano:
                origem = f"histórico FIPE API v2 do ano {proxy_ano.get('ano_modelo_proxy')} aplicado ao zero km"
                return saida, origem, {**proxy_ano, "fonte": "priceHistory API v2", "codigo_ano_original": codigo_ano_original, "proxy_aplicado": True}
            return saida, "histórico próprio FIPE API v2 (priceHistory)", {"fonte": "priceHistory API v2", "proxy_aplicado": False}
        return [], "histórico FIPE API v2 sem pontos suficientes", {"pontos_api": len(saida), "proxy_aplicado": bool(proxy_ano), **(proxy_ano or {})}

    @staticmethod
    def _parse_mes_referencia_api(texto: Any) -> str | None:
        txt = str(texto or "").strip().lower()
        if not txt:
            return None
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
        m = re.search(r"(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})", txt)
        if not m:
            m = re.search(r"(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)[/\s-]+(\d{4})", txt)
        if not m:
            return None
        mes = meses.get(m.group(1))
        ano = int(m.group(2))
        if not mes:
            return None
        return f"{ano:04d}-{mes:02d}"

    def _calcular_eletrico_por_historico_ou_proxy(self, veiculo: VeiculoSelecionado) -> dict[str, Any]:
        """Motor EV V23 baseado no painel antigo.

        Fluxo técnico:
        1. tenta usar histórico próprio do modelo/ano selecionado;
        2. se não existir série suficiente, usa uma curva EV salva tecnicamente similar;
        3. aplica a taxa mensal sobre o valor FIPE atual do veículo selecionado;
        4. considera idade de entrada para suavizar a depreciação ao longo do tempo;
        5. marca claramente quando o cálculo é próprio ou proxy.
        """
        historico, origem_hist, ref = self._buscar_historico_ev_compativel(veiculo)
        indices = self.ipca.carregar_indices()

        if len(historico) >= 2 and indices:
            return self._calcular_ev_v21_simplificado(
                veiculo=veiculo,
                historico=historico,
                origem_hist=origem_hist,
                referencia=ref,
                indices_ipca=indices,
            )

        # Último fallback: curva EV salva similar. Não é apresentado como curva própria.
        return self._calcular_proxy_tecnico(veiculo, tipo="eletrico", auditoria_origem={
            "motivo": "histórico próprio/similar insuficiente para o motor EV V21",
            "pontos_historicos_encontrados": len(historico),
        })

    def _buscar_historico_ev_compativel(self, veiculo: VeiculoSelecionado) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
        linhas = self.historico.carregar_historico_eletrico()
        curvas = self.curvas._ler_csv(self.curvas._arquivo_curvas_eletrico())
        alvo_marca = self._normalizar_local(veiculo.marca)
        alvo_modelo = self._normalizar_modelo_ev(veiculo.modelo)
        alvo_tokens = self._tokens_modelo_ev(alvo_modelo)

        # 0) Primeiro tenta o histórico real retornado pela API FIPE v2/fipe.online.
        historico_api, origem_api, ref_api = self._historico_api_v2_price_history(veiculo)
        if len(historico_api) >= 2:
            return self._ordenar_historico_ev(historico_api), origem_api, ref_api

        def linha_texto(row: dict[str, Any]) -> str:
            return self._normalizar_modelo_ev(" ".join(str(row.get(k, "") or "") for k in ["titulo", "marca", "modelo", "categoria"]))

        # 1) Histórico próprio por código do modelo, quando existir.
        codigo_modelo = str(veiculo.codigo_modelo or "").strip()
        codigo_marca = str(veiculo.codigo_marca or "").strip()
        proprios = []
        if codigo_modelo:
            for row in linhas:
                if str(row.get("modelo_id", "") or "").strip().replace(".0", "") == codigo_modelo:
                    if not codigo_marca or str(row.get("marca_id", "") or "").strip().replace(".0", "") == codigo_marca:
                        proprios.append(row)
        if len(proprios) >= 2:
            return self._ordenar_historico_ev(proprios), "histórico próprio do modelo FIPE", None

        # 2) Histórico próprio/aproximado por nome completo.
        por_nome = []
        for row in linhas:
            texto = linha_texto(row)
            if alvo_marca and alvo_marca not in texto:
                continue
            if alvo_modelo and (alvo_modelo in texto or texto in alvo_modelo):
                por_nome.append(row)
        if len(por_nome) >= 2:
            return self._ordenar_historico_ev(por_nome), "histórico próprio por nome FIPE", None

        # 3) Histórico similar por família/token, evitando usar Mini quando o alvo não é Mini.
        melhor_score = 0
        melhor_titulo = ""
        for row in linhas:
            texto = linha_texto(row)
            score = self._score_similaridade_ev(alvo_marca, alvo_modelo, alvo_tokens, texto)
            if score > melhor_score:
                melhor_score = score
                melhor_titulo = str(row.get("titulo", "") or "").strip()
        if melhor_score >= 38 and melhor_titulo:
            similares = [r for r in linhas if str(r.get("titulo", "") or "").strip() == melhor_titulo]
            if len(similares) >= 2:
                ref = {"titulo": melhor_titulo, "score": melhor_score}
                return self._ordenar_historico_ev(similares), f"proxy por histórico EV similar: {melhor_titulo}", ref

        # 4) Se não há histórico, usa a melhor curva salva como referência para extrair taxa.
        referencia, score = self._escolher_curva_referencia(curvas, veiculo, "eletrico")
        if referencia:
            ref_titulo = str(referencia.get("titulo") or referencia.get("modelo") or "curva EV similar")
            return [], f"proxy por curva EV similar: {ref_titulo}", {**referencia, "score": score}
        return [], "histórico EV não encontrado", None

    @staticmethod
    def _ordenar_historico_ev(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saida = []
        for row in linhas:
            data = str(row.get("data_referencia", "") or "").strip()[:7]
            valor = parse_float_seguro(row.get("valor_fipe"), 0.0)
            if data and valor > 0:
                novo = dict(row)
                novo["data_referencia"] = data
                novo["valor_fipe"] = valor
                saida.append(novo)
        saida.sort(key=lambda r: r["data_referencia"])
        return saida

    @staticmethod
    def _normalizar_modelo_ev(valor: Any) -> str:
        texto = str(valor or "")
        for termo in ["(elétrico)", "(eletrico)", "elétrico", "eletrico", "ev", "zero km", "0 km", "híbrido", "hibrido"]:
            texto = texto.replace(termo, " ").replace(termo.upper(), " ").replace(termo.title(), " ")
        try:
            from services.text_utils import normalizar_texto
            return normalizar_texto(texto)
        except Exception:
            return texto.lower().strip()

    @staticmethod
    def _tokens_modelo_ev(modelo_norm: str) -> set[str]:
        stop = {"plus", "mini", "pro", "ev", "gl", "gs", "aut", "mec", "16v", "12v", "eletrico", "hibrido", "zero", "km"}
        return {t for t in str(modelo_norm or "").split() if len(t) >= 3 and t not in stop}

    def _score_similaridade_ev(self, marca: str, modelo: str, tokens: set[str], texto: str) -> int:
        score = 0
        if marca and marca in texto:
            score += 25
        if modelo and modelo in texto:
            score += 70
        if tokens:
            score += min(45, sum(1 for t in tokens if t in texto) * 22)
        # Penaliza família errada conhecida.
        if "mini" in texto and "mini" not in modelo:
            score -= 20
        if "plus" in texto and "plus" not in modelo:
            score -= 8
        return score

    @staticmethod
    def _resolver_mes_ipca(data_ref: str, indices: dict[str, float]) -> str | None:
        if data_ref in indices:
            return data_ref
        chaves = sorted(indices.keys())
        anteriores = [k for k in chaves if k <= data_ref]
        if anteriores:
            return anteriores[-1]
        return chaves[0] if chaves else None

    @staticmethod
    def _meses_entre(data_inicial: str, data_final: str) -> int:
        d0 = datetime.strptime(str(data_inicial).strip()[:7], "%Y-%m")
        d1 = datetime.strptime(str(data_final).strip()[:7], "%Y-%m")
        return max(0, (d1.year - d0.year) * 12 + (d1.month - d0.month))

    @staticmethod
    def _taxa_mensal_por_intervalo(v0: float, v1: float, meses: int) -> float | None:
        if v0 <= 0 or v1 <= 0 or meses <= 0:
            return None
        razao = v1 / v0
        if razao <= 0:
            return None
        taxa = 1.0 - (razao ** (1.0 / meses))
        if math.isnan(taxa) or math.isinf(taxa):
            return None
        return max(0.0, taxa * 100.0)

    @staticmethod
    def _fator_taper_idade(idade_meses: int) -> float:
        idade_anos = max(0.0, float(idade_meses) / 12.0)
        if idade_anos <= 1.0:
            return 1.00
        if idade_anos <= 3.0:
            return 1.00 - ((idade_anos - 1.0) / 2.0) * 0.15
        if idade_anos <= 5.0:
            return 0.85 - ((idade_anos - 3.0) / 2.0) * 0.15
        if idade_anos <= 8.0:
            return 0.70 - ((idade_anos - 5.0) / 3.0) * 0.15
        if idade_anos <= 12.0:
            return 0.55 - ((idade_anos - 8.0) / 4.0) * 0.10
        return 0.45

    def _fator_cumulativo_por_idade(self, taxa_mensal_percentual: float, idade_entrada_meses: int, horizonte_meses: int) -> float:
        taxa_base = max(0.0, float(taxa_mensal_percentual) / 100.0)
        fator = 1.0
        for passo in range(max(0, int(horizonte_meses))):
            idade_mes_atual = max(0, int(idade_entrada_meses)) + passo
            taxa_mes = max(0.0, taxa_base * self._fator_taper_idade(idade_mes_atual))
            fator *= (1.0 - taxa_mes)
        return fator

    @staticmethod
    def _taxa_anual_efetiva_do_fator(fator: float, horizonte_meses: int) -> float:
        if horizonte_meses <= 0 or fator <= 0:
            return 0.0
        anos = horizonte_meses / 12.0
        return max(0.0, (1.0 - (float(fator) ** (1.0 / anos))) * 100.0)

    def _calcular_ev_v21_simplificado(
        self,
        *,
        veiculo: VeiculoSelecionado,
        historico: list[dict[str, Any]],
        origem_hist: str,
        referencia: dict[str, Any] | None,
        indices_ipca: dict[str, float],
    ) -> dict[str, Any]:
        hist = self._ordenar_historico_ev(historico)
        corrigido = []
        meses_ipca = [self._resolver_mes_ipca(str(x["data_referencia"]), indices_ipca) for x in hist]
        meses_ipca = [m for m in meses_ipca if m]
        mes_base = min(meses_ipca) if meses_ipca else None
        indice_base = indices_ipca.get(mes_base, 0.0) if mes_base else 0.0
        for item in hist:
            mes_ipca = self._resolver_mes_ipca(str(item["data_referencia"]), indices_ipca)
            indice_ref = indices_ipca.get(mes_ipca, 0.0) if mes_ipca else 0.0
            if not indice_base or not indice_ref:
                continue
            novo = dict(item)
            novo["preco_corrigido"] = float(item["valor_fipe"]) * (indice_base / indice_ref)
            corrigido.append(novo)

        taxas = []
        for ant, atual in zip(corrigido[:-1], corrigido[1:]):
            meses = self._meses_entre(ant["data_referencia"], atual["data_referencia"])
            taxa = self._taxa_mensal_por_intervalo(float(ant["preco_corrigido"]), float(atual["preco_corrigido"]), meses)
            if taxa is not None:
                taxas.append(taxa)
        if not taxas:
            return self._calcular_proxy_tecnico(veiculo, tipo="eletrico", auditoria_origem={"motivo": "histórico EV sem taxa válida"})

        taxa_curva = float(median(taxas))
        taxa_cauda = float(sum(taxas[-min(6, len(taxas)):]) / min(6, len(taxas)))
        taxa_hibrida = (taxa_curva * 0.60) + (taxa_cauda * 0.40)

        valor_atual = float(veiculo.valor_atual or 0.0)
        horizonte_anos = max(1, int(veiculo.horizonte_anos or 5))
        horizonte_meses = horizonte_anos * 12
        janela_meses = self._meses_entre(hist[0]["data_referencia"], hist[-1]["data_referencia"])
        data_origem_idade = str(hist[0]["data_referencia"])
        idade_entrada_meses = self._meses_entre(data_origem_idade, hist[-1]["data_referencia"])

        # Para seleção Zero km, a projeção começa da idade zero. Para usados, ela continua a curva histórica.
        idade_projecao_meses = 0 if self._veiculo_zero_km(veiculo) or str(veiculo.ano_modelo).lower().startswith("zero") else idade_entrada_meses
        fator_base = self._fator_cumulativo_por_idade(taxa_hibrida, idade_projecao_meses, horizonte_meses)
        fator_ot = self._fator_cumulativo_por_idade(taxa_hibrida * 0.85, idade_projecao_meses, horizonte_meses)
        fator_pe = self._fator_cumulativo_por_idade(taxa_hibrida * 1.25, idade_projecao_meses, horizonte_meses)

        valor_futuro = max(0.0, valor_atual * fator_base)
        dep_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        taxa_anual = self._taxa_anual_efetiva_do_fator(fator_base, horizonte_meses)

        pontos = len(hist)
        primeiro_valor = float(hist[0].get("valor_fipe") or 0.0) if hist else 0.0
        ultimo_valor = float(hist[-1].get("valor_fipe") or 0.0) if hist else 0.0
        valores_hist = [float(x.get("valor_fipe") or 0.0) for x in hist if float(x.get("valor_fipe") or 0.0) > 0]
        variacao_total = ((ultimo_valor - primeiro_valor) / primeiro_valor * 100.0) if primeiro_valor > 0 else 0.0
        modo_calculo = "zero_km_curva_desde_idade_zero" if self._veiculo_zero_km(veiculo) or str(veiculo.ano_modelo).lower().startswith("zero") else "usado_continua_curva_a_partir_da_idade_atual"

        if origem_hist.startswith("histórico próprio") and pontos >= 24 and janela_meses >= 24:
            confianca = "ALTA"
        elif origem_hist.startswith("histórico próprio") and pontos >= 8:
            confianca = "MÉDIA"
        else:
            confianca = "EXPLORATÓRIA"

        return {
            "status": "calculado_ev_v21_web",
            "mensagem": "Curva EV calculada com motor de histórico e salva para reutilização.",
            "veiculo_titulo": f"{veiculo.marca} {veiculo.modelo} {'Zero km' if self._veiculo_zero_km(veiculo) else veiculo.ano_modelo}".strip(),
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_otimista": round(max(0.0, valor_atual * fator_ot), 2),
            "valor_futuro_pessimista": round(max(0.0, valor_atual * fator_pe), 2),
            "depreciacao_percentual": round(max(0.0, dep_pct), 2),
            "taxa_anual_percentual": round(taxa_anual, 2),
            "taxa_mensal_percentual": round(taxa_hibrida, 6),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela_meses,
            "periodo_inicial": hist[0]["data_referencia"],
            "periodo_final": hist[-1]["data_referencia"],
            "confianca": confianca,
            "origem_curva": origem_hist,
            "tipo_match": "historico_ev_v21_web" if origem_hist.startswith("histórico próprio") else "proxy_ev_v21_web",
            "horizonte_anos": horizonte_anos,
            "auditoria_historico": {
                "metodo_taxa": "motor_ev_v21_historico_ipca_taper_idade",
                "modo_calculo": modo_calculo,
                "primeiro_valor": round(primeiro_valor, 2),
                "ultimo_valor": round(ultimo_valor, 2),
                "menor_valor": round(min(valores_hist), 2) if valores_hist else 0,
                "maior_valor": round(max(valores_hist), 2) if valores_hist else 0,
                "variacao_total_percentual": round(variacao_total, 2),
                "taxa_mensal_curva_percentual": round(taxa_curva, 6),
                "taxa_mensal_cauda_percentual": round(taxa_cauda, 6),
                "taxa_mensal_hibrida_percentual": round(taxa_hibrida, 6),
                "data_origem_idade": data_origem_idade,
                "idade_entrada_meses": idade_entrada_meses,
                "idade_projecao_meses": idade_projecao_meses,
                "ipca_base": mes_base or "",
                "referencia": referencia or {},
                "proxy_aplicado": not origem_hist.startswith("histórico próprio"),
                "fonte_historico": "priceHistory API v2" if "API v2" in origem_hist else "base local",
                "observacao": "Para veículo usado, a curva histórica é entendida como trajetória já percorrida; a projeção parte do valor FIPE atual e continua a curva no ponto de idade estimado. Para zero km, a projeção começa na idade zero.",
            },
        }

    def _calcular_proxy_tecnico(self, veiculo: VeiculoSelecionado, tipo: str, auditoria_origem: dict[str, Any] | None = None, mensagem_origem: str = "") -> dict[str, Any]:
        """Cálculo seguro por proxy técnico usando as curvas já validadas no painel.

        Não inventa taxa fixa seca: procura curva parecida por marca/modelo. Se não houver
        similaridade suficiente, usa mediana das taxas positivas da base do mesmo tipo e marca
        como fallback. O resultado é marcado como proxy/estimativa técnica.
        """
        curvas = self.curvas._ler_csv(self.curvas._arquivo_curvas_eletrico() if tipo == "eletrico" else self.curvas._arquivo_curvas_combustao())
        referencia, score = self._escolher_curva_referencia(curvas, veiculo, tipo)
        taxas = []
        for row in curvas:
            taxa = self._extrair_taxa_curva(row, tipo)
            if 0.1 <= taxa <= 35:
                taxas.append(taxa)
        taxa_ref = self._extrair_taxa_curva(referencia or {}, tipo) if referencia else 0.0
        if taxa_ref <= 0 and taxas:
            taxa_ref = float(median(taxas))
        if taxa_ref <= 0:
            taxa_ref = 11.0 if tipo == "eletrico" else 9.5

        valor_atual = float(veiculo.valor_atual or 0.0)
        horizonte = max(1, int(veiculo.horizonte_anos or 5))
        taxa_mensal = (1.0 - ((1.0 - taxa_ref / 100.0) ** (1.0 / 12.0))) * 100.0
        fator = (1.0 - taxa_mensal / 100.0) ** (horizonte * 12)
        valor_futuro = max(0.0, valor_atual * fator)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0

        pontos = parse_int_seguro((referencia or {}).get("pontos_historicos") or (referencia or {}).get("observacoes_total"), 0)
        janela = parse_int_seguro((referencia or {}).get("janela_historica_meses"), 0)
        confianca = "MÉDIA" if referencia and score >= 50 else "EXPLORATÓRIA"
        origem_ref = "curva similar da base EV" if tipo == "eletrico" else "curva similar da base combustão"
        if not referencia:
            origem_ref = "mediana das curvas cadastradas"
        titulo_ref = (referencia or {}).get("titulo") or (referencia or {}).get("veiculo") or "base cadastrada"

        return {
            "status": "calculado_proxy_tecnico",
            "mensagem": "Curva calculada por proxy técnico e salva para reutilização.",
            "veiculo_titulo": f"{veiculo.marca} {veiculo.modelo} {'Zero km' if self._veiculo_zero_km(veiculo) else veiculo.ano_modelo}".strip(),
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_ref), 2),
            "taxa_mensal_percentual": round(max(0.0, taxa_mensal), 6),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "periodo_inicial": (referencia or {}).get("periodo_inicial", ""),
            "periodo_final": (referencia or {}).get("periodo_final", ""),
            "confianca": confianca,
            "origem_curva": f"cálculo sob demanda por proxy técnico ({origem_ref})",
            "tipo_match": "proxy_tecnico_base_local",
            "horizonte_anos": horizonte,
            "auditoria_historico": {
                "metodo_taxa": "proxy_tecnico_base_local",
                "proxy_aplicado": True,
                "curva_referencia": str(titulo_ref),
                "score_referencia": score,
                "mensagem_origem": mensagem_origem,
                "auditoria_origem": auditoria_origem or {},
                "observacao": "Taxa extraída de curva cadastrada semelhante e aplicada ao valor FIPE atual do veículo selecionado.",
            },
        }

    def _extrair_taxa_curva(self, row: dict[str, Any], tipo: str) -> float:
        chaves = ["depreciacao_media_anual_percentual", "depreciacao_media_anual_principal_percentual", "taxa_anual_percentual", "taxa_anual_base_efetiva"]
        for chave in chaves:
            taxa = parse_float_seguro(row.get(chave), 0.0)
            if taxa > 0:
                return taxa
        taxa_mensal = parse_float_seguro(row.get("taxa_mensal_base_cenario_percentual") or row.get("taxa_mensal_hibrida_percentual"), 0.0)
        if taxa_mensal > 0:
            return (1.0 - ((1.0 - taxa_mensal / 100.0) ** 12.0)) * 100.0
        return 0.0

    def _escolher_curva_referencia(self, curvas: list[dict[str, Any]], veiculo: VeiculoSelecionado, tipo: str) -> tuple[dict[str, Any] | None, int]:
        alvo_marca = self._normalizar_local(veiculo.marca)
        alvo_modelo = self._normalizar_local(veiculo.modelo)
        tokens_alvo = {t for t in alvo_modelo.split() if len(t) >= 3 and t not in {"eletrico", "hibrido", "flex", "aut", "mec", "16v", "12v"}}
        melhor: tuple[int, dict[str, Any] | None] = (0, None)
        for row in curvas:
            texto = self._normalizar_local(" ".join(str(row.get(k, "") or "") for k in ["marca", "modelo", "titulo", "veiculo"]))
            taxa = self._extrair_taxa_curva(row, tipo)
            if taxa <= 0:
                continue
            score = 0
            if alvo_marca and alvo_marca in texto:
                score += 25
            if alvo_modelo and alvo_modelo in texto:
                score += 60
            if tokens_alvo:
                acertos = sum(1 for t in tokens_alvo if t in texto)
                score += min(45, acertos * 18)
            if score > melhor[0]:
                melhor = (score, row)
        if melhor[0] >= 25:
            return melhor[1], melhor[0]
        return None, 0

    @staticmethod
    def _normalizar_local(valor: Any) -> str:
        try:
            from services.text_utils import normalizar_texto
            return normalizar_texto(valor)
        except Exception:
            return str(valor or "").strip().lower()

    def _calcular_combustao_zero_km_por_proxy(self, veiculo: VeiculoSelecionado) -> dict[str, Any]:
        """Calcula depreciação de zero km usando ano usado equivalente.

        O código 32000 da FIPE acompanha preço de tabela do carro novo. Isso não
        representa depreciação do uso. Para não gerar taxa zero ou curva falsa,
        tentamos anos usados do mesmo modelo, de preferência mesmo combustível,
        até encontrar uma série histórica válida.
        """
        cliente_fipe = FipeHistoricoService()
        candidatos = cliente_fipe.listar_codigos_ano_usados_mesmo_modelo(veiculo)
        auditorias_falhas: list[dict[str, Any]] = []

        for cand in candidatos[:8]:
            veiculo_proxy = VeiculoSelecionado(
                tipo=veiculo.tipo,
                codigo_marca=veiculo.codigo_marca,
                codigo_modelo=veiculo.codigo_modelo,
                codigo_ano=str(cand.get("codigo_ano", "")),
                codigo_fipe=veiculo.codigo_fipe,
                marca=veiculo.marca,
                modelo=veiculo.modelo,
                ano_modelo=str(cand.get("ano_modelo", "")),
                combustivel=veiculo.combustivel,
                valor_atual=veiculo.valor_atual,
                horizonte_anos=veiculo.horizonte_anos,
            )
            try:
                historico_proxy = self.historico.buscar_historico_combustao_veiculo(veiculo_proxy)
                resultado = calcular_curva_combustao_por_historico(
                    veiculo=veiculo_proxy,
                    historico=historico_proxy,
                ).to_dict()
                auditoria = dict(resultado.get("auditoria_historico") or {})
                auditoria.update({
                    "zero_km_original": True,
                    "proxy_aplicado": True,
                    "codigo_ano_proxy": veiculo_proxy.codigo_ano,
                    "ano_modelo_proxy": veiculo_proxy.ano_modelo,
                    "nome_proxy": cand.get("nome", ""),
                    "valor_zero_km_atual": veiculo.valor_atual,
                    "observacao_proxy": "Taxa calculada com ano usado equivalente e aplicada ao valor FIPE zero km selecionado.",
                })
                resultado.update({
                    "status": "calculado_proxy_zero_km",
                    "mensagem": "Curva de combustão calculada por proxy de ano usado equivalente para seleção zero km.",
                    "veiculo_titulo": f"{veiculo.marca} {veiculo.modelo} Zero km",
                    "valor_atual": round(float(veiculo.valor_atual), 2),
                    "origem_curva": "proxy zero km por ano usado equivalente",
                    "tipo_match": "proxy_zero_km_ano_usado",
                    "auditoria_historico": auditoria,
                    "codigo_ano_proxy": veiculo_proxy.codigo_ano,
                    "ano_modelo_proxy": veiculo_proxy.ano_modelo,
                    "nome_proxy": cand.get("nome", ""),
                })
                # Recalcula o valor futuro explicitamente sobre o preço zero km selecionado.
                taxa_mensal = float(resultado.get("taxa_mensal_percentual", 0.0)) / 100.0
                horizonte_meses = int(veiculo.horizonte_anos) * 12
                fator = (1.0 - taxa_mensal) ** horizonte_meses
                valor_futuro = max(0.0, float(veiculo.valor_atual) * fator)
                dep_pct = ((float(veiculo.valor_atual) - valor_futuro) / float(veiculo.valor_atual) * 100.0) if veiculo.valor_atual > 0 else 0.0
                resultado["valor_futuro"] = round(valor_futuro, 2)
                resultado["depreciacao_percentual"] = round(max(0.0, dep_pct), 2)
                return resultado
            except CalculoCombustaoInvalido as exc:
                auditorias_falhas.append({
                    "codigo_ano_proxy": veiculo_proxy.codigo_ano,
                    "ano_modelo_proxy": veiculo_proxy.ano_modelo,
                    "mensagem": str(exc),
                    "auditoria": exc.auditoria,
                })
                continue

        raise CalculoCombustaoInvalido(
            "Não foi possível calcular proxy para zero km. Nenhum ano usado equivalente apresentou histórico suficiente e depreciação válida.",
            {
                "zero_km_detectado": True,
                "proxy_aplicado": False,
                "candidatos_testados": auditorias_falhas,
                "quantidade_candidatos": len(candidatos),
            },
        )

    @staticmethod
    def _veiculo_zero_km(veiculo: VeiculoSelecionado) -> bool:
        return str(veiculo.ano_modelo).strip() == "32000" or str(veiculo.codigo_ano).strip().startswith("32000")

    def _detectar_tipo_por_veiculo(self, veiculo: VeiculoSelecionado) -> str:
        return "eletrico" if detectar_eletrico(veiculo.combustivel, veiculo.modelo) else "combustao"

    def _resolver_tipo(self, veiculo: VeiculoSelecionado, tipo_detectado: str | None = None) -> str:
        tipo = str(veiculo.tipo or "auto").strip().lower()
        if tipo in {"eletrico", "ev", "ve"}:
            return "eletrico"
        if tipo in {"combustao", "icev", "atual"}:
            return "combustao"
        return tipo_detectado or self._detectar_tipo_por_veiculo(veiculo)

    def _montar_aviso_tipo(self, tipo_informado: str, tipo_detectado: str, tipo_utilizado: str) -> str:
        tipo = str(tipo_informado or "auto").strip().lower()
        if tipo == "auto":
            return ""
        if tipo_detectado != tipo_utilizado:
            if tipo_detectado == "eletrico" and tipo_utilizado == "combustao":
                return "Atenção: o veículo parece elétrico/híbrido, mas a busca foi forçada como combustão."
            if tipo_detectado == "combustao" and tipo_utilizado == "eletrico":
                return "Atenção: o veículo parece combustão, mas a busca foi forçada como elétrico/híbrido."
        return ""

    def _filtrar_curva_para_detalhes(self, curva: dict[str, Any]) -> dict[str, Any]:
        campos = [
            "titulo",
            "marca",
            "modelo",
            "ano_modelo",
            "codigo_fipe",
            "family_id",
            "family_nome",
            "modelo_base_curva",
            "ano_base_curva",
            "fonte_ajuste",
            "categoria",
            "pontos_historicos",
            "observacoes_total",
            "janela_historica_meses",
            "depreciacao_media_anual_percentual",
            "depreciacao_media_anual_principal_percentual",
            "taxa_mensal_hibrida_percentual",
            "confianca_ev",
            "status_final",
            "data_salvamento",
            "fonte_historico",
            "proxy_aplicado",
            "metodo_taxa",
            "modo_calculo",
            "idade_entrada_meses",
            "idade_projecao_meses",
            "primeiro_valor_historico",
            "ultimo_valor_historico",
            "variacao_total_percentual",
            "observacao_metodologica",
            "tipo_match",
        ]
        return {campo: curva.get(campo, "") for campo in campos if campo in curva and str(curva.get(campo, "")).strip()}
