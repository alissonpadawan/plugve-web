from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, render_template, request, session

from services.site_usage_service import (
    SiteUsageValidationError,
    get_site_usage_service,
)
from services.site_usage_tracking import record_current_usage_event

usage_bp = Blueprint("site_usage", __name__)


@usage_bp.route("/admin/uso", methods=["GET"])
def admin_usage_page():
    # A página não recebe nem persiste o token no servidor. Os dados permanecem
    # protegidos pelas APIs administrativas, e o navegador envia o token apenas
    # no cabeçalho das requisições após o administrador informá-lo.
    response = current_app.make_response(render_template("admin_usage.html"))
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _admin_token_received() -> str:
    value = request.headers.get("X-PlugVE-Admin-Token", "").strip()
    if value:
        return value
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _admin_token_valid() -> bool:
    expected = str(current_app.config.get("PLUGVE_ADMIN_TOKEN", "") or "").strip()
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


@usage_bp.route("/api/site-usage/event", methods=["POST"])
def record_public_event():
    payload = request.get_json(silent=True) or {}
    try:
        _validate_csrf(payload)
        module = str(payload.get("module") or "").strip().lower()
        action = str(payload.get("action") or "").strip().lower()
        allowed = {
            ("fipe_plus", "consultation_completed"),
            ("fipe_plus", "pdf_exported"),
            ("tco", "pdf_exported"),
            ("depreciacao", "pdf_exported"),
        }
        if (module, action) not in allowed:
            raise SiteUsageValidationError("Evento público não autorizado.")
        analysis_type = "fipe_plus" if (module, action) == ("fipe_plus", "consultation_completed") else ""
        event_id = record_current_usage_event(
            event_type="analysis" if analysis_type else "export",
            module=module,
            action=action,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            vehicles=payload.get("vehicles") if isinstance(payload.get("vehicles"), list) else [],
            analysis_type=analysis_type,
        )
        if event_id is None:
            raise SiteUsageValidationError("Não foi possível registrar o evento.", 500)
    except SiteUsageValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status_code
    return jsonify({"ok": True}), 201


@usage_bp.route("/api/site-usage/curve-requests", methods=["POST"])
def submit_curve_request():
    payload = request.get_json(silent=True) or {}
    try:
        _validate_csrf(payload)
        result = get_site_usage_service().submit_curve_request(
            visitor_id=str(session.get("site_usage_visitor_id") or ""),
            payload=payload,
        )
        record_current_usage_event(
            event_type="interaction",
            module=str(payload.get("usage_context") or payload.get("origem") or "depreciacao").strip().lower().replace("+", "_")[:40] or "depreciacao",
            action="curve_requested",
            metadata={"already_requested": bool(result.get("already_requested"))},
            vehicles=[payload],
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
        "telemetry": service.telemetry_summary(
            start=str(request.args.get("start") or ""),
            end=str(request.args.get("end") or ""),
        ),
        **requests_page,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@usage_bp.route("/api/site-usage/admin/telemetry/summary", methods=["GET"])
def admin_telemetry_summary():
    if not _admin_token_valid():
        return _unauthorized()
    service = get_site_usage_service()
    try:
        tz_offset_minutes = int(request.args.get("tz_offset_minutes", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Fuso horário inválido."}), 400
    response = jsonify({
        "ok": True,
        **service.telemetry_summary(
            start=str(request.args.get("start") or ""),
            end=str(request.args.get("end") or ""),
            tz_offset_minutes=tz_offset_minutes,
        ),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@usage_bp.route("/api/site-usage/admin/telemetry/events", methods=["GET"])
def admin_telemetry_events():
    if not _admin_token_valid():
        return _unauthorized()
    try:
        page = get_site_usage_service().list_events(
            start=str(request.args.get("start") or ""),
            end=str(request.args.get("end") or ""),
            module=str(request.args.get("module") or ""),
            visitor=str(request.args.get("visitor") or ""),
            offset=int(request.args.get("offset", 0)),
            limit=int(request.args.get("limit", 200)),
        )
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Paginação inválida."}), 400
    response = jsonify({"ok": True, **page})
    response.headers["Cache-Control"] = "no-store"
    return response


@usage_bp.route("/api/site-usage/admin/telemetry/visitors", methods=["GET"])
def admin_telemetry_visitors():
    if not _admin_token_valid():
        return _unauthorized()
    try:
        page = get_site_usage_service().list_visitors(
            start=str(request.args.get("start") or ""),
            end=str(request.args.get("end") or ""),
            offset=int(request.args.get("offset", 0)),
            limit=int(request.args.get("limit", 200)),
        )
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Paginação inválida."}), 400
    response = jsonify({"ok": True, **page})
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
