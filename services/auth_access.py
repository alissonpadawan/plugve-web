from __future__ import annotations

from typing import Any

from flask import current_app, g, jsonify, redirect, request, session, url_for

from services.auth_security import safe_next_path
from services.auth_service import get_auth_service


PUBLIC_ENDPOINTS = {
    "main.index",
    "main.health",
    "auth.login",
    "auth.register",
    "auth.verify_email",
    "auth.resend_verification",
    "auth.pending_approval",
    "auth.forgot_password",
    "auth.reset_password",
    "auth.privacy",
    "auth.terms",
    "auth.logout",
}

# Essas rotas continuam protegidas pelo token técnico que já existe nelas.
TECHNICAL_ENDPOINTS = {
    "depreciacao.importar_curvas",
    "depreciacao.sincronizar_snapshot_curvas",
    "depreciacao.excluir_curvas_admin",
    "fipe.catalogo_estado",
    "site_usage.admin_dashboard",
    "site_usage.admin_telemetry_summary",
    "site_usage.admin_telemetry_events",
    "site_usage.admin_telemetry_event_detail",
    "site_usage.admin_telemetry_visitors",
    "site_usage.admin_update_curve_request",
    "access_admin.list_access_requests",
    "access_admin.list_access_users",
    "access_admin.access_user_detail",
    "access_admin.approve_access",
    "access_admin.reject_access",
    "access_admin.suspend_access",
    "access_admin.reactivate_access",
    "access_admin.resend_access_notification",
    "tco.sobre_admin_comments",
    "tco.sobre_admin_official_reply",
    "tco.sobre_admin_delete_comment",
    "tco.contato_admin_messages",
    "tco.contato_admin_message",
}

TELEMETRY_SESSION_KEYS = (
    "site_usage_visitor_id",
    "site_usage_session_id",
    "site_usage_last_active_ts",
)


def endpoint_is_public(endpoint: str | None = None) -> bool:
    name = str(endpoint if endpoint is not None else request.endpoint or "")
    return name == "static" or name in PUBLIC_ENDPOINTS


def endpoint_is_technical(endpoint: str | None = None) -> bool:
    name = str(endpoint if endpoint is not None else request.endpoint or "")
    return name in TECHNICAL_ENDPOINTS


def endpoint_requires_user(endpoint: str | None = None) -> bool:
    return not endpoint_is_public(endpoint) and not endpoint_is_technical(endpoint)


def access_control_enabled() -> bool:
    enabled = bool(current_app.config.get("AUTH_ACCESS_CONTROL_ENABLED", False))
    if current_app.testing and not bool(current_app.config.get("AUTH_ENFORCE_IN_TESTS", False)):
        return False
    return enabled


def _preserve_telemetry_values() -> dict[str, Any]:
    return {key: session.get(key) for key in TELEMETRY_SESSION_KEYS if session.get(key) is not None}


def rotate_session_with_auth_token(auth_token: str) -> None:
    preserved = _preserve_telemetry_values()
    session.clear()
    session.update(preserved)
    session["auth_session_token"] = auth_token
    session.permanent = True
    g._curve_auth_user = None


def clear_auth_session(*, revoke: bool = True) -> None:
    token = str(session.get("auth_session_token") or "")
    if revoke and token:
        try:
            get_auth_service().revoke_session(token)
        except Exception as exc:
            current_app.logger.debug("Falha ao revogar sessão de autenticação: %s", exc)
    preserved = _preserve_telemetry_values()
    session.clear()
    session.update(preserved)
    session.permanent = True
    g._curve_auth_user = None


def current_auth_user() -> dict[str, Any] | None:
    if hasattr(g, "_curve_auth_user"):
        return g._curve_auth_user
    token = str(session.get("auth_session_token") or "")
    if not token:
        g._curve_auth_user = None
        return None
    try:
        result = get_auth_service().current_session_user(token)
    except Exception as exc:
        current_app.logger.warning("Falha ao validar sessão autenticada: %s", exc)
        g._curve_auth_user = None
        return None
    if not result:
        session.pop("auth_session_token", None)
        g._curve_auth_user = None
        return None
    _, user = result
    g._curve_auth_user = user
    return user


def is_active_user() -> bool:
    user = current_auth_user()
    return bool(user and str(user.get("access_status") or "") == "active")


def enforce_auth_access():
    if not access_control_enabled():
        return None
    endpoint = str(request.endpoint or "")
    if endpoint_is_public(endpoint) or endpoint_is_technical(endpoint):
        return None

    user = current_auth_user()
    if user and str(user.get("access_status") or "") == "active":
        return None

    if user:
        reason = str(user.get("access_status") or "inactive")
        clear_auth_session(revoke=True)
    else:
        reason = "login_required"

    next_path = safe_next_path(request.full_path.rstrip("?") or request.path)
    if request.path.startswith("/api/"):
        authenticated_but_inactive = reason != "login_required"
        response = jsonify({
            "ok": False,
            "error": "Conta sem acesso ativo." if authenticated_but_inactive else "Autenticação necessária.",
            "reason": reason,
            "login_url": url_for("auth.login", next=next_path, reason=reason),
        })
        response.status_code = 403 if authenticated_but_inactive else 401
        response.headers["Cache-Control"] = "no-store"
        return response
    return redirect(url_for("auth.login", next=next_path, reason=reason))
