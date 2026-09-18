from __future__ import annotations

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, url_for

from services.noticias_service import carregar_noticias_home
from services.result_history_service import (
    build_result_history_view,
    is_valid_result_code,
    normalize_result_code,
)
from services.result_snapshot_service import ResultSnapshotError, get_result_snapshot_service
from services.site_usage_tracking import record_current_usage_event
from services.auth_access import access_control_enabled, current_auth_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    # V51.36 — a Home permanece visível como contexto visual mesmo durante o
    # acesso controlado. A própria template exibe um modal bloqueante para
    # visitantes/contas sem status active, sem liberar interação com a Home.
    return render_template("index.html", noticias=carregar_noticias_home())


@main_bp.route("/health")
def health():
    return jsonify({"ok": True, "service": "curve", "version": str(current_app.config.get("CURVE_VERSION") or "")})


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

    # V51.34 — snapshots novos pertencem à conta que os criou. O código S/D/F
    # deixa de ser, por si só, uma credencial de acesso a resultados de terceiros.
    owner_user_id = str(stored.get("owner_user_id") or "").strip()
    if owner_user_id:
        auth_user = current_auth_user()
        requester_user_id = str((auth_user or {}).get("public_id") or "").strip()
        if not auth_user or str(auth_user.get("access_status") or "") != "active":
            return redirect(url_for("auth.login", next=request.path, reason="login_required"))
        if requester_user_id != owner_user_id:
            return render_template(
                "consultar_resultado.html",
                codigo=codigo,
                erro="Este resultado pertence a outra conta e não pode ser aberto com o seu acesso.",
            ), 403

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
