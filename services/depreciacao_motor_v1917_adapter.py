from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app

from core.modelos import VeiculoSelecionado
from repositories.ipca_repository import IpcaRepository
from services.fipe_historico_painel_adapter import FipeHistoricoPainelAdapter, PontoHistoricoPainel
from services.fipe_service import FipeApiError, FipeService
from services.text_utils import formatar_brl, normalizar_texto, parse_float_seguro, parse_int_seguro


@dataclass
class PontoV1917:
    data_referencia: str
    idade_meses: int
    valor_fipe: float
    preco_zero_km_corrigido: float
    ratio: float
    ratio_ajustado_monotonico: float
    indice_tempo: int
    flag_pandemia: bool
    peso: float
    categoria: str
    veiculo: str


@dataclass
class ResultadoCurvaV1917:
    veiculo: str
    categoria: str
    fonte_ajuste: str
    ano_modelo: int
    periodo_inicial: str
    periodo_final: str
    numero_observacoes_total: int
    numero_observacoes_utilizadas: int
    idade_atual_meses: int
    horizonte_anos: float
    horizonte_meses: int
    valor_fipe_atual: float
    preco_zero_km_base: float
    data_preco_zero_km_base: str
    preco_zero_km_corrigido_atual: float
    ratio_atual: float
    ratio_atual_ajustado: float
    taxa_mensal_curva_percentual: float
    taxa_mensal_cauda_percentual: float
    taxa_mensal_hibrida_percentual: float
    depreciacao_media_anual_principal_percentual: float
    ratio_estimado_futuro_principal: float
    ratio_estimado_futuro_otimista: float
    ratio_estimado_futuro_pessimista: float
    valor_estimado_futuro_principal: float
    valor_estimado_futuro_otimista: float
    valor_estimado_futuro_pessimista: float
    depreciacao_acumulada_principal_percentual: float
    modo_pandemia: str
    texto_diagnostico: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MESES_PT = {
    "janeiro": 1,
    "jan": 1,
    "fevereiro": 2,
    "fev": 2,
    "marco": 3,
    "março": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "maio": 5,
    "mai": 5,
    "junho": 6,
    "jun": 6,
    "julho": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "setembro": 9,
    "set": 9,
    "outubro": 10,
    "out": 10,
    "novembro": 11,
    "nov": 11,
    "dezembro": 12,
    "dez": 12,
}


# ---------------------------------------------------------------------------
# Núcleo matemático portado do painel local V19.17/V18.
# Mantido neste arquivo para o web não depender da pasta do painel local.
# ---------------------------------------------------------------------------

def parse_ano_mes(data_str: str) -> tuple[int, int]:
    partes = str(data_str or "").split("-")
    if len(partes) != 2:
        raise ValueError(f"Data inválida: {data_str}. Formato esperado: YYYY-MM")
    ano = int(partes[0])
    mes = int(partes[1])
    if mes < 1 or mes > 12:
        raise ValueError(f"Mês inválido em {data_str}.")
    return ano, mes


def formatar_ano_mes(ano: int, mes: int) -> str:
    return f"{ano:04d}-{mes:02d}"


def adicionar_meses(data_str: str, meses: int) -> str:
    ano, mes = parse_ano_mes(data_str)
    total = (ano * 12 + (mes - 1)) + int(meses)
    novo_ano = total // 12
    novo_mes = (total % 12) + 1
    return formatar_ano_mes(novo_ano, novo_mes)


def diferenca_meses(data_inicial: str, data_final: str) -> int:
    ano_i, mes_i = parse_ano_mes(data_inicial)
    ano_f, mes_f = parse_ano_mes(data_final)
    return (ano_f - ano_i) * 12 + (mes_f - mes_i)


def eh_periodo_pandemia(data_ref: str) -> bool:
    ano, _mes = parse_ano_mes(data_ref)
    return 2020 <= ano <= 2022


def resolver_indice_inflacao(indices_inflacao: dict[str, float], data_ref: str) -> tuple[str, float]:
    if not indices_inflacao:
        return data_ref, 100.0
    if data_ref in indices_inflacao:
        return data_ref, float(indices_inflacao[data_ref])
    chaves = sorted(k for k, v in indices_inflacao.items() if v is not None)
    anteriores = [k for k in chaves if k <= data_ref]
    if anteriores:
        chave = anteriores[-1]
        return chave, float(indices_inflacao[chave])
    chave = chaves[0]
    return chave, float(indices_inflacao[chave])


def isotonic_decreasing_weighted(y_vals: list[float], pesos: list[float]) -> list[float]:
    blocks: list[dict[str, float | int]] = []
    for idx, (y, w) in enumerate(zip(y_vals, pesos)):
        if w <= 0:
            raise ValueError("Peso inválido no ajuste monotônico.")
        blocks.append({"start": idx, "end": idx, "weight": float(w), "mean": float(y)})
        while len(blocks) >= 2 and float(blocks[-2]["mean"]) < float(blocks[-1]["mean"]):
            b2 = blocks.pop()
            b1 = blocks.pop()
            peso_total = float(b1["weight"]) + float(b2["weight"])
            media_total = ((float(b1["mean"]) * float(b1["weight"])) + (float(b2["mean"]) * float(b2["weight"]))) / peso_total
            blocks.append({"start": int(b1["start"]), "end": int(b2["end"]), "weight": peso_total, "mean": media_total})
    ajustado = [0.0] * len(y_vals)
    for bloco in blocks:
        for i in range(int(bloco["start"]), int(bloco["end"]) + 1):
            ajustado[i] = float(bloco["mean"])
    return ajustado


def aplicar_modo_pandemia(pontos: list[PontoV1917], modo_pandemia: str) -> list[PontoV1917]:
    modo = normalizar_texto(modo_pandemia or "Excluir")
    if modo == "manter":
        return pontos
    if modo == "excluir":
        filtrados = [p for p in pontos if not p.flag_pandemia]
        if len(filtrados) < 2:
            raise ValueError("Após excluir pandemia, restaram menos de 2 observações.")
        return filtrados
    if modo == "peso reduzido":
        ajustados: list[PontoV1917] = []
        for p in pontos:
            d = asdict(p)
            d["peso"] = 0.30 if p.flag_pandemia else 1.0
            ajustados.append(PontoV1917(**d))
        return ajustados
    raise ValueError("Modo pandemia inválido. Use: Excluir, Peso reduzido ou Manter.")


def construir_pontos_veiculo(dados_veiculo: dict[str, Any], indices_inflacao: dict[str, float]) -> list[PontoV1917]:
    veiculo = str(dados_veiculo["veiculo"])
    categoria = str(dados_veiculo["categoria"])
    ano_modelo = int(dados_veiculo["ano_modelo"])
    preco_zero_km_base = float(dados_veiculo["preco_zero_km_base"])
    data_preco_zero_km_base = str(dados_veiculo["data_preco_zero_km_base"]).strip()

    _data_base_ipca, indice_base = resolver_indice_inflacao(indices_inflacao, data_preco_zero_km_base)
    data_origem_idade = f"{ano_modelo}-01"
    historico_ordenado = sorted(dados_veiculo["historico"], key=lambda item: str(item["data_referencia"]))

    pontos: list[PontoV1917] = []
    for idx, item in enumerate(historico_ordenado):
        data_ref = str(item["data_referencia"]).strip()
        valor_fipe = float(item["valor_fipe"])
        _data_obs_ipca, indice_obs = resolver_indice_inflacao(indices_inflacao, data_ref)
        idade_meses = diferenca_meses(data_origem_idade, data_ref)
        preco_zero_km_corrigido = preco_zero_km_base * (indice_obs / max(indice_base, 1e-9))
        ratio = valor_fipe / max(preco_zero_km_corrigido, 1e-9)
        pontos.append(
            PontoV1917(
                data_referencia=data_ref,
                idade_meses=idade_meses,
                valor_fipe=valor_fipe,
                preco_zero_km_corrigido=preco_zero_km_corrigido,
                ratio=ratio,
                ratio_ajustado_monotonico=ratio,
                indice_tempo=idx,
                flag_pandemia=eh_periodo_pandemia(data_ref),
                peso=1.0,
                categoria=categoria,
                veiculo=veiculo,
            )
        )
    return pontos


def preparar_base_ajuste(pontos: list[PontoV1917], modo_pandemia: str) -> list[PontoV1917]:
    pontos_filtrados = aplicar_modo_pandemia(pontos, modo_pandemia)
    pontos_filtrados.sort(key=lambda p: p.idade_meses)
    y_vals = [float(p.ratio) for p in pontos_filtrados]
    pesos = [float(p.peso) for p in pontos_filtrados]
    y_iso = isotonic_decreasing_weighted(y_vals, pesos)
    saida: list[PontoV1917] = []
    for p, y_adj in zip(pontos_filtrados, y_iso):
        d = asdict(p)
        d["ratio_ajustado_monotonico"] = float(y_adj)
        saida.append(PontoV1917(**d))
    return saida


def calcular_taxa_mensal_equivalente_da_curva(idades: list[int], ratios_ajustados: list[float]) -> float:
    if len(idades) < 2:
        return 0.0
    delta = int(idades[-1]) - int(idades[0])
    if delta <= 0 or ratios_ajustados[0] <= 0 or ratios_ajustados[-1] <= 0:
        return 0.0
    fator_total = min(float(ratios_ajustados[-1]) / float(ratios_ajustados[0]), 1.0)
    return max(0.0, 1.0 - (fator_total ** (1.0 / delta)))


def calcular_taxa_mensal_cauda(idades: list[int], ratios_ajustados: list[float]) -> float:
    if len(idades) < 2:
        return 0.0
    inicio = max(0, len(idades) - 4)
    logs_trechos: list[float] = []
    for i in range(inicio, len(idades) - 1):
        r0, r1 = float(ratios_ajustados[i]), float(ratios_ajustados[i + 1])
        d0, d1 = int(idades[i]), int(idades[i + 1])
        delta = d1 - d0
        if delta <= 0 or r0 <= 0 or r1 <= 0:
            continue
        logs_trechos.append(math.log(r1 / r0) / delta)
    if not logs_trechos:
        return 0.0
    fator = min(math.exp(sum(logs_trechos) / len(logs_trechos)), 1.0)
    return max(0.0, 1.0 - fator)


def projetar_ratio(ratio_base: float, taxa_mensal: float, horizonte_meses: int) -> float:
    return float(ratio_base) * ((1.0 - max(0.0, float(taxa_mensal))) ** max(0, int(horizonte_meses)))


def regressao_linear_ponderada(x_vals: list[float], y_vals: list[float], pesos: list[float]) -> tuple[float, float]:
    soma_p = sum(float(p) for p in pesos)
    if len(x_vals) < 2 or soma_p <= 0:
        raise ValueError("Dados insuficientes para regressão ponderada.")
    media_x = sum(w * x for x, w in zip(x_vals, pesos)) / soma_p
    media_y = sum(w * y for y, w in zip(y_vals, pesos)) / soma_p
    soma_num = 0.0
    soma_den = 0.0
    for x, y, w in zip(x_vals, y_vals, pesos):
        soma_num += w * (x - media_x) * (y - media_y)
        soma_den += w * ((x - media_x) ** 2)
    if abs(soma_den) < 1e-12:
        raise ValueError("Variância ponderada de X nula.")
    beta_1 = soma_num / soma_den
    beta_0 = media_y - beta_1 * media_x
    return beta_0, beta_1


def calcular_curva_v1917(
    *,
    dados_veiculo: dict[str, Any],
    horizonte_anos: float,
    indices_inflacao: dict[str, float],
    modo_pandemia: str,
    minimo_pontos_veiculo: int = 8,
) -> ResultadoCurvaV1917:
    pontos_total = construir_pontos_veiculo(dados_veiculo, indices_inflacao)
    if len(pontos_total) < minimo_pontos_veiculo:
        raise ValueError(f"Histórico insuficiente para cálculo V19.17: {len(pontos_total)} ponto(s).")

    pontos_utilizados = preparar_base_ajuste(pontos_total, modo_pandemia)
    if len(pontos_utilizados) < 2:
        raise ValueError("Histórico insuficiente após tratamento de pandemia.")

    ultimo_total = max(pontos_total, key=lambda p: p.data_referencia)
    ultimo_util = max(pontos_utilizados, key=lambda p: p.idade_meses)
    horizonte_meses = max(0, int(round(float(horizonte_anos) * 12.0)))
    idades_util = [int(p.idade_meses) for p in pontos_utilizados]
    ratios_adj = [float(p.ratio_ajustado_monotonico) for p in pontos_utilizados]

    taxa_mensal_curva = calcular_taxa_mensal_equivalente_da_curva(idades_util, ratios_adj)
    taxa_mensal_cauda = calcular_taxa_mensal_cauda(idades_util, ratios_adj)
    taxa_mensal_hibrida = (0.30 * taxa_mensal_curva) + (0.70 * taxa_mensal_cauda)

    ratio_base = float(ultimo_util.ratio_ajustado_monotonico)
    ratio_futuro = projetar_ratio(ratio_base, taxa_mensal_hibrida, horizonte_meses)
    ratio_futuro_ot = projetar_ratio(ratio_base, taxa_mensal_hibrida * 0.80, horizonte_meses)
    ratio_futuro_pe = projetar_ratio(ratio_base, taxa_mensal_hibrida * 1.20, horizonte_meses)

    preco_zero_km_corrigido_atual = float(ultimo_total.preco_zero_km_corrigido)
    valor_futuro = ratio_futuro * preco_zero_km_corrigido_atual
    valor_futuro_ot = ratio_futuro_ot * preco_zero_km_corrigido_atual
    valor_futuro_pe = ratio_futuro_pe * preco_zero_km_corrigido_atual
    dep_acumulada = ((ultimo_total.valor_fipe - valor_futuro) / ultimo_total.valor_fipe) * 100.0 if ultimo_total.valor_fipe > 0 else 0.0
    taxa_anual_equivalente = 1.0 - ((1.0 - taxa_mensal_hibrida) ** 12)

    # Mantém a regressão alternativa do motor antigo apenas como proteção de diagnóstico.
    try:
        x_vals = [float(p.idade_meses) for p in pontos_utilizados]
        y_vals = [math.log(max(float(p.ratio), 1e-9)) for p in pontos_utilizados]
        pesos = [float(p.peso) for p in pontos_utilizados]
        beta_0, beta_1 = regressao_linear_ponderada(x_vals, y_vals, pesos)
        if beta_1 > 0:
            beta_1 = 0.0
            soma_p = sum(pesos)
            beta_0 = sum(w * y for y, w in zip(y_vals, pesos)) / max(soma_p, 1e-9)
    except Exception:
        beta_0, beta_1 = 0.0, 0.0

    texto_diagnostico = (
        f"Fonte do ajuste: Veículo específico ({dados_veiculo['veiculo']})\n"
        f"Modo pandemia: {modo_pandemia}\n"
        f"Observações totais: {len(pontos_total)}\n"
        f"Observações usadas no ajuste: {len(pontos_utilizados)}\n"
        f"Ratio atual observado: {ultimo_total.ratio:.4f}\n"
        f"Ratio base da projeção: {ratio_base:.4f}\n"
        f"Taxa mensal curva: {taxa_mensal_curva * 100:.4f}%\n"
        f"Taxa mensal cauda: {taxa_mensal_cauda * 100:.4f}%\n"
        f"Taxa mensal híbrida: {taxa_mensal_hibrida * 100:.4f}%\n"
        f"Taxa anual equivalente sem offset: {taxa_anual_equivalente * 100:.2f}%\n"
        f"Regressão log-linear alternativa: beta0={beta_0:.6f}; beta1={beta_1:.6f}"
    )

    return ResultadoCurvaV1917(
        veiculo=str(dados_veiculo["veiculo"]),
        categoria=str(dados_veiculo["categoria"]),
        fonte_ajuste=f"Veículo específico ({dados_veiculo['veiculo']})",
        ano_modelo=int(dados_veiculo["ano_modelo"]),
        periodo_inicial=min(p.data_referencia for p in pontos_total),
        periodo_final=max(p.data_referencia for p in pontos_total),
        numero_observacoes_total=len(pontos_total),
        numero_observacoes_utilizadas=len(pontos_utilizados),
        idade_atual_meses=int(ultimo_total.idade_meses),
        horizonte_anos=float(horizonte_anos),
        horizonte_meses=horizonte_meses,
        valor_fipe_atual=float(ultimo_total.valor_fipe),
        preco_zero_km_base=float(dados_veiculo["preco_zero_km_base"]),
        data_preco_zero_km_base=str(dados_veiculo["data_preco_zero_km_base"]),
        preco_zero_km_corrigido_atual=preco_zero_km_corrigido_atual,
        ratio_atual=float(ultimo_total.ratio),
        ratio_atual_ajustado=ratio_base,
        taxa_mensal_curva_percentual=taxa_mensal_curva * 100.0,
        taxa_mensal_cauda_percentual=taxa_mensal_cauda * 100.0,
        taxa_mensal_hibrida_percentual=taxa_mensal_hibrida * 100.0,
        depreciacao_media_anual_principal_percentual=taxa_anual_equivalente * 100.0,
        ratio_estimado_futuro_principal=ratio_futuro,
        ratio_estimado_futuro_otimista=ratio_futuro_ot,
        ratio_estimado_futuro_pessimista=ratio_futuro_pe,
        valor_estimado_futuro_principal=valor_futuro,
        valor_estimado_futuro_otimista=valor_futuro_ot,
        valor_estimado_futuro_pessimista=valor_futuro_pe,
        depreciacao_acumulada_principal_percentual=dep_acumulada,
        modo_pandemia=modo_pandemia,
        texto_diagnostico=texto_diagnostico,
    )


def fator_taper_idade(idade_meses: int) -> float:
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


def calcular_fator_cumulativo_por_idade(taxa_mensal_percentual: float, idade_entrada_meses: int, horizonte_meses: int) -> float:
    taxa_base = max(0.0, float(taxa_mensal_percentual) / 100.0)
    fator = 1.0
    for passo in range(max(0, int(horizonte_meses))):
        idade_mes_atual = max(0, int(idade_entrada_meses)) + passo
        taxa_mes = max(0.0, taxa_base * fator_taper_idade(idade_mes_atual))
        fator *= (1.0 - taxa_mes)
    return fator


def calcular_taxa_anual_efetiva_do_fator(fator_cumulativo: float, horizonte_meses: int) -> float:
    try:
        meses = max(0, int(horizonte_meses))
        fator = float(fator_cumulativo)
        if meses <= 0 or fator <= 0:
            return 0.0
        anos = meses / 12.0
        if anos <= 0:
            return 0.0
        return max(0.0, (1.0 - (fator ** (1.0 / anos))) * 100.0)
    except Exception:
        return 0.0


class DepreciacaoMotorV1917Adapter:
    """Adapter paralelo para portar o motor local V19.17 ao PlugVE Web.

    Responsabilidades desta primeira entrega V24:
    - reconstruir histórico por referência mensal, como o painel local;
    - buscar primeira aparição e zero km base;
    - coletar histórico em lotes pequenos, persistindo progresso;
    - calcular diagnóstico com IPCA, pandemia e offset de idade;
    - nunca salvar curva definitiva nesta rota.
    """

    VERSAO = "V24_adapter_v1917_parallel"

    def __init__(self, fipe: FipeService | None = None) -> None:
        self.fipe = fipe or FipeService()
        self.painel_adapter = FipeHistoricoPainelAdapter(self.fipe)
        self.ipca_repo = IpcaRepository()

    # ------------------------------------------------------------------
    # API pública usada pelas rotas Flask.
    # ------------------------------------------------------------------
    def diagnosticar(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload or {})
        job: dict[str, Any] | None = None
        try:
            job_id = str(payload.get("job_id") or payload.get("diagnostico_job_id") or "").strip()
            reiniciar = bool(payload.get("reiniciar_v1917"))
            if job_id and not reiniciar:
                job = self._carregar_job(job_id)
                if not job:
                    return {
                        "ok": False,
                        "status": "job_nao_encontrado",
                        "mensagem": "Diagnóstico V19.17 não encontrado no disco persistente. Inicie uma nova coleta.",
                        "job_id": job_id,
                    }
            else:
                job = self._criar_job(payload)
            job = self._executar_lote(job, payload)
            self._salvar_job(job)
            return self._montar_resposta(job)
        except FipeApiError as exc:
            if job is None:
                return {
                    "ok": False,
                    "status": "erro_api_fipe",
                    "mensagem": exc.message,
                    "erro": exc.to_dict(),
                    "pode_salvar": False,
                }
            job["fase"] = "erro_api_fipe"
            job["erro"] = exc.to_dict()
            job.setdefault("eventos", []).append({"tipo": "erro_api_fipe", "mensagem": exc.message, "status_code": exc.status_code})
            self._salvar_job(job)
            return self._montar_resposta(job)
        except Exception as exc:
            if job is None:
                return {
                    "ok": False,
                    "status": "erro_controlado",
                    "mensagem": f"Erro ao iniciar diagnóstico V19.17: {type(exc).__name__}: {exc}",
                    "erro": {"tipo": type(exc).__name__, "mensagem": str(exc)},
                    "pode_salvar": False,
                }
            job["fase"] = "erro_controlado"
            job["erro"] = {"tipo": type(exc).__name__, "mensagem": str(exc)}
            job.setdefault("eventos", []).append({"tipo": "erro_controlado", "mensagem": f"{type(exc).__name__}: {exc}"})
            self._salvar_job(job)
            return self._montar_resposta(job)

    def continuar(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.diagnosticar(payload)

    def status(self, job_id: str) -> dict[str, Any]:
        job = self._carregar_job(str(job_id or "").strip())
        if not job:
            return {"ok": False, "status": "job_nao_encontrado", "mensagem": "Diagnóstico V19.17 não encontrado.", "job_id": job_id}
        return self._montar_resposta(job, executar_calculo=False)

    # ------------------------------------------------------------------
    # Persistência simples no disco persistente do Render.
    # ------------------------------------------------------------------
    def _base_dir(self) -> Path:
        base = Path(current_app.config.get("PERSISTENT_DIR") or "data/_runtime") / "depreciacao_v1917"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _job_path(self, job_id: str) -> Path:
        safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in {"-", "_"})[:80]
        return self._base_dir() / f"{safe}.json"

    def _carregar_job(self, job_id: str) -> dict[str, Any] | None:
        if not job_id:
            return None
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _salvar_job(self, job: dict[str, Any]) -> None:
        job["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._job_path(str(job["job_id"])).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Criação do plano de diagnóstico.
    # ------------------------------------------------------------------
    def _criar_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        veiculo = VeiculoSelecionado.from_payload(payload)
        if not veiculo.codigo_marca or not veiculo.codigo_modelo:
            raise ValueError("Selecione marca e modelo antes de iniciar o diagnóstico V19.17.")
        referencias = self._referencias_serializadas()
        falha_fipe_web_v1917 = str(getattr(self, "_ultima_falha_referencias_web", "") or "")
        referencias_fipe_web_v1917 = len([r for r in referencias if str(r.get("fonte") or "") == "fipe_web_v1917"])
        referencias_fipe_v2 = len([r for r in referencias if str(r.get("fonte") or "") == "fipe_v2"])
        data_base_operacao = self._resolver_data_base_operacao(payload, referencias)
        anos_disponiveis = self._listar_anos_disponiveis(veiculo)
        ano_base_preferencial = self._resolver_ano_preferencial(payload, data_base_operacao)
        coorte = self._escolher_coorte_base(anos_disponiveis, ano_base_preferencial, veiculo.codigo_ano, veiculo.combustivel)
        if not coorte:
            raise ValueError("Não foi possível escolher uma coorte/base usada para esse modelo FIPE.")

        inicio_busca = f"{max(int(coorte['ano']) - 1, 1990):04d}-01"
        refs_busca = [r for r in referencias if r.get("data_ref") and r["data_ref"] >= inicio_busca and r["data_ref"] <= data_base_operacao]
        if not refs_busca:
            raise ValueError("Não há referências FIPE suficientes para iniciar a busca da primeira aparição.")

        job_id = f"v1917_{uuid.uuid4().hex[:16]}"
        selecionado_zero_km = self._codigo_ano_eh_zero(veiculo.codigo_ano) or str(veiculo.ano_modelo).strip() == "32000"
        job = {
            "job_id": job_id,
            "motor": self.VERSAO,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "fase": "buscar_primeira_aparicao",
            "payload_original": payload,
            "veiculo": veiculo.to_dict(),
            "selecionado_zero_km": selecionado_zero_km,
            "modo_pandemia": str(payload.get("modo_pandemia") or "Excluir").strip() or "Excluir",
            "data_base_operacao": data_base_operacao,
            "ano_base_preferencial": int(ano_base_preferencial),
            "coorte_base": coorte,
            "anos_disponiveis": anos_disponiveis,
            "referencias": referencias,
            "fonte_historico": str((referencias[0] or {}).get("fonte") or "fipe_v2") if referencias else "sem_referencias",
            "falha_fipe_web_v1917": falha_fipe_web_v1917,
            "referencias_fipe_web_v1917": referencias_fipe_web_v1917,
            "referencias_fipe_v2": referencias_fipe_v2,
            "total_referencias_disponiveis": len(referencias),
            "total_referencias_busca": len(refs_busca),
            "referencias_busca": refs_busca,
            "indice_busca_primeira": 0,
            "primeiro_usado": None,
            "referencias_zero_km": [],
            "indice_busca_zero": 0,
            "zero_km_base": None,
            "referencias_planejadas": [],
            "offset_coleta": 0,
            "historico": [],
            "falhas_coleta": 0,
            "erros_404_ignorados": 0,
            "limite_interrompeu": False,
            "eventos": [
                {
                    "tipo": "inicio",
                    "mensagem": "Diagnóstico V19.17 iniciado em módulo paralelo. Nenhuma curva será salva.",
                },
                {
                    "tipo": "fonte_historica",
                    "mensagem": (
                        "Fonte FIPE Web V19.17 ativa."
                        if (str((referencias[0] or {}).get("fonte") or "") == "fipe_web_v1917")
                        else "FIPE Web V19.17 indisponível no início; usando fallback FIPE v2 por referência mensal."
                    ),
                }
            ],
        }
        self._salvar_job(job)
        return job

    def _referencias_serializadas(self) -> list[dict[str, Any]]:
        """Carrega referências mensais.

        O caminho preferencial da V24 é o mesmo do painel local V19.17:
        endpoint web da FIPE usado pelo aplicativo desktop. Se esse caminho
        não responder, o diagnóstico cai para a API v2 atual apenas como
        fallback, mantendo a coleta em lote e sem salvar curva.
        """
        refs: list[dict[str, Any]] = []
        self._ultima_falha_referencias_web = ""
        try:
            referencias_web = self.painel_adapter.referencias_ordenadas_web_v1917()
        except Exception as exc:
            referencias_web = []
            self._ultima_falha_referencias_web = f"{type(exc).__name__}: {exc}"
        if not referencias_web and not self._ultima_falha_referencias_web:
            self._ultima_falha_referencias_web = "ConsultarTabelaDeReferencia retornou vazio ou não foi parseável no ambiente web."
        for r in referencias_web or []:
            data_dt = r.get("data_ref")
            data_ref = data_dt.strftime("%Y-%m") if hasattr(data_dt, "strftime") else str(data_dt or "")[:7]
            code = str(r.get("code") or r.get("codigo_tabela_referencia") or "").strip()
            month = str(r.get("month") or "").strip()
            if code and data_ref:
                refs.append({"code": code, "month": month, "data_ref": data_ref, "fonte": "fipe_web_v1917"})
        if refs:
            refs.sort(key=lambda x: x["data_ref"])
            return refs

        for r in self.painel_adapter.referencias_ordenadas():
            data_dt = r.get("data_ref")
            data_ref = data_dt.strftime("%Y-%m") if hasattr(data_dt, "strftime") else str(data_dt or "")[:7]
            code = str(r.get("code") or "").strip()
            month = str(r.get("month") or "").strip()
            if code and data_ref:
                refs.append({"code": code, "month": month, "data_ref": data_ref, "fonte": "fipe_v2"})
        refs.sort(key=lambda x: x["data_ref"])
        return refs

    def _resolver_data_base_operacao(self, payload: dict[str, Any], referencias: list[dict[str, Any]]) -> str:
        bruto = str(payload.get("data_base_operacao") or payload.get("data_base") or "").strip()
        if bruto:
            try:
                if len(bruto) >= 7:
                    parse_ano_mes(bruto[:7])
                    return bruto[:7]
            except Exception:
                pass
        hoje = datetime.now()
        atual = f"{hoje.year:04d}-{hoje.month:02d}"
        refs_validas = [r["data_ref"] for r in referencias if r.get("data_ref") and r["data_ref"] <= atual]
        if refs_validas:
            return refs_validas[-1]
        return referencias[-1]["data_ref"] if referencias else atual

    def _resolver_ano_preferencial(self, payload: dict[str, Any], data_base_operacao: str) -> int:
        override = parse_int_seguro(payload.get("ano_base_preferencial") or payload.get("ano_base_curva") or 0, 0)
        if override >= 1900:
            return override
        ano, _mes = parse_ano_mes(data_base_operacao)
        return int(ano) - 7

    def _listar_anos_disponiveis(self, veiculo: VeiculoSelecionado) -> list[dict[str, Any]]:
        anos = self.fipe.listar_anos(veiculo.codigo_marca, veiculo.codigo_modelo)
        saida: list[dict[str, Any]] = []
        for a in anos or []:
            codigo = str(a.get("codigo") or a.get("code") or "").strip()
            nome = str(a.get("nome") or a.get("name") or "").strip()
            ano = self._ano_do_codigo_ano(codigo)
            suffix = self._suffix_codigo_ano(codigo)
            if ano is None:
                continue
            saida.append({"codigo": codigo, "nome": nome, "ano": ano, "suffix": suffix, "zero_km": codigo.startswith("32000")})
        saida.sort(key=lambda x: int(x["ano"]))
        return saida

    def _escolher_coorte_base(
        self,
        anos_disponiveis: list[dict[str, Any]],
        ano_preferencial: int,
        codigo_ano_selecionado: str,
        combustivel: str,
    ) -> dict[str, Any] | None:
        usados = [a for a in anos_disponiveis if not a.get("zero_km")]
        if not usados:
            return None
        suffix_sel = self._suffix_codigo_ano(codigo_ano_selecionado)
        if suffix_sel:
            filtrados = [a for a in usados if str(a.get("suffix") or "") == suffix_sel]
            if filtrados:
                usados = filtrados
        compativeis = [a for a in usados if self._combustivel_nome_compativel(str(a.get("nome") or ""), combustivel)]
        if compativeis:
            usados = compativeis
        anos = sorted({int(a["ano"]) for a in usados})
        if not anos:
            return None
        if ano_preferencial in anos:
            escolhido = ano_preferencial
        else:
            abaixo = [a for a in anos if a <= ano_preferencial]
            escolhido = max(abaixo) if abaixo else min(anos)
        item = next((a for a in usados if int(a["ano"]) == int(escolhido)), None)
        return {
            "ano": int(escolhido),
            "codigo_ano": str(item.get("codigo") if item else ""),
            "nome": str(item.get("nome") if item else escolhido),
            "criterio": "preferir ano da data-base menos 7; se não existir, usar ano usado mais próximo sem ultrapassar; modelo recente usa primeiro disponível",
            "ano_base_preferencial": int(ano_preferencial),
        }

    # ------------------------------------------------------------------
    # Execução em lote para evitar timeout no Render/Gunicorn.
    # ------------------------------------------------------------------
    def _executar_lote(self, job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        limite = self._limite_lote(payload)
        if str(job.get("fonte_historico") or "") == "fipe_web_v1917":
            # Cada referência no fluxo fiel V19.17 pode exigir 4 chamadas ao endpoint web
            # da FIPE. No Render/Gunicorn, uma referência por requisição é mais seguro.
            limite = min(limite, 1)
        processadas = 0
        while processadas < limite and job.get("fase") not in {"concluido", "erro_controlado", "erro_api_fipe", "primeira_aparicao_nao_encontrada", "zero_km_nao_encontrado"}:
            fase = str(job.get("fase") or "")
            if fase == "buscar_primeira_aparicao":
                fez = self._passo_buscar_primeira(job)
            elif fase == "buscar_zero_km":
                fez = self._passo_buscar_zero_km(job)
            elif fase == "planejar_historico":
                self._planejar_historico(job)
                fez = 0
            elif fase == "coletar_historico":
                fez = self._passo_coletar_historico(job)
            else:
                job["fase"] = "erro_controlado"
                job["erro"] = {"mensagem": f"Fase desconhecida: {fase}"}
                break
            processadas += max(1, int(fez or 0))
            if fez == 0 and str(job.get("fase")) in {"planejar_historico", "coletar_historico"}:
                continue
        job["ultima_execucao_lote"] = {"limite_referencias": limite, "processadas": processadas}
        return job

    def _limite_lote(self, payload: dict[str, Any]) -> int:
        # Cada referência de busca pode consumir várias chamadas FIPE. Mantém teto baixo.
        bruto = parse_int_seguro(payload.get("max_referencias_por_chamada") or payload.get("limite_lote") or 4, 4)
        return max(1, min(12, bruto))

    def _passo_buscar_primeira(self, job: dict[str, Any]) -> int:
        refs = job.get("referencias_busca") or []
        idx = int(job.get("indice_busca_primeira") or 0)
        if idx >= len(refs):
            job["fase"] = "primeira_aparicao_nao_encontrada"
            job.setdefault("eventos", []).append({"tipo": "falha", "mensagem": "Primeira aparição não encontrada na janela de referências."})
            return 0
        ref = refs[idx]
        veiculo = job["veiculo"]
        coorte = job["coorte_base"]
        try:
            if str(job.get("fonte_historico") or "") == "fipe_web_v1917":
                ponto = self.painel_adapter.consultar_ponto_modelo_primeiro_web_v1917(
                    reference=str(ref.get("code") or ""),
                    mes_referencia=str(ref.get("month") or ""),
                    codigo_marca_atual=str(veiculo.get("codigo_marca") or ""),
                    nome_marca=str(veiculo.get("marca") or ""),
                    nome_modelo=str(veiculo.get("modelo") or ""),
                    ano_base=int(coorte["ano"]),
                    combustivel=str(veiculo.get("combustivel") or ""),
                )
            else:
                ponto = self.painel_adapter.consultar_ponto_modelo_primeiro_v19(
                    reference=str(ref.get("code") or ""),
                    mes_referencia=str(ref.get("month") or ""),
                    codigo_marca_atual=str(veiculo.get("codigo_marca") or ""),
                    nome_marca=str(veiculo.get("marca") or ""),
                    nome_modelo=str(veiculo.get("modelo") or ""),
                    ano_base=int(coorte["ano"]),
                    combustivel=str(veiculo.get("combustivel") or ""),
                )
        except FipeApiError as exc:
            if exc.status_code in (401, 403, 429):
                raise
            if exc.status_code == 404:
                job["erros_404_ignorados"] = int(job.get("erros_404_ignorados") or 0) + 1
            else:
                job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
            ponto = PontoHistoricoPainel(False, str(ref.get("code") or ""), str(ref.get("month") or ""), motivo=f"erro_api_controlado:{exc.tipo}:{exc.message}", debug={"status_code": exc.status_code, "endpoint": exc.endpoint})
        except Exception as exc:
            job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
            ponto = PontoHistoricoPainel(False, str(ref.get("code") or ""), str(ref.get("month") or ""), motivo=f"erro_controlado:{type(exc).__name__}:{exc}")
        job["indice_busca_primeira"] = idx + 1
        if ponto.ok and ponto.valor:
            job["primeiro_usado"] = ponto.to_dict()
            job.setdefault("eventos", []).append({
                "tipo": "primeira_aparicao",
                "mensagem": f"Primeira aparição encontrada em {ponto.data_referencia} ({ponto.valor_formatado}).",
            })
            self._preparar_referencias_zero(job)
            job["fase"] = "buscar_zero_km"
        else:
            tentativas = job.setdefault("tentativas_primeira_aparicao", [])
            if len(tentativas) < 20:
                tentativas.append({"reference": ref.get("code"), "mes": ref.get("month"), "data_ref": ref.get("data_ref"), "motivo": ponto.motivo, "debug": ponto.debug or {}})
        return 1

    def _preparar_referencias_zero(self, job: dict[str, Any]) -> None:
        primeiro = job.get("primeiro_usado") or {}
        data_primeiro = str(primeiro.get("data_referencia") or "")
        inicio_busca = f"{max(int(job['coorte_base']['ano']) - 1, 1990):04d}-01"
        refs = [r for r in job.get("referencias") or [] if r.get("data_ref") and inicio_busca <= r["data_ref"] <= data_primeiro]
        refs.sort(key=lambda x: x["data_ref"], reverse=True)
        # Garante que a referência da primeira aparição seja a primeira tentativa.
        ref_primeiro = next((r for r in refs if str(r.get("code")) == str(primeiro.get("reference"))), None)
        if ref_primeiro:
            refs = [ref_primeiro] + [r for r in refs if str(r.get("code")) != str(ref_primeiro.get("code"))]
        job["referencias_zero_km"] = refs
        job["indice_busca_zero"] = 0

    def _passo_buscar_zero_km(self, job: dict[str, Any]) -> int:
        refs = job.get("referencias_zero_km") or []
        idx = int(job.get("indice_busca_zero") or 0)
        if idx >= len(refs):
            job["fase"] = "zero_km_nao_encontrado"
            job.setdefault("eventos", []).append({"tipo": "falha", "mensagem": "Zero km 32000 não encontrado para a coorte base."})
            return 0
        ref = refs[idx]
        primeiro = self._ponto_historico_from_dict(job.get("primeiro_usado") or {})
        if str(job.get("fonte_historico") or "") == "fipe_web_v1917":
            zero = self.painel_adapter.consultar_zero_km_web_v1917(referencia={"code": ref.get("code"), "month": ref.get("month")}, primeiro_usado=primeiro)
        else:
            zero = self.painel_adapter._consultar_zero_km_v19(referencia={"code": ref.get("code"), "month": ref.get("month")}, primeiro_usado=primeiro)
        job["indice_busca_zero"] = idx + 1
        if zero and zero.valor:
            z = zero.to_dict()
            z["tipo"] = "zero_km"
            job["zero_km_base"] = z
            job.setdefault("eventos", []).append({
                "tipo": "zero_km",
                "mensagem": f"Zero km base encontrado em {z.get('data_referencia')} ({z.get('valor_formatado')}).",
            })
            job["fase"] = "planejar_historico"
        else:
            tentativas = job.setdefault("tentativas_zero_km", [])
            if len(tentativas) < 20:
                tentativas.append({"reference": ref.get("code"), "mes": ref.get("month"), "data_ref": ref.get("data_ref"), "motivo": "zero_km_nao_encontrado_nesta_referencia"})
        return 1

    def _planejar_historico(self, job: dict[str, Any]) -> None:
        zero = job.get("zero_km_base") or {}
        inicio = str(zero.get("data_referencia") or "")
        data_final = str(job.get("data_base_operacao") or "")
        if not inicio or not data_final:
            raise ValueError("Não foi possível planejar histórico sem zero km e data final.")
        refs_filtradas = [r for r in job.get("referencias") or [] if r.get("data_ref") and inicio <= r["data_ref"] <= data_final]
        refs_filtradas.sort(key=lambda x: x["data_ref"])
        if not refs_filtradas:
            raise ValueError("Nenhuma referência FIPE disponível entre zero km e data final.")
        total_meses = diferenca_meses(inicio, data_final) + 1
        passo_meses = 1 if total_meses <= 36 else 2
        refs_amostradas: list[dict[str, Any]] = []
        ultimo_mes: str | None = None
        for i, ref in enumerate(refs_filtradas):
            incluir = False
            if i == len(refs_filtradas) - 1 or ultimo_mes is None:
                incluir = True
            else:
                if diferenca_meses(ultimo_mes, ref["data_ref"]) >= passo_meses:
                    incluir = True
            if incluir:
                refs_amostradas.append(ref)
                ultimo_mes = ref["data_ref"]
        anos = sorted({int(r["data_ref"][:4]) for r in refs_filtradas})
        for ano in anos:
            if not any(int(r["data_ref"][:4]) == ano for r in refs_amostradas):
                refs_ano = [r for r in refs_filtradas if int(r["data_ref"][:4]) == ano]
                if refs_ano:
                    refs_amostradas.append(refs_ano[len(refs_ano) // 2])
        refs_unicas = {str(r["code"]): r for r in refs_amostradas}
        refs_amostradas = sorted(refs_unicas.values(), key=lambda x: x["data_ref"])

        hist_zero = {
            "data_referencia": str(zero.get("data_referencia")),
            "mes_referencia": str(zero.get("mes") or zero.get("data_referencia")),
            "preco_nominal": float(zero.get("valor") or 0),
            "valor_formatado": zero.get("valor_formatado") or formatar_brl(float(zero.get("valor") or 0)),
            "tipo": "zero_km",
            "reference": str(zero.get("reference") or ""),
        }
        job["referencias_planejadas"] = refs_amostradas
        job["offset_coleta"] = 0
        job["historico"] = [hist_zero] if hist_zero["preco_nominal"] > 0 else []
        job["passo_meses"] = passo_meses
        job["janela_planejada_meses"] = total_meses
        job["fase"] = "coletar_historico"
        job.setdefault("eventos", []).append({
            "tipo": "plano_historico",
            "mensagem": f"Histórico planejado de {inicio} a {data_final}: {len(refs_amostradas)} referências, passo {passo_meses} mês(es).",
        })

    def _passo_coletar_historico(self, job: dict[str, Any]) -> int:
        refs = job.get("referencias_planejadas") or []
        idx = int(job.get("offset_coleta") or 0)
        if idx >= len(refs):
            job["fase"] = "concluido"
            self._deduplicar_historico(job)
            job.setdefault("eventos", []).append({"tipo": "coleta_concluida", "mensagem": "Coleta V19.17 concluída. Nenhuma curva foi salva."})
            return 0
        ref = refs[idx]
        primeiro = job.get("primeiro_usado") or {}
        try:
            if str(job.get("fonte_historico") or "") == "fipe_web_v1917":
                ponto = self.painel_adapter.consultar_preco_usado_web_v1917(referencia=ref, primeiro_usado=self._ponto_historico_from_dict(primeiro))
                valor = float(ponto.valor or 0)
                valor_txt = ponto.valor_formatado or formatar_brl(valor)
                if ponto.ok and valor > 0:
                    data_ref = str(ponto.data_referencia or ref.get("data_ref") or "")
                    job.setdefault("historico", []).append({
                        "data_referencia": data_ref,
                        "mes_referencia": str(ponto.mes or ref.get("month") or ""),
                        "preco_nominal": float(valor),
                        "valor_formatado": valor_txt if isinstance(valor_txt, str) and valor_txt else formatar_brl(float(valor)),
                        "tipo": "usado",
                        "reference": str(ref.get("code") or ""),
                    })
                else:
                    job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
                    tentativas = job.setdefault("tentativas_historico", [])
                    if len(tentativas) < 20:
                        tentativas.append({"reference": ref.get("code"), "mes": ref.get("month"), "data_ref": ref.get("data_ref"), "motivo": ponto.motivo})
            else:
                detalhe = self.fipe.consultar_preco_referencia(
                    str(primeiro.get("codigo_marca_referencia") or ""),
                    str(primeiro.get("codigo_modelo_referencia") or ""),
                    str(primeiro.get("codigo_ano_referencia") or ""),
                    str(ref.get("code") or ""),
                )
                valor_txt = detalhe.get("Valor") or detalhe.get("price") or ""
                valor = parse_float_seguro(valor_txt)
                if valor and valor > 0:
                    data_ref = str(ref.get("data_ref") or "")
                    job.setdefault("historico", []).append({
                        "data_referencia": data_ref,
                        "mes_referencia": str(ref.get("month") or detalhe.get("MesReferencia") or detalhe.get("referenceMonth") or ""),
                        "preco_nominal": float(valor),
                        "valor_formatado": valor_txt if isinstance(valor_txt, str) and valor_txt else formatar_brl(float(valor)),
                        "tipo": "usado",
                        "reference": str(ref.get("code") or ""),
                    })
                else:
                    job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
        except FipeApiError as exc:
            if exc.status_code == 429:
                job["limite_interrompeu"] = True
                raise
            if exc.status_code == 404:
                job["erros_404_ignorados"] = int(job.get("erros_404_ignorados") or 0) + 1
            else:
                job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
        except Exception:
            job["falhas_coleta"] = int(job.get("falhas_coleta") or 0) + 1
        job["offset_coleta"] = idx + 1
        self._deduplicar_historico(job)
        if int(job.get("offset_coleta") or 0) >= len(refs):
            job["fase"] = "concluido"
            job.setdefault("eventos", []).append({"tipo": "coleta_concluida", "mensagem": "Coleta V19.17 concluída. Nenhuma curva foi salva."})
        return 1

    # ------------------------------------------------------------------
    # Cálculo e resposta.
    # ------------------------------------------------------------------
    def _montar_resposta(self, job: dict[str, Any], executar_calculo: bool = True) -> dict[str, Any]:
        self._deduplicar_historico(job)
        historico = job.get("historico") or []
        pontos_total = len(historico)
        pontos_usados = len([p for p in historico if str(p.get("tipo")) != "zero_km"])
        refs_planejadas = job.get("referencias_planejadas") or []
        coleta_concluida = str(job.get("fase")) == "concluido"
        calculo = None
        erro_calculo = None
        if executar_calculo and pontos_total >= 8 and job.get("zero_km_base"):
            try:
                calculo = self._calcular_diagnostico(job)
                job["resultado_calculo"] = calculo
            except Exception as exc:
                erro_calculo = f"{type(exc).__name__}: {exc}"
                job["erro_calculo"] = erro_calculo
        elif job.get("resultado_calculo") and not executar_calculo:
            calculo = job.get("resultado_calculo")

        qualidade = self._classificar_qualidade(pontos_usados, self._janela_historico_meses(historico))
        status = self._status_publico(job, calculo)
        mensagem = self._mensagem_publica(job, qualidade, calculo)
        amostragem = self._montar_amostragem(job)
        relatorio = self._montar_relatorio_textual(job, qualidade, calculo, erro_calculo)
        top = {
            "ok": str(job.get("fase")) not in {"erro_controlado", "erro_api_fipe", "primeira_aparicao_nao_encontrada", "zero_km_nao_encontrado"},
            "motor": self.VERSAO,
            "status": status,
            "mensagem": mensagem,
            "job_id": job.get("job_id"),
            "fase": job.get("fase"),
            "coleta_concluida": coleta_concluida,
            "pode_salvar": False,
            "criterio_salvamento": "Diagnóstico V24 não salva curva. Integração/salvamento só depois de validar o caso-padrão e atingir critério mínimo.",
            "modo_pandemia": job.get("modo_pandemia"),
            "modo_calculo_proposto": "motor_local_v19_17_portado_em_adapter_paralelo",
            "fonte_historico": job.get("fonte_historico"),
            "falha_fipe_web_v1917": job.get("falha_fipe_web_v1917"),
            "total_referencias_disponiveis": job.get("total_referencias_disponiveis"),
            "total_referencias_busca": job.get("total_referencias_busca"),
            "indice_busca_primeira": job.get("indice_busca_primeira"),
            "referencias_fipe_web_v1917": job.get("referencias_fipe_web_v1917"),
            "referencias_fipe_v2": job.get("referencias_fipe_v2"),
            "zero_km_detectado": bool(job.get("selecionado_zero_km")),
            "tem_zero_km_na_fipe": bool(job.get("zero_km_base")),
            "ano_base_preferencial": job.get("ano_base_preferencial"),
            "coorte_base": job.get("coorte_base"),
            "primeira_aparicao": job.get("primeiro_usado"),
            "zero_km_base": job.get("zero_km_base"),
            "price_history_coorte_base_pontos": 0,
            "pontos_historicos": pontos_usados,
            "pontos_historicos_total_com_zero": pontos_total,
            "janela_historica_meses": self._janela_historico_meses(historico),
            "qualidade_estimativa": qualidade["classe"],
            "qualidade_detalhe": qualidade,
            "amostragem_referencias": amostragem,
            "relatorio_textual": relatorio,
            "erro": job.get("erro"),
            "erro_calculo": erro_calculo,
            "eventos": (job.get("eventos") or [])[-12:],
        }
        if calculo:
            top.update(calculo)
        return top

    def _calcular_diagnostico(self, job: dict[str, Any]) -> dict[str, Any]:
        veiculo = job["veiculo"]
        historico = sorted(job.get("historico") or [], key=lambda p: str(p.get("data_referencia") or ""))
        zero = next((h for h in historico if str(h.get("tipo")) == "zero_km" and float(h.get("preco_nominal") or 0) > 0), None)
        if not zero:
            raise ValueError("Histórico sem zero km base.")
        coorte_ano = int(job["coorte_base"]["ano"])
        nome_veiculo = f"{veiculo.get('marca', '')} {veiculo.get('modelo', '')} {coorte_ano}".strip()
        dados_veiculo = {
            "veiculo": nome_veiculo,
            "categoria": str(veiculo.get("marca") or "Sob demanda"),
            "ano_modelo": coorte_ano,
            "preco_zero_km_base": float(zero["preco_nominal"]),
            "data_preco_zero_km_base": str(zero["data_referencia"]),
            "historico": [
                {"data_referencia": str(h["data_referencia"]), "valor_fipe": float(h["preco_nominal"])}
                for h in historico
                if h.get("data_referencia") and float(h.get("preco_nominal") or 0) > 0
            ],
        }
        indices = self.ipca_repo.carregar_indices()
        curva = calcular_curva_v1917(
            dados_veiculo=dados_veiculo,
            horizonte_anos=float(veiculo.get("horizonte_anos") or 5),
            indices_inflacao=indices,
            modo_pandemia=str(job.get("modo_pandemia") or "Excluir"),
            minimo_pontos_veiculo=8,
        )
        horizonte_meses = max(1, int(curva.horizonte_meses or 60))
        idade_entrada = 0 if bool(job.get("selecionado_zero_km")) else self._calcular_idade_entrada_meses(veiculo, str(job.get("data_base_operacao") or curva.periodo_final))
        fator_base = calcular_fator_cumulativo_por_idade(curva.taxa_mensal_hibrida_percentual, idade_entrada, horizonte_meses)
        fator_ot = calcular_fator_cumulativo_por_idade(curva.taxa_mensal_hibrida_percentual * 0.80, idade_entrada, horizonte_meses)
        fator_pe = calcular_fator_cumulativo_por_idade(curva.taxa_mensal_hibrida_percentual * 1.20, idade_entrada, horizonte_meses)
        valor_atual = float(veiculo.get("valor_atual") or 0) or float(curva.valor_fipe_atual)
        valor_futuro = valor_atual * fator_base
        valor_futuro_ot = valor_atual * fator_ot
        valor_futuro_pe = valor_atual * fator_pe
        taxa_plataforma = calcular_taxa_anual_efetiva_do_fator(fator_base, horizonte_meses)
        taxa_ot = calcular_taxa_anual_efetiva_do_fator(fator_ot, horizonte_meses)
        taxa_pe = calcular_taxa_anual_efetiva_do_fator(fator_pe, horizonte_meses)
        pontos_usados = len([h for h in historico if str(h.get("tipo")) != "zero_km"])
        janela = self._janela_historico_meses(historico)
        qualidade = self._classificar_qualidade(pontos_usados, janela)
        dep_pct = (1.0 - fator_base) * 100.0
        resultado_curva = curva.to_dict()
        return {
            "resultado_calculo": resultado_curva,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_otimista": round(valor_futuro_ot, 2),
            "valor_futuro_pessimista": round(valor_futuro_pe, 2),
            "depreciacao_percentual": round(dep_pct, 4),
            "taxa_anual_percentual": round(taxa_plataforma, 4),
            "taxa_para_plataforma_percentual": round(taxa_plataforma, 4),
            "taxa_anual_otimista_percentual": round(taxa_ot, 4),
            "taxa_anual_pessimista_percentual": round(taxa_pe, 4),
            "confianca": qualidade["classe"],
            "origem_curva": "diagnóstico V19.17 paralelo; curva não salva",
            "horizonte_anos": int(veiculo.get("horizonte_anos") or 5),
            "horizonte_meses": horizonte_meses,
            "idade_entrada_curva_meses": idade_entrada,
            "idade_entrada_curva_anos": round(idade_entrada / 12.0, 2),
            "pontos_historicos": pontos_usados,
            "pontos_historicos_total_com_zero": len(historico),
            "janela_historica_meses": janela,
            "periodo_inicial": historico[0].get("data_referencia") if historico else None,
            "periodo_final": historico[-1].get("data_referencia") if historico else None,
            "detalhes": {
                "tipo_label": "Zero km" if job.get("selecionado_zero_km") else "Usado com offset de idade V19.17",
                "auditoria_historico": {
                    "fonte_historico": "FIPE reconstruída por referência mensal, sem usar /history como espinha dorsal",
                    "primeira_aparicao": job.get("primeiro_usado"),
                    "zero_km_base": job.get("zero_km_base"),
                    "modo_pandemia": job.get("modo_pandemia"),
                    "taxa_mensal_hibrida_percentual": curva.taxa_mensal_hibrida_percentual,
                    "taxa_anual_sem_offset_percentual": curva.depreciacao_media_anual_principal_percentual,
                    "taxa_anual_com_offset_percentual": taxa_plataforma,
                    "idade_entrada_meses": idade_entrada,
                    "pontos_historicos": pontos_usados,
                    "meses_janela": janela,
                    "status_serie": qualidade["classe"],
                    "pode_salvar": False,
                },
            },
        }

    def _montar_amostragem(self, job: dict[str, Any]) -> dict[str, Any]:
        hist = job.get("historico") or []
        refs = job.get("referencias_planejadas") or []
        pontos_usados = [h for h in hist if str(h.get("tipo")) != "zero_km"]
        primeiro_ponto = self._ponto_resumo(hist[0]) if hist else None
        ultimo_ponto = self._ponto_resumo(hist[-1]) if hist else None
        variacao = None
        if len(hist) >= 2 and float(hist[0].get("preco_nominal") or 0) > 0:
            variacao = round(((float(hist[-1].get("preco_nominal") or 0) - float(hist[0].get("preco_nominal") or 0)) / float(hist[0].get("preco_nominal") or 1)) * 100.0, 2)
        return {
            "criterio_passo": f"V19.17: primeira aparição + zero km + histórico amostrado por referência mensal; passo {job.get('passo_meses') or '-'} mês(es)",
            "estrategia_historico": "v1917_adapter_parallel_sem_history_curto",
            "fonte_historico": job.get("fonte_historico"),
            "falha_fipe_web_v1917": job.get("falha_fipe_web_v1917"),
            "total_referencias_disponiveis": job.get("total_referencias_disponiveis"),
            "total_referencias_busca": job.get("total_referencias_busca"),
            "indice_busca_primeira": job.get("indice_busca_primeira"),
            "pontos_planejados": len(refs) + (1 if job.get("zero_km_base") else 0),
            "pontos_validos": len(hist),
            "pontos_usados_validos": len(pontos_usados),
            "referencias_processadas": int(job.get("offset_coleta") or 0),
            "proximo_offset": int(job.get("offset_coleta") or 0),
            "total_referencias_coleta": len(refs),
            "coleta_concluida": str(job.get("fase")) == "concluido",
            "passo_meses": job.get("passo_meses"),
            "janela_planejada_meses": job.get("janela_planejada_meses"),
            "primeiro_ponto": primeiro_ponto,
            "ultimo_ponto": ultimo_ponto,
            "variacao_percentual_observada": variacao,
            "falhas_coleta": int(job.get("falhas_coleta") or 0),
            "erros_404_ignorados": int(job.get("erros_404_ignorados") or 0),
            "limite_interrompeu": bool(job.get("limite_interrompeu")),
            "amostra": [self._ponto_resumo(p) for p in hist[:12]],
        }

    def _montar_relatorio_textual(self, job: dict[str, Any], qualidade: dict[str, Any], calculo: dict[str, Any] | None, erro_calculo: str | None) -> str:
        veiculo = job.get("veiculo") or {}
        linhas = [
            "DIAGNÓSTICO TÉCNICO V24 - MOTOR LOCAL V19.17 PORTADO",
            "",
            "Este diagnóstico roda em módulo paralelo e não salva curva definitiva.",
            f"Veículo selecionado: {veiculo.get('marca', '')} {veiculo.get('modelo', '')} {veiculo.get('ano_modelo', '')}".strip(),
            f"Código FIPE: {veiculo.get('codigo_fipe', '-')}",
            f"Modo pandemia: {job.get('modo_pandemia') or 'Excluir'}",
            f"Data-base da operação: {job.get('data_base_operacao')}",
            "",
            "A. BASE/COORTE",
            f"Ano-base preferencial: {job.get('ano_base_preferencial')}",
            f"Coorte/base usada: {((job.get('coorte_base') or {}).get('ano'))} - {((job.get('coorte_base') or {}).get('nome'))}",
            f"Primeira aparição: {((job.get('primeiro_usado') or {}).get('data_referencia')) or '-'}",
            f"Zero km base: {((job.get('zero_km_base') or {}).get('data_referencia')) or '-'}",
            "",
            "B. COLETA",
            f"Fase atual: {job.get('fase')}",
            f"Fonte histórica: {job.get('fonte_historico') or '-'}",
            f"Referências FIPE disponíveis: {job.get('total_referencias_disponiveis') or 0}; janela de busca: {job.get('total_referencias_busca') or 0}; busca primeira aparição: {job.get('indice_busca_primeira') or 0}/{job.get('total_referencias_busca') or 0}",
            f"Aviso FIPE Web V19.17: {job.get('falha_fipe_web_v1917') or 'sem falha registrada'}",
            f"Pontos válidos usados: {qualidade.get('pontos_usados')} usado(s) + zero km quando disponível",
            f"Janela histórica: {qualidade.get('janela_meses')} mês(es)",
            f"Qualidade: {qualidade.get('classe')} - {qualidade.get('descricao')}",
            f"Falhas controladas: {job.get('falhas_coleta') or 0}; 404 ignorados: {job.get('erros_404_ignorados') or 0}",
        ]
        if calculo:
            linhas.extend([
                "",
                "C. RESULTADO DIAGNÓSTICO",
                f"Valor atual usado: {formatar_brl(calculo.get('valor_atual') or 0)}",
                f"Valor futuro base: {formatar_brl(calculo.get('valor_futuro') or 0)}",
                f"Taxa para plataforma com offset: {float(calculo.get('taxa_para_plataforma_percentual') or 0):.4f}% a.a.",
                f"Idade de entrada na curva: {calculo.get('idade_entrada_curva_meses')} meses",
                f"Taxa mensal híbrida da curva base: {float((calculo.get('resultado_calculo') or {}).get('taxa_mensal_hibrida_percentual') or 0):.4f}%",
            ])
        elif erro_calculo:
            linhas.extend(["", f"C. CÁLCULO AINDA NÃO HOMOLOGADO: {erro_calculo}"])
        else:
            linhas.extend(["", "C. RESULTADO: coleta ainda incompleta ou histórico abaixo do mínimo de cálculo."])
        linhas.extend([
            "",
            "D. REGRA DE SEGURANÇA",
            "0-3 pontos: não calcular; 4-7: diagnóstico; 8-15: exploratório; 16-23: médio; 24+: alto; 50/60: robusto.",
            "Nesta etapa V24 o resultado é diagnóstico. O botão Calcular/salvar definitivo continua protegido.",
        ])
        return "\n".join(linhas)

    # ------------------------------------------------------------------
    # Utilitários.
    # ------------------------------------------------------------------
    def _deduplicar_historico(self, job: dict[str, Any]) -> None:
        hist = job.get("historico") or []
        unicos: dict[tuple[str, str], dict[str, Any]] = {}
        for p in hist:
            data = str(p.get("data_referencia") or "")
            tipo = str(p.get("tipo") or "usado")
            if not data:
                continue
            chave = (data, tipo)
            unicos[chave] = p
        job["historico"] = sorted(unicos.values(), key=lambda p: (str(p.get("data_referencia") or ""), 0 if str(p.get("tipo")) == "zero_km" else 1))

    def _ponto_resumo(self, p: dict[str, Any]) -> dict[str, Any]:
        valor = float(p.get("preco_nominal") or p.get("valor") or 0)
        return {
            "data_referencia": p.get("data_referencia"),
            "mes": p.get("mes_referencia") or p.get("mes"),
            "valor": round(valor, 2),
            "valor_formatado": p.get("valor_formatado") or formatar_brl(valor),
            "tipo": p.get("tipo") or "usado",
            "reference": p.get("reference"),
        }

    def _janela_historico_meses(self, historico: list[dict[str, Any]]) -> int:
        datas = sorted([str(h.get("data_referencia") or "") for h in historico if h.get("data_referencia")])
        if len(datas) < 2:
            return 0
        try:
            return max(0, diferenca_meses(datas[0], datas[-1]))
        except Exception:
            return 0

    def _classificar_qualidade(self, pontos_usados: int, janela_meses: int) -> dict[str, Any]:
        p = int(pontos_usados or 0)
        if p <= 3:
            classe, desc = "INSUFICIENTE", "0 a 3 pontos: não calcular."
        elif p <= 7:
            classe, desc = "DIAGNÓSTICO", "4 a 7 pontos: diagnóstico apenas, sem salvar."
        elif p <= 15:
            classe, desc = "EXPLORATÓRIA", "8 a 15 pontos: cálculo exploratório, sem salvar definitivo."
        elif p <= 23:
            classe, desc = "MÉDIA", "16 a 23 pontos: base média; validar antes de salvar."
        elif p >= 50:
            classe, desc = "ALTA/ROBUSTA", "50+ pontos: base alta/robusta quando metodologia e coorte conferem."
        else:
            classe, desc = "ALTA", "24+ pontos: base alta, desde que coorte e zero km estejam coerentes."
        return {"classe": classe, "descricao": desc, "pontos_usados": p, "janela_meses": int(janela_meses or 0)}

    def _status_publico(self, job: dict[str, Any], calculo: dict[str, Any] | None) -> str:
        fase = str(job.get("fase") or "")
        if fase == "concluido" and calculo:
            return "diagnostico_v1917_pronto"
        if fase == "concluido":
            return "coleta_concluida_sem_calculo"
        if fase.startswith("erro") or fase.endswith("nao_encontrado"):
            return fase
        return "coleta_v1917_em_andamento"

    def _mensagem_publica(self, job: dict[str, Any], qualidade: dict[str, Any], calculo: dict[str, Any] | None) -> str:
        fase = str(job.get("fase") or "")
        if fase == "concluido" and calculo:
            return f"Diagnóstico V19.17 concluído: {qualidade['classe']}. Nenhuma curva foi salva."
        if fase == "concluido":
            return "Coleta V19.17 concluída, mas ainda sem cálculo válido. Nenhuma curva foi salva."
        if fase == "buscar_primeira_aparicao":
            return "Buscando primeira aparição da coorte/base em lotes seguros. A tela pode continuar automaticamente sem salvar curva."
        if fase == "buscar_zero_km":
            return "Primeira aparição encontrada. Buscando zero km base 32000 em lote seguro."
        if fase == "coletar_historico":
            return "Coletando histórico FIPE em lotes pequenos para evitar timeout. A tela pode continuar automaticamente."
        if fase == "primeira_aparicao_nao_encontrada":
            return "Não foi possível localizar a primeira aparição da coorte/base nesta janela."
        if fase == "zero_km_nao_encontrado":
            return "Não foi possível localizar o zero km base 32000 para a coorte selecionada."
        erro = job.get("erro") or {}
        if erro:
            return str(erro.get("mensagem") or erro.get("erro") or erro)
        return "Diagnóstico V19.17 em andamento."

    def _ponto_historico_from_dict(self, dados: dict[str, Any]) -> PontoHistoricoPainel:
        return PontoHistoricoPainel(
            ok=bool(dados.get("ok", True)),
            reference=str(dados.get("reference") or ""),
            mes=str(dados.get("mes") or ""),
            data_referencia=dados.get("data_referencia"),
            valor=float(dados.get("valor") or 0) if dados.get("valor") is not None else None,
            valor_formatado=str(dados.get("valor_formatado") or ""),
            codigo_marca_referencia=str(dados.get("codigo_marca_referencia") or ""),
            codigo_modelo_referencia=str(dados.get("codigo_modelo_referencia") or ""),
            modelo_referencia=str(dados.get("modelo_referencia") or ""),
            codigo_ano_referencia=str(dados.get("codigo_ano_referencia") or ""),
            ano_referencia=str(dados.get("ano_referencia") or ""),
            codigo_tipo_combustivel=parse_int_seguro(dados.get("codigo_tipo_combustivel"), 0) if dados.get("codigo_tipo_combustivel") is not None else None,
            ano_modelo_referencia=parse_int_seguro(dados.get("ano_modelo_referencia"), 0) if dados.get("ano_modelo_referencia") is not None else None,
            estrategia=str(dados.get("estrategia") or ""),
            motivo=str(dados.get("motivo") or ""),
            debug=dados.get("debug") or {},
        )

    def _calcular_idade_entrada_meses(self, veiculo: dict[str, Any], data_base: str) -> int:
        ano_modelo = self._ano_modelo_selecionado(veiculo)
        if not ano_modelo or ano_modelo == 32000:
            return 0
        ano_base, mes_base = parse_ano_mes(data_base)
        idade_meses = (ano_base - int(ano_modelo)) * 12 + max(0, mes_base - 1)
        return max(0, idade_meses)

    def _ano_modelo_selecionado(self, veiculo: dict[str, Any]) -> int | None:
        for valor in (veiculo.get("ano_modelo"), veiculo.get("codigo_ano")):
            txt = str(valor or "").strip()
            if not txt:
                continue
            if "-" in txt:
                txt = txt.split("-", 1)[0]
            if txt.isdigit():
                return int(txt)
        return None

    @staticmethod
    def _codigo_ano_eh_zero(codigo_ano: str) -> bool:
        return str(codigo_ano or "").split("-", 1)[0] == "32000"

    @staticmethod
    def _ano_do_codigo_ano(codigo_ano: str) -> int | None:
        txt = str(codigo_ano or "").split("-", 1)[0]
        if txt.isdigit():
            return int(txt)
        return None

    @staticmethod
    def _suffix_codigo_ano(codigo_ano: str) -> str:
        txt = str(codigo_ano or "")
        if "-" in txt:
            return txt.split("-", 1)[1].strip()
        return ""

    @staticmethod
    def _combustivel_nome_compativel(nome_ano: str, combustivel_alvo: str) -> bool:
        alvo = normalizar_texto(combustivel_alvo)
        nome = normalizar_texto(nome_ano)
        if not alvo or not nome:
            return True
        if "flex" in alvo:
            return "flex" in nome
        if "diesel" in alvo:
            return "diesel" in nome
        if "eletrico" in alvo:
            return "eletrico" in nome
        if "hibrido" in alvo or "hybrid" in alvo:
            return "hibrido" in nome or "hybrid" in nome
        if "gasolina" in alvo:
            return "gasolina" in nome or "flex" in nome
        return True
