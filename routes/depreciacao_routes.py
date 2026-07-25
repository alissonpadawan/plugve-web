from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
import hmac
import traceback

from services.depreciacao_service import DepreciacaoService
from services.coorte_diagnostico_service import CoorteDiagnosticoService
from services.depreciacao_motor_v1917_adapter import DepreciacaoMotorV1917Adapter
from services.site_usage_service import get_site_usage_service
from repositories.curvas_repository import CurvasRepository

depreciacao_bp = Blueprint("depreciacao", __name__)
depreciacao_service = DepreciacaoService()
coorte_diagnostico_service = CoorteDiagnosticoService()
motor_v1917_adapter = DepreciacaoMotorV1917Adapter()
curvas_repository = CurvasRepository()


def _admin_token_recebido() -> str:
    token = request.headers.get("X-PlugVE-Admin-Token", "").strip()
    if token:
        return token
    token = request.headers.get("X-PlugVE-Sync-Token", "").strip()
    if token:
        return token
    token = request.args.get("token", "").strip()
    if token:
        return token
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _admin_token_valido() -> bool:
    esperado = str(
        current_app.config.get("PLUGVE_ADMIN_TOKEN", "")
        or current_app.config.get("PLUGVE_SYNC_TOKEN", "")
        or ""
    ).strip()
    recebido = _admin_token_recebido()
    return bool(esperado) and bool(recebido) and hmac.compare_digest(recebido, esperado)


@depreciacao_bp.route("/status")
def status():
    return jsonify(depreciacao_service.status_bases())


@depreciacao_bp.route("/painel")
def painel():
    try:
        return jsonify(depreciacao_service.painel_dados())
    except Exception as exc:
        return jsonify({"erro": str(exc)}), 500


@depreciacao_bp.route("/marcadores_curvas")
def marcadores_curvas():
    try:
        resp = jsonify(depreciacao_service.marcadores_curvas_salvas())
        # V35: os marcadores dependem de vínculos de similaridade enviados pelo
        # Painel Local. Não devem ficar presos em cache HTTP/CDN antigo, porque
        # isso faz a página Depreciação exibir só curvas próprias.
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc), "modelos": []}), 200


@depreciacao_bp.route("/resumo", methods=["POST"])
def resumo():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.obter_resumo(payload)
        is_internal_usage = bool(payload.get("origem_tco")) or str(payload.get("usage_context") or "").strip().lower() == "fipe_plus"
        if resultado.get("encontrado") and not is_internal_usage:
            try:
                get_site_usage_service().record_analysis("depreciacao")
            except Exception as analytics_error:
                current_app.logger.warning("Falha ao registrar métrica de depreciação: %s", analytics_error)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"encontrado": False, "erro": str(exc)}), 500


@depreciacao_bp.route("/calcular", methods=["POST"])
def calcular():
    # Decisão de arquitetura: Render não calcula histórico pesado nem fabrica curva.
    # Se não houver curva pronta, o site deve registrar/mostrar pendência e o painel local processa.
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.registrar_pendencia_calculo(payload)
    except Exception:
        resultado = {}
    return jsonify({
        "ok": False,
        "status": "pendente_processamento_local",
        "mensagem": "Curva não calculada no Render. Processe no painel local e envie/importa a curva pronta.",
        "pendencia": resultado,
    }), 200


@depreciacao_bp.route("/apagar_curva", methods=["POST"])
def apagar_curva():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.apagar_curva_manual(payload)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"ok": False, "mensagem": str(exc)}), 200


@depreciacao_bp.route("/importar_curvas", methods=["POST"])
@depreciacao_bp.route("/admin/importar_curvas", methods=["POST"])
def importar_curvas():
    if not _admin_token_valido():
        return jsonify({
            "ok": False,
            "erro": "Token administrativo inválido ou ausente.",
            "tipo": "nao_autorizado",
        }), 401
    payload = request.get_json(silent=True) or {}
    try:
        resultado = curvas_repository.importar_curvas_painel(payload)
        resultado["ok"] = True
        resultado.setdefault("mensagem", "Curvas importadas no Render a partir do painel local.")
        resultado["status_bases"] = depreciacao_service.status_bases()
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "erro": str(exc),
            "tipo": "erro_importacao_curvas",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 500


@depreciacao_bp.route("/sincronizar_snapshot", methods=["POST"])
@depreciacao_bp.route("/admin/sincronizar_snapshot", methods=["POST"])
def sincronizar_snapshot_curvas():
    if not _admin_token_valido():
        return jsonify({
            "ok": False,
            "erro": "Token administrativo inválido ou ausente.",
            "tipo": "nao_autorizado",
        }), 401
    payload = request.get_json(silent=True) or {}
    try:
        payload["modo"] = "snapshot_completo"
        resultado = curvas_repository.sincronizar_snapshot_painel(payload)
        resultado["ok"] = True
        resultado["status_bases"] = depreciacao_service.status_bases()
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "erro": str(exc),
            "tipo": "erro_sincronizacao_snapshot",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 500



@depreciacao_bp.route("/excluir_curvas", methods=["POST"])
@depreciacao_bp.route("/admin/excluir_curvas", methods=["POST"])
def excluir_curvas_admin():
    if not _admin_token_valido():
        return jsonify({
            "ok": False,
            "erro": "Token administrativo inválido ou ausente.",
            "tipo": "nao_autorizado",
        }), 401
    payload = request.get_json(silent=True) or {}
    try:
        resultado = curvas_repository.excluir_curvas_painel(payload)
        resultado["status_bases"] = depreciacao_service.status_bases()
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "erro": str(exc),
            "tipo": "erro_exclusao_curvas",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 500


@depreciacao_bp.route("/diagnostico_v1917", methods=["POST"])
def diagnostico_v1917():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = motor_v1917_adapter.diagnosticar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico_v1917",
            "mensagem": f"Erro interno no diagnóstico V19.17: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200


@depreciacao_bp.route("/diagnostico_v1917/continuar", methods=["POST"])
def diagnostico_v1917_continuar():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = motor_v1917_adapter.continuar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico_v1917",
            "mensagem": f"Erro interno ao continuar diagnóstico V19.17: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200


@depreciacao_bp.route("/diagnostico_v1917/status/<job_id>", methods=["GET"])
def diagnostico_v1917_status(job_id):
    try:
        resultado = motor_v1917_adapter.status(job_id)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_status_v1917",
            "mensagem": f"Erro interno ao consultar status V19.17: {type(exc).__name__}: {exc}",
        }), 200

@depreciacao_bp.route("/diagnostico_coorte", methods=["POST"])
def diagnostico_coorte():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = coorte_diagnostico_service.diagnosticar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico",
            "mensagem": f"Erro interno no diagnóstico: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200

@depreciacao_bp.route("/diagnostico", methods=["POST"])
def diagnostico_coorte_alias():
    return diagnostico_coorte()
