from __future__ import annotations

import json
from urllib.parse import unquote_plus

from flask import Blueprint, current_app, jsonify, render_template, request

from services.pbev_service import PbevService

pbev_bp = Blueprint("pbev", __name__)
pbev_pages_bp = Blueprint("pbev_pages", __name__)
pbev_service = PbevService()


def _payload_request() -> dict:
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            return payload
    return {k: v for k, v in request.args.items()}


@pbev_bp.route("/sugestao_consumo", methods=["GET", "POST"])
def sugestao_consumo():
    """Sugere consumo/eficiência PBEV para um veículo FIPE selecionado.

    O endpoint é propositalmente conservador: somente retorna autopreencher=true
    quando o backend classifica o match como alto e o registro PBEV não tem flags
    críticas. Match médio/baixo fica disponível para auditoria, mas a interface não
    deve preencher silenciosamente.
    """
    payload = _payload_request()
    try:
        resposta = pbev_service.sugerir_consumo(payload)
        resp = jsonify(resposta)
        # A base PBEV é local/versionada; o resultado por veículo pode ser cacheado por pouco tempo.
        resp.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=21600"
        return resp
    except Exception as exc:  # fallback seguro: a Simular deve continuar manual.
        current_app.logger.exception("Erro na sugestão PBEV/Inmetro: %s", exc)
        return jsonify({
            "encontrou": False,
            "nivel_match": "sem_match",
            "score": 0,
            "motivo": "Erro interno ao consultar PBEV; preenchimento manual mantido.",
            "autopreencher": False,
            "origem": "Inmetro/PBEV",
            "sugestoes_consumo": {},
            "candidato": None,
            "flags": {},
        }), 200


@pbev_pages_bp.route("/comprovacao", methods=["GET"])
def comprovacao_pbev():
    """Página de comprovação dos dados de consumo usados pela Simular.

    Recebe um payload compacto gerado no navegador após a seleção FIPE/PBEV e
    apresenta os valores considerados com link oficial da tabela Inmetro/PBEV.
    """
    dados_raw = request.args.get("dados") or ""
    dados = {}
    erro = ""
    if dados_raw:
        try:
            dados = json.loads(unquote_plus(dados_raw))
            if not isinstance(dados, dict):
                dados = {}
                erro = "Dados de comprovação inválidos."
        except Exception:
            dados = {}
            erro = "Não foi possível ler os dados de comprovação enviados pela Simular."
    else:
        erro = "Nenhum dado PBEV foi informado para comprovação."
    return render_template("pbev_comprovacao.html", dados=dados, erro=erro)


@pbev_bp.route("/status", methods=["GET"])
def status_pbev():
    """Diagnóstico leve para confirmar que a base saneada PBEV está carregável."""
    try:
        cache = pbev_service.carregar_base_pbev()
        manifest = cache.manifest or {}
        return jsonify({
            "ok": True,
            "origem": "Inmetro/PBEV",
            "base": cache.path,
            "registros": len(cache.registros),
            "marcas_indexadas": len(cache.indice_marca),
            "manifest_registros": (
                manifest.get("total_linhas_base_saneada")
                or manifest.get("registros")
                or manifest.get("total_registros")
                or manifest.get("qtd_registros")
            ),
        })
    except Exception as exc:
        current_app.logger.exception("Erro no status PBEV/Inmetro: %s", exc)
        return jsonify({"ok": False, "origem": "Inmetro/PBEV", "erro": str(exc)}), 500
