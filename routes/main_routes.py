from __future__ import annotations

from flask import Blueprint, current_app, make_response, redirect, render_template, request, url_for

from services.noticias_service import carregar_noticias_home
from services.result_history_service import (
    build_result_history_view,
    is_valid_result_code,
    normalize_result_code,
)
from services.result_snapshot_service import ResultSnapshotError, get_result_snapshot_service
from services.site_usage_tracking import record_current_usage_event

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html", noticias=carregar_noticias_home())


@main_bp.route("/consulta-fipe")
@main_bp.route("/fipe")
def consulta_fipe():
    return render_template("consulta_fipe.html")


@main_bp.route("/depreciacao")
def depreciacao():
    return render_template("depreciacao.html")


@main_bp.route("/depreciacao/auditoria")
def depreciacao_auditoria():
    return render_template("auditoria_depreciacao.html")


@main_bp.route("/resultado")
def consultar_resultado():
    codigo = normalize_result_code(request.args.get("codigo") or "")
    if codigo:
        if not is_valid_result_code(codigo):
            return render_template(
                "consultar_resultado.html",
                codigo=codigo,
                erro="Código inválido. Confira o identificador S, D ou F impresso no resultado.",
            ), 400
        return redirect(url_for("main.resultado_historico", codigo=codigo))
    return render_template("consultar_resultado.html", codigo="", erro="")


@main_bp.route("/resultado/<codigo>")
def resultado_historico(codigo: str):
    codigo = normalize_result_code(codigo)
    if not is_valid_result_code(codigo):
        return render_template(
            "consultar_resultado.html",
            codigo=codigo,
            erro="Código inválido. Confira o identificador S, D ou F impresso no resultado.",
        ), 400

    try:
        stored = get_result_snapshot_service().get_snapshot(codigo, verify_integrity=True)
    except ResultSnapshotError as exc:
        current_app.logger.error("Falha de integridade ao recuperar resultado %s: %s", codigo, exc)
        return render_template(
            "consultar_resultado.html",
            codigo=codigo,
            erro="O resultado foi localizado, mas a verificação de integridade falhou. Não foi exibido.",
        ), 409

    if stored is None:
        return render_template(
            "consultar_resultado.html",
            codigo=codigo,
            erro="Nenhum resultado histórico foi encontrado para esse código.",
        ), 404

    view = build_result_history_view(stored)
    try:
        record_current_usage_event(
            event_type="interaction",
            module="resultado",
            action="historical_result_opened",
            metadata={
                "resultado_codigo": codigo,
                "resultado_tipo": str(stored.get("result_type") or ""),
                "resultado_modulo": str(stored.get("module") or ""),
            },
        )
    except Exception as analytics_error:
        current_app.logger.debug("Telemetria de resultado histórico ignorada: %s", analytics_error)
    response = make_response(render_template("resultado_historico.html", resultado=view))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@main_bp.route("/metodologia")
def metodologia():
    return redirect(url_for("tco.simular"))


@main_bp.route("/financiamento")
def financiamento():
    return render_template("financiamento.html")
