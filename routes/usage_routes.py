from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request, session

from services.site_usage_service import (
    SiteUsageValidationError,
    get_site_usage_service,
)

usage_bp = Blueprint("site_usage", __name__)


def _admin_token_received() -> str:
    for header in ("X-PlugVE-Admin-Token", "X-PlugVE-Sync-Token"):
        value = request.headers.get(header, "").strip()
        if value:
            return value
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _admin_token_valid() -> bool:
    expected = str(
        current_app.config.get("PLUGVE_ADMIN_TOKEN", "")
        or current_app.config.get("PLUGVE_SYNC_TOKEN", "")
        or ""
    ).strip()
    received = _admin_token_received()
    return bool(expected and received and hmac.compare_digest(expected, received))


def _unauthorized():
    return jsonify({"ok": False, "error": "Acesso administrativo não autorizado."}), 401


def _validate_csrf(payload: dict | None = None) -> None:
    expected = str(session.get("site_usage_csrf_token") or "")
    supplied = str(
        request.headers.get("X-CSRF-Token")
        or (payload or {}).get("csrf_token")
        or ""
    )
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise SiteUsageValidationError(
            "Sessão inválida. Atualize a página e tente novamente.", 403
        )


@usage_bp.route("/api/site-usage/analysis", methods=["POST"])
def record_public_analysis():
    payload = request.get_json(silent=True) or {}
    try:
        _validate_csrf(payload)
        analysis_type = str(payload.get("type") or "").strip().lower()
        if analysis_type != "fipe_plus":
            raise SiteUsageValidationError("Tipo de análise não autorizado.")
        counts = get_site_usage_service().record_analysis(analysis_type)
    except SiteUsageValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True, "total": counts.get("total", 0)})


@usage_bp.route("/api/site-usage/curve-requests", methods=["POST"])
def submit_curve_request():
    payload = request.get_json(silent=True) or {}
    try:
        _validate_csrf(payload)
        result = get_site_usage_service().submit_curve_request(
            visitor_id=str(session.get("site_usage_visitor_id") or ""),
            payload=payload,
        )
    except SiteUsageValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True, **result}), 201


@usage_bp.route("/api/site-usage/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if not _admin_token_valid():
        return _unauthorized()
    status = str(request.args.get("status", "all") or "all")
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = max(1, int(request.args.get("limit", 500)))
        service = get_site_usage_service()
        requests_page = service.list_curve_requests(status=status, offset=offset, limit=limit)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Paginação inválida."}), 400
    except SiteUsageValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    response = jsonify({
        "ok": True,
        "metrics": service.get_analysis_counts(),
        **requests_page,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@usage_bp.route("/api/site-usage/admin/curve-requests/<int:request_id>", methods=["PATCH"])
def admin_update_curve_request(request_id: int):
    if not _admin_token_valid():
        return _unauthorized()
    payload = request.get_json(silent=True) or {}
    try:
        item = get_site_usage_service().update_curve_request_status(
            request_id, payload.get("status")
        )
    except SiteUsageValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    if item is None:
        return jsonify({"ok": False, "error": "Solicitação não encontrada."}), 404
    response = jsonify({"ok": True, "request": item})
    response.headers["Cache-Control"] = "no-store"
    return response
