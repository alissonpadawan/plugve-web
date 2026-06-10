from __future__ import annotations

from datetime import datetime
from typing import Any

from core.modelos import VeiculoSelecionado
from services.fipe_service import FipeService, FipeApiError
from services.text_utils import detectar_eletrico, parse_float_seguro


class CoorteDiagnosticoService:
    """Diagnóstico seguro do motor novo de depreciação por família/coorte.

    Este serviço NÃO salva curva, NÃO apaga curva e NÃO substitui o motor atual.
    Ele serve para mostrar, em teste de mesa, qual seria o caminho metodológico
    antes de conectar o cálculo definitivo.
    """

    def __init__(self) -> None:
        self.fipe = FipeService()

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

        detalhe_base = None
        pontos_price_history = 0
        erro_price_history = None
        amostragem_referencias = self._coletar_amostragem_referencias(
            veiculo=veiculo,
            coorte_base=coorte_base,
            historico_plano=historico_plano,
        )
        pontos_amostrados = int(amostragem_referencias.get("pontos_validos", 0) or 0)

        # Consulta leve adicional: algumas respostas da API já trazem priceHistory direto.
        # Se vier, ele é usado apenas como indicação; a coleta por referências é mais controlada.
        try:
            detalhe_base = self.fipe.consultar_preco(veiculo.codigo_marca, veiculo.codigo_modelo, coorte_base["codigo"])
            pontos_price_history = len(detalhe_base.get("HistoricoPreco") or detalhe_base.get("priceHistory") or [])
        except Exception as exc:
            erro_price_history = str(exc)[:240]

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
