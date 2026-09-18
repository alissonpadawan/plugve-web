from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from services.auth_admin_service import get_auth_admin_service
from services.auth_security import AuthValidationError


access_admin_bp = Blueprint("access_admin", __name__)


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
    response = jsonify({"ok": False, "error": "Acesso administrativo não autorizado."})
    response.status_code = 401
    response.headers["Cache-Control"] = "no-store"
    return response


def _response(payload: dict, status: int = 200):
    response = jsonify({"ok": True, **payload})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _error(exc: AuthValidationError):
    response = jsonify({"ok": False, "error": str(exc)})
    response.status_code = int(getattr(exc, "status_code", 400) or 400)
    response.headers["Cache-Control"] = "no-store"
    return response


@access_admin_bp.route("/api/access/admin/requests", methods=["GET"])
def list_access_requests():
    if not _admin_token_valid():
        return _unauthorized()
    try:
        page = get_auth_admin_service().list_users(
            status="pending_approval",
            query=str(request.args.get("q") or ""),
            profile_type=str(request.args.get("profile") or ""),
            institution=str(request.args.get("institution") or ""),
            offset=int(request.args.get("offset", 0) or 0),
            limit=int(request.args.get("limit", 200) or 200),
        )
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Paginação inválida."}), 400
    return _response(page)


@access_admin_bp.route("/api/access/admin/users", methods=["GET"])
def list_access_users():
    if not _admin_token_valid():
        return _unauthorized()
    try:
        page = get_auth_admin_service().list_users(
            status=str(request.args.get("status") or "all"),
            query=str(request.args.get("q") or ""),
            profile_type=str(request.args.get("profile") or ""),
            institution=str(request.args.get("institution") or ""),
            offset=int(request.args.get("offset", 0) or 0),
            limit=int(request.args.get("limit", 200) or 200),
        )
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Paginação inválida."}), 400
    return _response(page)


@access_admin_bp.route("/api/access/admin/users/<public_id>", methods=["GET"])
def access_user_detail(public_id: str):
    if not _admin_token_valid():
        return _unauthorized()
    try:
        detail = get_auth_admin_service().get_user_detail(public_id)
    except AuthValidationError as exc:
        return _error(exc)
    return _response(detail)


def _action(public_id: str, method_name: str):
    if not _admin_token_valid():
        return _unauthorized()
    payload = request.get_json(silent=True) or {}
    try:
        service = get_auth_admin_service()
        result = getattr(service, method_name)(public_id, note=str(payload.get("note") or ""))
    except AuthValidationError as exc:
        return _error(exc)
    return _response(result)


@access_admin_bp.route("/api/access/admin/users/<public_id>/approve", methods=["POST"])
def approve_access(public_id: str):
    return _action(public_id, "approve")


@access_admin_bp.route("/api/access/admin/users/<public_id>/reject", methods=["POST"])
def reject_access(public_id: str):
    return _action(public_id, "reject")


@access_admin_bp.route("/api/access/admin/users/<public_id>/suspend", methods=["POST"])
def suspend_access(public_id: str):
    return _action(public_id, "suspend")


@access_admin_bp.route("/api/access/admin/users/<public_id>/reactivate", methods=["POST"])
def reactivate_access(public_id: str):
    return _action(public_id, "reactivate")


@access_admin_bp.route("/api/access/admin/users/<public_id>/resend-notification", methods=["POST"])
def resend_access_notification(public_id: str):
    if not _admin_token_valid():
        return _unauthorized()
    try:
        result = get_auth_admin_service().resend_notification(public_id)
    except AuthValidationError as exc:
        return _error(exc)
    return _response(result)
