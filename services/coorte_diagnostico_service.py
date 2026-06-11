from __future__ import annotations

from datetime import datetime
from typing import Any

from core.modelos import VeiculoSelecionado
from services.fipe_service import FipeService, FipeApiError
from services.fipe_historico_painel_adapter import FipeHistoricoPainelAdapter
from services.text_utils import detectar_eletrico, normalizar_texto, parse_float_seguro


class CoorteDiagnosticoService:
    """Diagnóstico seguro do motor novo de depreciação por família/coorte.

    Este serviço NÃO salva curva, NÃO apaga curva e NÃO substitui o motor atual.
    Ele serve para mostrar, em teste de mesa, qual seria o caminho metodológico
    antes de conectar o cálculo definitivo.
    """

    def __init__(self) -> None:
        self.fipe = FipeService()
        self.historico_adapter = FipeHistoricoPainelAdapter(self.fipe)

    def diagnosticar(self, payload: dict[str, Any]) -> dict[str, Any]:
        veiculo = VeiculoSelecionado.from_payload(payload)
        ano_atual = datetime.now().year
        ano_base_preferencial = ano_atual - 7
        tipo = self._resolver_tipo(veiculo)
        zero_km = self._veiculo_zero_km(veiculo)
        ano_selecionado = self._ano_selecionado(veiculo)

        try:
            anos_raw = self.fipe.listar_anos(veiculo.codigo_marca, veiculo.codigo_modelo)
        except FipeApiError as exc:
            return {
                "ok": False,
                "status": "erro_fipe",
                "mensagem": "Não foi possível listar os anos do modelo agora. O diagnóstico não alterou nem salvou nada.",
                "erro": exc.to_dict(),
                "veiculo": veiculo.to_dict(),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "erro_controlado",
                "mensagem": "Não foi possível listar os anos do modelo agora. O diagnóstico não alterou nem salvou nada.",
                "erro": str(exc),
                "veiculo": veiculo.to_dict(),
            }

        anos_validos = self._normalizar_anos_validos(anos_raw)
        tem_zero_km = any(a["zero_km"] for a in anos_validos)
        anos_usados = [a for a in anos_validos if not a["zero_km"]]
        anos_usados_ordenados = sorted(anos_usados, key=lambda x: x["ano"])

        if not anos_usados_ordenados:
            return {
                "ok": False,
                "status": "sem_anos_validos",
                "mensagem": "O modelo não possui anos usados elegíveis para montar curva de coorte.",
                "veiculo": veiculo.to_dict(),
                "tipo_utilizado": tipo,
                "zero_km_detectado": zero_km,
                "tem_zero_km_na_fipe": tem_zero_km,
                "anos_disponiveis": anos_validos,
            }

        coorte_base = self._escolher_coorte_base(anos_usados_ordenados, ano_base_preferencial, ano_atual)
        primeiro_ano = anos_usados_ordenados[0]
        ultimo_ano = anos_usados_ordenados[-1]

        if zero_km:
            modo = "zero_km"
            idade_entrada = 0
            explicacao_modo = (
                "Veículo zero km: a curva deve começar na idade 0. "
                "A coorte usada para aprender a curva deve ser um ano usado representativo, preferencialmente ano atual - 7."
            )
        else:
            modo = "usado"
            if not ano_selecionado:
                ano_selecionado = self._ano_codigo_int(veiculo.codigo_ano) or ultimo_ano["ano"]
            idade_entrada = max(0, ano_atual - int(ano_selecionado))
            explicacao_modo = (
                "Veículo usado: a curva não deve reiniciar no ano 0. "
                "O valor FIPE atual entra na curva na idade aproximada do veículo e a projeção continua dali para frente."
            )

        historico_plano = self._montar_plano_historico(
            ano_atual=ano_atual,
            coorte_base=coorte_base,
            primeiro_ano=primeiro_ano,
            ultimo_ano=ultimo_ano,
            anos_usados=anos_usados_ordenados,
            zero_km=zero_km,
            ano_selecionado=ano_selecionado,
        )

        erro_price_history = None

        # 1) Caminho prioritário da documentação atual da API FIPE:
        #    /{vehicleType}/{fipeCode}/years/{yearId}/history
        # Esse endpoint evita reconstruir manualmente marca/modelo/ano em cada referência
        # e é o equivalente mais direto ao histórico que o painel antigo precisava montar.
        amostragem_referencias = self._coletar_historico_por_codigo_fipe(
            veiculo=veiculo,
            coorte_base=coorte_base,
            historico_plano=historico_plano,
        )
        pontos_price_history = int(amostragem_referencias.get("pontos_validos", 0) or 0)

        # 2) Se o endpoint /history retornou só uma janela curta, tenta ampliar
        # usando âncoras de referência. A API pode devolver poucos meses por chamada;
        # então consultamos o mesmo código FIPE em poucas referências espaçadas e
        # unimos os priceHistory retornados. Isso aproveita a documentação atual sem
        # reconstruir marca/modelo em todas as referências.
        if pontos_price_history < 8:
            ampliado = self._coletar_historico_codigo_fipe_por_ancoras(
                veiculo=veiculo,
                coorte_base=coorte_base,
                historico_plano=historico_plano,
                historico_inicial=amostragem_referencias,
            )
            if int(ampliado.get("pontos_validos", 0) or 0) > pontos_price_history:
                amostragem_referencias = ampliado
                pontos_price_history = int(ampliado.get("pontos_validos", 0) or 0)
            else:
                amostragem_referencias["ampliacao_por_ancoras"] = ampliado

        # 3) Fallback principal: reproduz o fluxo V19.15/V19.17 do painel local.
        # O painel local achava a primeira aparição do modelo/coorte, buscava o
        # zero km 32000 e reutilizava os códigos encontrados para coletar o histórico.
        if pontos_price_history < 8:
            try:
                v19 = self.historico_adapter.montar_historico_v19_15_adaptado(
                    codigo_marca_atual=veiculo.codigo_marca,
                    nome_marca=veiculo.marca,
                    nome_modelo=veiculo.modelo,
                    ano_base=int(coorte_base.get("ano") or ano_selecionado or ano_atual),
                    combustivel=veiculo.combustivel,
                    ano_atual=ano_atual,
                    max_pontos=24,
                )
            except Exception as exc:
                v19 = {"ok": False, "estrategia_historico": "painel_local_v19_15_adaptado", "pontos_validos": 0, "erro": f"{type(exc).__name__}: {str(exc)[:220]}"}
            if int(v19.get("pontos_validos", 0) or 0) > pontos_price_history:
                amostragem_referencias = v19
                pontos_price_history = int(v19.get("pontos_validos", 0) or 0)
            else:
                amostragem_referencias["fallback_v19_15_painel_local"] = v19

        # 4) Fallback controlado: se ainda houver poucos pontos, tenta a reconstrução
        # por referência/ano. Continua limitado para não estourar timeout/requisições.
        if pontos_price_history < 8:
            fallback = self._coletar_amostragem_referencias(
                veiculo=veiculo,
                coorte_base=coorte_base,
                historico_plano=historico_plano,
            )
            if int(fallback.get("pontos_validos", 0) or 0) > pontos_price_history:
                amostragem_referencias = fallback
                pontos_price_history = int(fallback.get("pontos_validos", 0) or 0)
            else:
                # preserva o erro/diagnóstico do fallback como contexto, sem perder a estratégia principal
                amostragem_referencias["fallback_referencia"] = fallback

        pontos_amostrados = int(amostragem_referencias.get("pontos_validos", 0) or 0)
        erro_price_history = amostragem_referencias.get("erro") or amostragem_referencias.get("ultimo_erro")

        pontos_para_qualidade = max(pontos_price_history, pontos_amostrados)
        qualidade = self._classificar_qualidade(pontos_para_qualidade, historico_plano["janela_teorica_meses"])

        texto = self._montar_texto(
            veiculo=veiculo,
            tipo=tipo,
            modo=modo,
            zero_km=zero_km,
            tem_zero_km=tem_zero_km,
            ano_atual=ano_atual,
            ano_base_preferencial=ano_base_preferencial,
            coorte_base=coorte_base,
            primeiro_ano=primeiro_ano,
            ultimo_ano=ultimo_ano,
            idade_entrada=idade_entrada,
            historico_plano=historico_plano,
            pontos_price_history=pontos_price_history,
            amostragem_referencias=amostragem_referencias,
            qualidade=qualidade,
            erro_price_history=erro_price_history,
        )

        return {
            "ok": True,
            "status": "diagnostico_coorte",
            "mensagem": "Diagnóstico técnico montado. Nenhuma curva foi salva.",
            "veiculo": veiculo.to_dict(),
            "tipo_utilizado": tipo,
            "modo_calculo_proposto": modo,
            "zero_km_detectado": zero_km,
            "tem_zero_km_na_fipe": tem_zero_km,
            "ano_atual": ano_atual,
            "ano_base_preferencial": ano_base_preferencial,
            "ano_selecionado": ano_selecionado,
            "idade_entrada_curva_anos": idade_entrada,
            "coorte_base": coorte_base,
            "primeiro_ano_disponivel": primeiro_ano,
            "ultimo_ano_disponivel": ultimo_ano,
            "plano_historico": historico_plano,
            "price_history_coorte_base_pontos": pontos_price_history,
            "amostragem_referencias": amostragem_referencias,
            "price_history_erro": erro_price_history,
            "qualidade_estimativa": qualidade,
            "explicacao_modo": explicacao_modo,
            "relatorio_textual": texto,
            "nao_salvou": True,
        }

    def _resolver_tipo(self, veiculo: VeiculoSelecionado) -> str:
        if veiculo.tipo in {"combustao", "eletrico"}:
            return veiculo.tipo
        return "eletrico" if detectar_eletrico(veiculo.modelo, veiculo.combustivel) else "combustao"

    @staticmethod
    def _veiculo_zero_km(veiculo: VeiculoSelecionado) -> bool:
        return str(veiculo.codigo_ano or "").split("-", 1)[0] == "32000" or "zero" in str(veiculo.ano_modelo or "").lower()

    @staticmethod
    def _ano_codigo_int(codigo_ano: str) -> int | None:
        txt = str(codigo_ano or "").split("-", 1)[0]
        return int(txt) if txt.isdigit() and txt != "32000" else None

    def _ano_selecionado(self, veiculo: VeiculoSelecionado) -> int | None:
        for valor in (veiculo.ano_modelo, veiculo.codigo_ano):
            ano = self._ano_codigo_int(str(valor))
            if ano:
                return ano
            txt = str(valor or "")
            for parte in txt.replace("/", " ").replace("-", " ").split():
                if parte.isdigit() and len(parte) == 4 and parte != "32000":
                    return int(parte)
        return None

    @staticmethod
    def _normalizar_anos_validos(anos_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saida = []
        for item in anos_raw or []:
            codigo = str(item.get("codigo") or item.get("code") or "").strip()
            nome = str(item.get("nome") or item.get("name") or "").strip()
            ano_txt = codigo.split("-", 1)[0]
            if ano_txt == "32000":
                saida.append({"codigo": codigo, "nome": nome or "Zero km", "ano": 32000, "zero_km": True})
                continue
            if ano_txt.isdigit():
                ano = int(ano_txt)
                if ano >= 2012:
                    saida.append({"codigo": codigo, "nome": nome, "ano": ano, "zero_km": False})
        return saida

    @staticmethod
    def _escolher_coorte_base(anos_usados: list[dict[str, Any]], ano_preferencial: int, ano_atual: int) -> dict[str, Any]:
        # Preferência: ano atual - 7. Se não existir, usa o mais próximo.
        # Se o modelo é recente, usa o primeiro ano disponível.
        # Se o modelo saiu de linha, usa o último ano disponível que dê maior janela até hoje.
        if not anos_usados:
            return {}
        exato = [a for a in anos_usados if a["ano"] == ano_preferencial]
        if exato:
            base = dict(exato[0])
            base["criterio"] = "ano atual - 7 encontrado exatamente"
            return base
        candidatos_ate_preferencial = [a for a in anos_usados if a["ano"] <= ano_preferencial]
        if candidatos_ate_preferencial:
            base = dict(max(candidatos_ate_preferencial, key=lambda x: x["ano"]))
            base["criterio"] = "ano disponível mais próximo abaixo do ano atual - 7"
            return base
        base = dict(min(anos_usados, key=lambda x: x["ano"]))
        base["criterio"] = "modelo recente; usado primeiro ano disponível"
        return base

    @staticmethod
    def _montar_plano_historico(*, ano_atual: int, coorte_base: dict[str, Any], primeiro_ano: dict[str, Any], ultimo_ano: dict[str, Any], anos_usados: list[dict[str, Any]], zero_km: bool, ano_selecionado: int | None) -> dict[str, Any]:
        ano_base = int(coorte_base.get("ano") or ano_atual)
        janela_teorica_anos = max(0, ano_atual - ano_base)
        return {
            "ano_base_coorte": ano_base,
            "janela_teorica_anos": janela_teorica_anos,
            "janela_teorica_meses": janela_teorica_anos * 12,
            "anos_disponiveis_2012_mais": [a["ano"] for a in anos_usados],
            "modelo_recente": primeiro_ano.get("ano") and int(primeiro_ano["ano"]) > ano_atual - 7,
            "modelo_descontinuado": ultimo_ano.get("ano") and int(ultimo_ano["ano"]) < ano_atual,
            "ano_selecionado": ano_selecionado,
            "fluxo": "zero_km_aplica_desde_idade_0" if zero_km else "usado_aplica_a_partir_da_idade_atual",
            "pandemia": "peso reduzido por padrão; futuro campo permitirá manter, reduzir ou excluir",
            "ipca": "corrigir série histórica antes de ajustar curva",
        }


    def _coletar_historico_por_codigo_fipe(self, *, veiculo: VeiculoSelecionado, coorte_base: dict[str, Any], historico_plano: dict[str, Any]) -> dict[str, Any]:
        """Coleta prioritária usando o endpoint documentado por código FIPE.

        A documentação enviada pelo Alisson oferece:
        GET /{vehicleType}/{fipeCode}/years/{yearId}/history

        Esse caminho precisa vir ANTES da reconstrução manual por referência, porque:
        - consome muito menos requisições;
        - evita timeout;
        - retorna a série histórica pronta quando disponível;
        - preserva a lógica do painel antigo sem depender do endpoint web antigo bloqueado no Render.
        """
        codigo_fipe = str(veiculo.codigo_fipe or "").strip()
        codigo_ano_coorte = str(coorte_base.get("codigo") or "").strip()
        tentativas: list[dict[str, Any]] = []

        if not codigo_fipe:
            try:
                detalhe_atual = self.fipe.consultar_preco(veiculo.codigo_marca, veiculo.codigo_modelo, veiculo.codigo_ano)
                codigo_fipe = str(detalhe_atual.get("CodigoFipe") or detalhe_atual.get("codeFipe") or "").strip()
            except Exception as exc:
                tentativas.append({"etapa": "obter_codigo_fipe_atual", "erro": f"{type(exc).__name__}: {str(exc)[:160]}"})

        if not codigo_fipe:
            return {
                "ok": False,
                "criterio_passo": "histórico por código FIPE indisponível: veículo sem código FIPE",
                "estrategia_historico": "codigo_fipe_history_indisponivel",
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "erro": "codigo_fipe_ausente",
                "tentativas": tentativas,
            }

        codigos_ano_para_tentar: list[tuple[str, str]] = []
        if codigo_ano_coorte:
            codigos_ano_para_tentar.append((codigo_ano_coorte, "coorte_base"))
        if veiculo.codigo_ano and str(veiculo.codigo_ano) != codigo_ano_coorte:
            codigos_ano_para_tentar.append((str(veiculo.codigo_ano), "ano_selecionado"))

        # Consulta leve: se a API souber listar anos pelo código FIPE, ela ajuda a alinhar
        # a coorte escolhida com o ano disponível para aquele código FIPE.
        try:
            anos_por_codigo = self.fipe.listar_anos_por_codigo_fipe(codigo_fipe)
            ano_coorte_int = self._ano_codigo_int(codigo_ano_coorte)
            if ano_coorte_int:
                for ano_item in anos_por_codigo or []:
                    codigo = str(ano_item.get("codigo") or ano_item.get("code") or "")
                    if self._ano_codigo_int(codigo) == ano_coorte_int and codigo not in [x[0] for x in codigos_ano_para_tentar]:
                        codigos_ano_para_tentar.insert(0, (codigo, "ano_por_codigo_fipe_alinhado"))
                        break
        except Exception as exc:
            tentativas.append({"etapa": "listar_anos_por_codigo_fipe", "erro": f"{type(exc).__name__}: {str(exc)[:160]}"})

        melhor: dict[str, Any] | None = None
        for codigo_ano, origem in codigos_ano_para_tentar:
            try:
                detalhe_hist = self.fipe.consultar_historico_por_codigo_fipe(codigo_fipe, codigo_ano)
                coletado = self._normalizar_historico_codigo_fipe(
                    detalhe_hist,
                    codigo_fipe=codigo_fipe,
                    codigo_ano=codigo_ano,
                    origem_codigo_ano=origem,
                    historico_plano=historico_plano,
                )
                tentativas.append({"codigo_ano": codigo_ano, "origem": origem, "pontos": coletado.get("pontos_validos", 0)})
                if melhor is None or int(coletado.get("pontos_validos", 0) or 0) > int(melhor.get("pontos_validos", 0) or 0):
                    melhor = coletado
                if int(coletado.get("pontos_validos", 0) or 0) >= 8:
                    break
            except FipeApiError as exc:
                tentativas.append({"codigo_ano": codigo_ano, "origem": origem, "erro": exc.message, "status_code": exc.status_code})
                if exc.status_code == 429:
                    return {
                        "ok": False,
                        "criterio_passo": "histórico por código FIPE interrompido por limite FIPE",
                        "estrategia_historico": "codigo_fipe_history",
                        "pontos_planejados": len(codigos_ano_para_tentar),
                        "pontos_validos": 0,
                        "limite_interrompeu": True,
                        "erro": exc.message,
                        "tentativas": tentativas,
                    }
            except Exception as exc:
                tentativas.append({"codigo_ano": codigo_ano, "origem": origem, "erro": f"{type(exc).__name__}: {str(exc)[:160]}"})

        if melhor is None:
            return {
                "ok": False,
                "criterio_passo": "histórico por código FIPE não retornou série",
                "estrategia_historico": "codigo_fipe_history",
                "pontos_planejados": len(codigos_ano_para_tentar),
                "pontos_validos": 0,
                "erro": "sem_historico_por_codigo_fipe",
                "tentativas": tentativas,
            }

        melhor["tentativas"] = tentativas
        return melhor

    def _normalizar_historico_codigo_fipe(self, detalhe: dict[str, Any], *, codigo_fipe: str, codigo_ano: str, origem_codigo_ano: str, historico_plano: dict[str, Any]) -> dict[str, Any]:
        historico = detalhe.get("HistoricoPreco") or detalhe.get("priceHistory") or []
        pontos: list[dict[str, Any]] = []
        for item in historico or []:
            if not isinstance(item, dict):
                continue
            mes = str(item.get("month") or item.get("mes") or item.get("MesReferencia") or "").strip()
            ref = str(item.get("reference") or item.get("codigo") or item.get("Codigo") or "").strip()
            preco_txt = item.get("price") or item.get("preco") or item.get("Valor") or ""
            valor = parse_float_seguro(preco_txt)
            if not valor or valor <= 0:
                continue
            data_dt = self.historico_adapter.parse_mes_referencia(mes)
            pontos.append({
                "ok": True,
                "reference": ref,
                "mes": mes,
                "data_referencia": data_dt.strftime("%Y-%m") if data_dt else None,
                "valor": float(valor),
                "valor_formatado": preco_txt if isinstance(preco_txt, str) and preco_txt else f"R$ {valor:,.2f}",
                "codigo_fipe": codigo_fipe,
                "codigo_ano": codigo_ano,
                "estrategia": "codigo_fipe_year_history",
            })

        pontos.sort(key=lambda x: x.get("data_referencia") or x.get("reference") or "")
        variacao = None
        if len(pontos) >= 2 and pontos[0].get("valor"):
            variacao = ((float(pontos[-1]["valor"]) - float(pontos[0]["valor"])) / float(pontos[0]["valor"])) * 100
            variacao = round(variacao, 2)

        return {
            "ok": True,
            "criterio_passo": "histórico direto por código FIPE, conforme documentação atual da API",
            "passo_meses": None,
            "janela_teorica_meses": int(historico_plano.get("janela_teorica_meses") or 0),
            "pontos_planejados": len(pontos),
            "pontos_validos": len(pontos),
            "pontos_price_history_codigo_fipe": len(pontos),
            "limite_interrompeu": False,
            "estrategia_historico": "codigo_fipe_history: /cars/{fipeCode}/years/{yearId}/history",
            "codigo_fipe_utilizado": codigo_fipe,
            "codigo_ano_utilizado": codigo_ano,
            "origem_codigo_ano": origem_codigo_ano,
            "modelo_referencia": detalhe.get("Modelo") or detalhe.get("model") or "",
            "ano_referencia": detalhe.get("AnoModelo") or detalhe.get("modelYear") or "",
            "primeiro_ponto": pontos[0] if pontos else None,
            "ultimo_ponto": pontos[-1] if pontos else None,
            "variacao_percentual_observada": variacao,
            "amostra": pontos[:12],
            "pontos": pontos,
            "erro": None if pontos else "priceHistory_vazio_no_endpoint_por_codigo_fipe",
        }


    def _coletar_historico_codigo_fipe_por_ancoras(self, *, veiculo: VeiculoSelecionado, coorte_base: dict[str, Any], historico_plano: dict[str, Any], historico_inicial: dict[str, Any] | None = None) -> dict[str, Any]:
        """Amplia histórico por código FIPE usando referências âncora.

        A documentação atual oferece /{vehicleType}/{fipeCode}/years/{yearId}/history.
        Na prática, algumas respostas vêm com uma janela curta. Para aproveitar melhor
        esse endpoint sem explodir requisições, testamos poucas referências espaçadas:

        referência âncora -> anos por código FIPE naquela referência -> history naquela referência

        Depois unimos os pontos únicos retornados. Se a API ignorar o parâmetro
        reference, os pontos duplicam e o diagnóstico informa isso sem salvar curva.
        """
        codigo_fipe = str(veiculo.codigo_fipe or "").strip()
        tentativas: list[dict[str, Any]] = []
        if not codigo_fipe:
            try:
                detalhe_atual = self.fipe.consultar_preco(veiculo.codigo_marca, veiculo.codigo_modelo, veiculo.codigo_ano)
                codigo_fipe = str(detalhe_atual.get("CodigoFipe") or detalhe_atual.get("codeFipe") or "").strip()
            except Exception as exc:
                tentativas.append({"etapa": "obter_codigo_fipe_atual", "erro": f"{type(exc).__name__}: {str(exc)[:160]}"})
        if not codigo_fipe:
            return {
                "ok": False,
                "criterio_passo": "ampliação por âncoras não executada: sem código FIPE",
                "estrategia_historico": "codigo_fipe_history_ancoras_indisponivel",
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "erro": "codigo_fipe_ausente",
                "tentativas": tentativas,
            }

        ano_base = int(coorte_base.get("ano") or 0)
        if not ano_base:
            return {
                "ok": False,
                "criterio_passo": "ampliação por âncoras não executada: coorte sem ano",
                "estrategia_historico": "codigo_fipe_history_ancoras",
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "erro": "coorte_sem_ano",
                "tentativas": tentativas,
            }

        try:
            referencias = self.historico_adapter.referencias_ordenadas()
        except FipeApiError as exc:
            return {
                "ok": False,
                "criterio_passo": "ampliação por âncoras interrompida ao listar referências",
                "estrategia_historico": "codigo_fipe_history_ancoras",
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "limite_interrompeu": exc.status_code == 429,
                "erro": exc.message,
                "tentativas": tentativas,
            }
        except Exception as exc:
            return {
                "ok": False,
                "criterio_passo": "ampliação por âncoras interrompida ao listar referências",
                "estrategia_historico": "codigo_fipe_history_ancoras",
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "erro": f"{type(exc).__name__}: {str(exc)[:160]}",
                "tentativas": tentativas,
            }

        janela_meses = int(historico_plano.get("janela_teorica_meses") or 0)
        ano_atual = datetime.now().year
        if janela_meses <= 36:
            max_ancoras = 5
            criterio = "histórico por código FIPE com âncoras: modelo recente, âncoras mais próximas"
        elif janela_meses <= 84:
            max_ancoras = 5
            criterio = "histórico por código FIPE com âncoras: modelo intermediário"
        else:
            max_ancoras = 4
            criterio = "histórico por código FIPE com âncoras: modelo antigo/descontinuado"

        planejadas = self.historico_adapter.selecionar_referencias_amostradas(
            referencias,
            ano_inicio=max(1990, ano_base),
            ano_atual=ano_atual,
            max_pontos=max_ancoras,
        )

        pontos_por_chave: dict[str, dict[str, Any]] = {}
        def adicionar_pontos(origem: dict[str, Any] | None, fonte: str) -> None:
            if not origem:
                return
            lista = origem.get("pontos") or origem.get("amostra") or []
            for p in lista or []:
                if not isinstance(p, dict) or not p.get("valor"):
                    continue
                chave = str(p.get("reference") or p.get("data_referencia") or p.get("mes") or len(pontos_por_chave))
                item = dict(p)
                item.setdefault("fonte_bloco", fonte)
                pontos_por_chave[chave] = item

        adicionar_pontos(historico_inicial, "history_inicial")

        refs_sem_ano = 0
        refs_sem_historico = 0
        erros_404 = 0
        erros_outros = 0
        limite_interrompeu = False
        ultimo_erro = None

        for ref in planejadas:
            ref_code = str(ref.get("code") or "")
            if not ref_code:
                continue
            try:
                anos_ref = self.fipe.listar_anos_por_codigo_fipe(codigo_fipe, reference=ref_code)
                ano_ref = self._encontrar_ano_na_referencia(anos_ref, ano_base, veiculo.combustivel)
                if not ano_ref:
                    refs_sem_ano += 1
                    tentativas.append({"reference": ref_code, "mes": ref.get("month"), "status": "ano_coorte_nao_encontrado"})
                    continue
                codigo_ano_ref = str(ano_ref.get("codigo") or ano_ref.get("code") or "")
                detalhe_hist = self.fipe.consultar_historico_por_codigo_fipe(codigo_fipe, codigo_ano_ref, reference=ref_code)
                bloco = self._normalizar_historico_codigo_fipe(
                    detalhe_hist,
                    codigo_fipe=codigo_fipe,
                    codigo_ano=codigo_ano_ref,
                    origem_codigo_ano=f"ancora_reference_{ref_code}",
                    historico_plano=historico_plano,
                )
                tentativas.append({
                    "reference": ref_code,
                    "mes": ref.get("month"),
                    "codigo_ano": codigo_ano_ref,
                    "pontos": bloco.get("pontos_validos", 0),
                })
                if int(bloco.get("pontos_validos", 0) or 0) <= 0:
                    refs_sem_historico += 1
                    ultimo_erro = bloco.get("erro") or "history_vazio_na_ancora"
                adicionar_pontos(bloco, f"history_ancora_{ref_code}")
                if len(pontos_por_chave) >= 12:
                    # suficiente para diagnosticar sem gastar muitas requisições neste clique
                    break
            except FipeApiError as exc:
                ultimo_erro = exc.message
                if exc.status_code == 404:
                    erros_404 += 1
                    tentativas.append({"reference": ref_code, "mes": ref.get("month"), "erro": exc.message, "status_code": 404})
                    continue
                if exc.status_code == 429:
                    limite_interrompeu = True
                    tentativas.append({"reference": ref_code, "mes": ref.get("month"), "erro": exc.message, "status_code": 429})
                    break
                erros_outros += 1
                tentativas.append({"reference": ref_code, "mes": ref.get("month"), "erro": exc.message, "status_code": exc.status_code})
            except Exception as exc:
                ultimo_erro = f"{type(exc).__name__}: {str(exc)[:180]}"
                erros_outros += 1
                tentativas.append({"reference": ref_code, "mes": ref.get("month"), "erro": ultimo_erro})

        pontos = list(pontos_por_chave.values())
        pontos.sort(key=lambda x: x.get("data_referencia") or x.get("reference") or x.get("mes") or "")
        variacao = None
        if len(pontos) >= 2 and pontos[0].get("valor"):
            variacao = ((float(pontos[-1]["valor"]) - float(pontos[0]["valor"])) / float(pontos[0]["valor"])) * 100
            variacao = round(variacao, 2)

        return {
            "ok": True,
            "criterio_passo": criterio,
            "passo_meses": None,
            "janela_teorica_meses": janela_meses,
            "referencias_disponiveis": len(referencias),
            "pontos_planejados": len(planejadas),
            "pontos_validos": len(pontos),
            "pontos_price_history_codigo_fipe": len(pontos),
            "refs_sem_ano": refs_sem_ano,
            "refs_sem_historico": refs_sem_historico,
            "erros_404_ignorados": erros_404,
            "erros_outros": erros_outros,
            "limite_interrompeu": limite_interrompeu,
            "estrategia_historico": "codigo_fipe_history_ancoras: /cars/{fipeCode}/years/{yearId}/history?reference=...",
            "codigo_fipe_utilizado": codigo_fipe,
            "codigo_ano_utilizado": str(coorte_base.get("codigo") or ""),
            "origem_codigo_ano": "coorte_por_ancoras",
            "primeiro_ponto": pontos[0] if pontos else None,
            "ultimo_ponto": pontos[-1] if pontos else None,
            "variacao_percentual_observada": variacao,
            "amostra": pontos[:12],
            "pontos": pontos,
            "tentativas": tentativas,
            "ultimo_erro": ultimo_erro,
            "erro": ultimo_erro if not pontos and ultimo_erro else None,
        }


    def _coletar_amostragem_referencias(self, *, veiculo: VeiculoSelecionado, coorte_base: dict[str, Any], historico_plano: dict[str, Any]) -> dict[str, Any]:
        """Coleta diagnóstica inspirada no painel antigo.

        Não usa código atual no passado como fonte única. Para cada referência
        mensal, reconstrói o caminho dentro daquele mês:
        referência -> marca -> ano -> modelos daquele ano -> preço.
        """
        ano_base = int(coorte_base.get("ano") or 0)
        if not ano_base:
            return {"ok": False, "erro": "coorte_base_sem_ano", "pontos_planejados": 0, "pontos_validos": 0}

        janela_meses = int(historico_plano.get("janela_teorica_meses") or 0)
        ano_atual = datetime.now().year
        if janela_meses <= 36:
            criterio = "modelo recente: amostra mensal/curta, com reconstrução por referência"
            max_pontos = 6
        elif janela_meses <= 84:
            criterio = "modelo intermediário: amostra adaptativa, com reconstrução por referência"
            max_pontos = 6
        else:
            criterio = "modelo antigo/descontinuado: amostra espaçada, com reconstrução por referência"
            max_pontos = 5

        try:
            referencias = self.historico_adapter.referencias_ordenadas()
        except FipeApiError as exc:
            return {
                "ok": False,
                "erro": exc.message,
                "erro_tipo": exc.tipo,
                "criterio_passo": criterio,
                "pontos_planejados": 0,
                "pontos_validos": 0,
                "limite_interrompeu": exc.status_code == 429,
            }
        except Exception as exc:
            return {"ok": False, "erro": str(exc)[:240], "criterio_passo": criterio, "pontos_planejados": 0, "pontos_validos": 0}

        planejadas = self.historico_adapter.selecionar_referencias_amostradas(
            referencias,
            ano_inicio=max(1990, ano_base),
            ano_atual=ano_atual,
            max_pontos=max_pontos,
        )

        pontos: list[dict[str, Any]] = []
        refs_sem_marca = 0
        refs_sem_modelo = 0
        refs_sem_ano = 0
        refs_sem_preco = 0
        erros_404 = 0
        erros_outros = 0
        limite_interrompeu = False
        ultimo_erro = None
        amostras_falhas: list[dict[str, Any]] = []

        for ref in planejadas:
            ref_code = str(ref.get("code") or "")
            try:
                ponto = self.historico_adapter.consultar_ponto_por_referencia_painel(
                    reference=ref_code,
                    mes_referencia=str(ref.get("month") or ""),
                    codigo_marca_atual=veiculo.codigo_marca,
                    nome_marca=veiculo.marca,
                    nome_modelo=veiculo.modelo,
                    ano_base=ano_base,
                    combustivel=veiculo.combustivel,
                )
                d = ponto.to_dict()
                if ponto.ok and ponto.valor:
                    pontos.append(d)
                else:
                    motivo = ponto.motivo or "sem_ponto"
                    ultimo_erro = motivo
                    if motivo == "marca_nao_encontrada_na_referencia":
                        refs_sem_marca += 1
                    elif motivo == "modelo_nao_encontrado_na_referencia":
                        refs_sem_modelo += 1
                    elif motivo == "ano_nao_encontrado_na_referencia":
                        refs_sem_ano += 1
                    elif motivo == "preco_invalido_na_referencia":
                        refs_sem_preco += 1
                    else:
                        erros_outros += 1
                    if len(amostras_falhas) < 4:
                        amostras_falhas.append(d)
            except FipeApiError as exc:
                ultimo_erro = exc.message
                if exc.status_code == 404:
                    erros_404 += 1
                    continue
                if exc.status_code == 429:
                    limite_interrompeu = True
                    break
                erros_outros += 1
            except Exception as exc:
                ultimo_erro = f"{type(exc).__name__}: {str(exc)[:180]}"
                erros_outros += 1

        # Ordena por data quando disponível; mantém ordem de coleta se não houver data.
        pontos.sort(key=lambda x: x.get("data_referencia") or x.get("reference") or "")
        variacao = None
        if len(pontos) >= 2 and pontos[0].get("valor"):
            variacao = ((float(pontos[-1]["valor"]) - float(pontos[0]["valor"])) / float(pontos[0]["valor"])) * 100
            variacao = round(variacao, 2)

        return {
            "ok": True,
            "criterio_passo": criterio,
            "passo_meses": None,
            "janela_teorica_meses": janela_meses,
            "referencias_disponiveis": len(referencias),
            "pontos_planejados_original": len(planejadas),
            "pontos_planejados": len(planejadas),
            "amostragem_parcial": True,
            "limite_diagnostico_por_clique": max_pontos,
            "pontos_validos": len(pontos),
            "refs_sem_marca": refs_sem_marca,
            "refs_sem_modelo": refs_sem_modelo,
            "refs_sem_ano": refs_sem_ano,
            "refs_sem_preco": refs_sem_preco,
            "erros_404_ignorados": erros_404,
            "erros_outros": erros_outros,
            "limite_interrompeu": limite_interrompeu,
            "estrategia_historico": "painel_antigo_adaptado: referencia_marca_ano_modelos_preco",
            "primeiro_ponto": pontos[0] if pontos else None,
            "ultimo_ponto": pontos[-1] if pontos else None,
            "variacao_percentual_observada": variacao,
            "amostra": pontos[:8],
            "amostras_falhas": amostras_falhas,
            "ultimo_erro": ultimo_erro,
            "erro": ultimo_erro if not pontos and ultimo_erro else None,
        }


    @staticmethod
    def _tokens_modelo(nome: str) -> set[str]:
        texto = normalizar_texto(nome)
        ignorar = {
            "flex", "aut", "mec", "auto", "automatico", "manual", "gasolina", "alcool",
            "diesel", "eletrico", "hibrido", "16v", "8v", "12v", "4p", "5p", "2p",
            "cv", "tb", "turbo", "vvt", "mpi", "tsi", "tdi", "gdi", "at", "mt",
        }
        tokens = set()
        for t in texto.replace(".", " ").replace("/", " ").replace("-", " ").split():
            if len(t) < 2 or t in ignorar:
                continue
            tokens.add(t)
        return tokens

    def _encontrar_modelo_na_referencia(self, modelos: list[dict[str, Any]], nome_alvo: str) -> dict[str, Any] | None:
        if not modelos:
            return None
        alvo_norm = normalizar_texto(nome_alvo)
        alvo_tokens = self._tokens_modelo(nome_alvo)
        melhor = None
        melhor_score = 0.0
        for m in modelos:
            nome = str(m.get("nome") or m.get("name") or "")
            nome_norm = normalizar_texto(nome)
            if not nome_norm:
                continue
            if nome_norm == alvo_norm:
                return m
            tokens = self._tokens_modelo(nome)
            inter = len(alvo_tokens & tokens)
            union = max(1, len(alvo_tokens | tokens))
            score = inter / union
            # Bônus quando o nome principal está contido. Isso ajuda HB20/Etios/Corolla.
            if alvo_tokens and any(t in nome_norm.split() for t in alvo_tokens):
                score += 0.10
            if score > melhor_score:
                melhor_score = score
                melhor = m
        return melhor if melhor_score >= 0.28 else None

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
        if "eletrico" in alvo or "hibrido" in alvo:
            return ("eletrico" in nome) or ("hibrido" in nome)
        return True

    def _encontrar_ano_na_referencia(self, anos: list[dict[str, Any]], ano_base: int, combustivel_alvo: str) -> dict[str, Any] | None:
        candidatos = []
        for a in anos or []:
            codigo = str(a.get("codigo") or a.get("code") or "")
            nome = str(a.get("nome") or a.get("name") or "")
            ano_txt = codigo.split("-", 1)[0]
            ano = int(ano_txt) if ano_txt.isdigit() and ano_txt != "32000" else None
            if ano == int(ano_base):
                candidatos.append(a)
        if not candidatos:
            return None
        compativeis = [a for a in candidatos if self._combustivel_compativel(str(a.get("nome") or a.get("name") or ""), combustivel_alvo)]
        return (compativeis or candidatos)[0]

    def _consultar_ponto_referencia_reconstruido(self, *, veiculo: VeiculoSelecionado, coorte_base: dict[str, Any], reference: str, mes_referencia: str) -> dict[str, Any]:
        ano_base = int(coorte_base.get("ano") or 0)
        if not ano_base:
            return {"ok": False, "motivo": "coorte_sem_ano_base"}

        modelos_data = self.fipe.listar_modelos_referencia(veiculo.codigo_marca, reference)
        modelos = modelos_data.get("modelos", []) if isinstance(modelos_data, dict) else []
        modelo_ref = self._encontrar_modelo_na_referencia(modelos, veiculo.modelo)
        if not modelo_ref:
            return {"ok": False, "motivo": "modelo_nao_encontrado_na_referencia", "reference": reference, "mes": mes_referencia}

        codigo_modelo_ref = str(modelo_ref.get("codigo") or modelo_ref.get("code") or "")
        anos = self.fipe.listar_anos_referencia(veiculo.codigo_marca, codigo_modelo_ref, reference)
        ano_ref = self._encontrar_ano_na_referencia(anos, ano_base, veiculo.combustivel)
        if not ano_ref:
            return {
                "ok": False,
                "motivo": "ano_nao_encontrado_na_referencia",
                "reference": reference,
                "mes": mes_referencia,
                "modelo_referencia": modelo_ref.get("nome") or modelo_ref.get("name"),
            }

        codigo_ano_ref = str(ano_ref.get("codigo") or ano_ref.get("code") or "")
        detalhe = self.fipe.consultar_preco_referencia(veiculo.codigo_marca, codigo_modelo_ref, codigo_ano_ref, reference)
        valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
        valor = parse_float_seguro(valor_txt)
        if not valor or valor <= 0:
            return {"ok": False, "motivo": "preco_invalido_na_referencia", "reference": reference, "mes": mes_referencia}

        return {
            "ok": True,
            "reference": reference,
            "mes": mes_referencia or detalhe.get("MesReferencia") or "",
            "valor": float(valor),
            "valor_formatado": valor_txt if isinstance(valor_txt, str) and valor_txt else f"R$ {valor:,.2f}",
            "codigo_modelo_referencia": codigo_modelo_ref,
            "modelo_referencia": modelo_ref.get("nome") or modelo_ref.get("name") or "",
            "codigo_ano_referencia": codigo_ano_ref,
            "ano_referencia": ano_ref.get("nome") or ano_ref.get("name") or "",
            "modelo_reconstruido": codigo_modelo_ref != str(veiculo.codigo_modelo),
            "ano_reconstruido": codigo_ano_ref != str(coorte_base.get("codigo") or ""),
        }

    @staticmethod
    def _classificar_qualidade(pontos: int, janela_meses: int) -> str:
        if pontos >= 24 and janela_meses >= 36:
            return "ALTA"
        if points := pontos:
            if points >= 8:
                return "MÉDIA"
            if points >= 2:
                return "EXPLORATÓRIA"
        return "NÃO CALCULAR AINDA"

    @staticmethod
    def _montar_texto(**ctx) -> str:
        v = ctx["veiculo"]
        linhas = []
        linhas.append("DIAGNÓSTICO TÉCNICO DO MOTOR POR FAMÍLIA/COORTE")
        linhas.append("")
        linhas.append(f"Veículo selecionado: {v.marca} {v.modelo} {v.ano_modelo} {v.combustivel}.".strip())
        linhas.append(f"Tipo utilizado: {ctx['tipo']}.")
        linhas.append(f"Zero km detectado: {'Sim' if ctx['zero_km'] else 'Não'}.")
        linhas.append(f"Existe opção zero km na FIPE para este modelo: {'Sim' if ctx['tem_zero_km'] else 'Não'}.")
        linhas.append("")
        linhas.append(f"Ano atual: {ctx['ano_atual']}.")
        linhas.append(f"Ano-base preferencial: {ctx['ano_base_preferencial']}.")
        cb = ctx["coorte_base"]
        linhas.append(f"Coorte base escolhida: {cb.get('ano')} - {cb.get('nome')}.")
        linhas.append(f"Critério da coorte: {cb.get('criterio')}.")
        linhas.append(f"Primeiro ano disponível: {ctx['primeiro_ano'].get('ano')}.")
        linhas.append(f"Último ano disponível: {ctx['ultimo_ano'].get('ano')}.")
        linhas.append(f"Idade de entrada na curva: {ctx['idade_entrada']} ano(s).")
        linhas.append("")
        plano = ctx["historico_plano"]
        linhas.append(f"Janela teórica da coorte: {plano.get('janela_teorica_anos')} ano(s), aproximadamente {plano.get('janela_teorica_meses')} meses.")
        linhas.append(f"Modelo recente: {'Sim' if plano.get('modelo_recente') else 'Não'}.")
        linhas.append(f"Modelo descontinuado: {'Sim' if plano.get('modelo_descontinuado') else 'Não'}.")
        linhas.append(f"Pontos priceHistory retornados na coorte base: {ctx['pontos_price_history']}.")
        am = ctx.get("amostragem_referencias") or {}
        linhas.append(f"Amostragem adaptativa por referências: {am.get('criterio_passo', '-') }.")
        linhas.append(f"Referências planejadas: {am.get('pontos_planejados', 0)}; pontos válidos encontrados: {am.get('pontos_validos', 0)}.")
        linhas.append(f"Estratégia de busca histórica: {am.get('estrategia_historico', 'consulta direta por referência')}.")
        if am.get('refs_sem_marca') or am.get('refs_sem_modelo') or am.get('refs_sem_ano') or am.get('refs_sem_preco'):
            linhas.append(
                f"Falhas por referência: sem marca {am.get('refs_sem_marca', 0)}, "
                f"sem modelo {am.get('refs_sem_modelo', 0)}, "
                f"sem ano {am.get('refs_sem_ano', 0)}, "
                f"sem preço {am.get('refs_sem_preco', 0)}."
            )
        if am.get("primeiro_ponto") and am.get("ultimo_ponto"):
            p0 = am.get("primeiro_ponto") or {}
            p1 = am.get("ultimo_ponto") or {}
            linhas.append(f"Primeiro ponto válido: {p0.get('mes')} - {p0.get('valor_formatado')}.")
            linhas.append(f"Último ponto válido: {p1.get('mes')} - {p1.get('valor_formatado')}.")
            linhas.append(f"Variação observada na janela: {am.get('variacao_percentual_observada')}%.")
        if am.get("limite_interrompeu"):
            linhas.append("Coleta interrompida por limite FIPE. O progresso deve ser retomado depois da janela de 24h.")
        if am.get("erro"):
            linhas.append(f"Observação da amostragem: {am.get('erro')}.")
        if ctx.get("erro_price_history"):
            linhas.append(f"Falha ao consultar priceHistory direto da coorte base: {ctx['erro_price_history']}.")
        linhas.append(f"Qualidade estimada: {ctx['qualidade']}.")
        linhas.append("")
        linhas.append("Como o cálculo definitivo deve agir:")
        if ctx["zero_km"]:
            linhas.append("- Aplicar a curva da família desde a idade 0 sobre o valor FIPE zero km atual.")
        else:
            linhas.append("- Não reiniciar a curva. Aplicar a função a partir da idade atual do veículo selecionado.")
        linhas.append("- Corrigir a série histórica por IPCA.")
        linhas.append("- Tratar pandemia com peso reduzido por padrão, com opção futura de excluir/manter.")
        linhas.append("- Salvar uma curva de família/coorte, não apenas uma curva isolada por ano.")
        linhas.append("- Não salvar curva definitiva se a qualidade for 'NÃO CALCULAR AINDA'.")
        return "\n".join(linhas)
