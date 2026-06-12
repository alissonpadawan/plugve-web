from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from services.fipe_service import FipeApiError, FipeService

fipe_bp = Blueprint("fipe", __name__)
fipe_service = FipeService()


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
        current_app.config.get("PLUGVE_SYNC_TOKEN", "")
        or current_app.config.get("PLUGVE_ADMIN_TOKEN", "")
        or ""
    ).strip()
    recebido = _admin_token_recebido()
    return bool(esperado) and bool(recebido) and hmac.compare_digest(recebido, esperado)


def _erro_fipe_response(exc: Exception, default_status: int = 500):
    if isinstance(exc, FipeApiError):
        status = exc.status_code or default_status
        if status < 400:
            status = default_status
        return jsonify(exc.to_dict()), status
    return jsonify({"erro": str(exc), "tipo": "erro_interno"}), default_status


@fipe_bp.route("/catalogo_estado")
@fipe_bp.route("/catalogo/status")
def catalogo_estado():
    """Estado consolidado da varredura FIPE para sincronização com o painel local."""
    if not _admin_token_valido():
        return jsonify({
            "ok": False,
            "erro": "Token de sincronização inválido ou ausente.",
            "tipo": "nao_autorizado",
        }), 401
    try:
        return jsonify(fipe_service.catalogo_estado())
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/marcas")
def marcas():
    try:
        return jsonify(fipe_service.listar_marcas())
    except Exception as exc:
        return _erro_fipe_response(exc)


@fipe_bp.route("/modelos")
def modelos():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    if not codigo_marca:
        return jsonify({"modelos": []})
    try:
        return jsonify(fipe_service.listar_modelos(codigo_marca))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["modelos"] = []
        return jsonify(data), status


@fipe_bp.route("/anos")
def anos():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    codigo_modelo = request.args.get("codigo_modelo", "").strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify([])
    try:
        return jsonify(fipe_service.listar_anos(codigo_marca, codigo_modelo))
    except Exception as exc:
        return _erro_fipe_response(exc)


@fipe_bp.route("/bloquear_modelo", methods=["POST"])
def bloquear_modelo():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    codigo_modelo = str(payload.get("codigo_modelo", "")).strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.bloquear_modelo_antigo(
            codigo_marca=codigo_marca,
            codigo_modelo=codigo_modelo,
            nome_marca=str(payload.get("marca", "")).strip(),
            nome_modelo=str(payload.get("modelo", "")).strip(),
            motivo=str(payload.get("motivo", "sem_ano_2012_ou_zero_km")).strip(),
        ))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/marcar_zero_km", methods=["POST"])
def marcar_zero_km():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    codigo_modelo = str(payload.get("codigo_modelo", "")).strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.marcar_modelo_zero_km(
            codigo_marca=codigo_marca,
            codigo_modelo=codigo_modelo,
            nome_marca=str(payload.get("marca", "")).strip(),
            nome_modelo=str(payload.get("modelo", "")).strip(),
        ))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/desmarcar_zero_km", methods=["POST"])
def desmarcar_zero_km():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    codigo_modelo = str(payload.get("codigo_modelo", "")).strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.desmarcar_modelo_zero_km(
            codigo_marca=codigo_marca,
            codigo_modelo=codigo_modelo,
        ))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/marcar_marca_varrida", methods=["POST"])
def marcar_marca_varrida():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    if not codigo_marca:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.marcar_marca_varrida(
            codigo_marca=codigo_marca,
            nome_marca=str(payload.get("marca", "")).strip(),
            modelos_validos=int(payload.get("modelos_validos", 0) or 0),
            modelos_bloqueados=int(payload.get("modelos_bloqueados", 0) or 0),
        ))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/bloquear_marca", methods=["POST"])
def bloquear_marca():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    if not codigo_marca:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.bloquear_marca_antiga(
            codigo_marca=codigo_marca,
            nome_marca=str(payload.get("marca", "")).strip(),
            motivo=str(payload.get("motivo", "sem_modelos_2012_ou_zero_km")).strip(),
        ))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/desbloquear_marca", methods=["POST"])
def desbloquear_marca():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    if not codigo_marca:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.desbloquear_marca(codigo_marca))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/usage")
def usage():
    try:
        return jsonify(fipe_service.uso_requisicoes())
    except Exception as exc:
        return _erro_fipe_response(exc)


@fipe_bp.route("/varredura_status")
def varredura_status():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    if not codigo_marca:
        return jsonify({})
    try:
        return jsonify(fipe_service.obter_progresso_varredura(codigo_marca))
    except Exception as exc:
        return _erro_fipe_response(exc)


@fipe_bp.route("/salvar_varredura", methods=["POST"])
def salvar_varredura():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    if not codigo_marca:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.registrar_progresso_varredura(codigo_marca, payload))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/limpar_varredura", methods=["POST"])
def limpar_varredura():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    if not codigo_marca:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.limpar_progresso_varredura(codigo_marca))
    except Exception as exc:
        resp, status = _erro_fipe_response(exc)
        data = resp.get_json() or {}
        data["ok"] = False
        return jsonify(data), status


@fipe_bp.route("/preco")
def preco():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    codigo_modelo = request.args.get("codigo_modelo", "").strip()
    codigo_ano = request.args.get("codigo_ano", "").strip()
    if not codigo_marca or not codigo_modelo or not codigo_ano:
        return jsonify({"erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.consultar_preco(codigo_marca, codigo_modelo, codigo_ano))
    except Exception as exc:
        return _erro_fipe_response(exc)
