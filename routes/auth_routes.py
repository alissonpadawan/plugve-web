from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from services.auth_access import clear_auth_session, current_auth_user, rotate_session_with_auth_token
from services.auth_email_service import AuthEmailDeliveryError
from services.auth_security import (
    AuthValidationError,
    ensure_auth_csrf_token,
    safe_next_path,
    validate_auth_csrf_token,
)
from services.auth_service import PROFILE_TYPES, get_auth_service
from services.site_usage_tracking import record_current_usage_event


auth_bp = Blueprint("auth", __name__)


def _client_key() -> str:
    forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    address = (
        str(request.headers.get("CF-Connecting-IP") or "").strip()
        or forwarded
        or str(request.remote_addr or "").strip()
        or "unknown"
    )
    agent = str(request.headers.get("User-Agent") or "")[:160]
    return f"{address}|{agent}"


def _csrf() -> str:
    return ensure_auth_csrf_token()


def _pending_user():
    public_id = str(session.get("auth_pending_public_id") or "").strip()
    if not public_id:
        return None
    return get_auth_service().repo.get_user_by_public_id(public_id)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    existing = current_auth_user()
    if existing and str(existing.get("access_status") or "") == "active":
        return redirect(safe_next_path(request.args.get("next"), fallback=url_for("main.index")))

    next_path = safe_next_path(request.values.get("next"), fallback=url_for("main.index"))
    reason = str(request.args.get("reason") or "").strip()
    error = ""
    if request.method == "POST":
        try:
            validate_auth_csrf_token(request.form.get("csrf_token"))
            result = get_auth_service().login(
                request.form.get("email"), request.form.get("password"), client_key=_client_key()
            )
            if result.ok:
                session.pop("auth_pending_public_id", None)
                rotate_session_with_auth_token(result.session_token)
                try:
                    record_current_usage_event(
                        event_type="auth", module="auth", action="login",
                        metadata={"access_status": "active"},
                        user_id=str((result.user or {}).get("public_id") or ""),
                    )
                except Exception:
                    pass
                flash("Acesso realizado com sucesso.", "success")
                return redirect(next_path)
            error = result.message
            if result.user and result.status in {"email_pending", "pending_approval"}:
                session["auth_pending_public_id"] = str(result.user.get("public_id") or "")
            else:
                session.pop("auth_pending_public_id", None)
            if result.status == "email_pending":
                flash(result.message, "info")
                return redirect(url_for("auth.verify_email"))
            if result.status == "pending_approval":
                return redirect(url_for("auth.pending_approval"))
        except AuthValidationError as exc:
            error = str(exc)
    return render_template(
        "auth/login.html",
        csrf_token=_csrf(),
        next_path=next_path,
        error=error,
        reason=reason,
    )


@auth_bp.route("/solicitar-acesso", methods=["GET", "POST"])
def register():
    error = ""
    values = {}
    if request.method == "POST":
        # Nunca devolve senha/confirmacao ao contexto do template em caso de erro.
        values = {
            key: request.form.get(key, "")
            for key in ("full_name", "email", "profile_type", "institution", "course_area", "purpose")
        }
        values["privacy_accepted"] = request.form.get("privacy_accepted") == "1"
        try:
            validate_auth_csrf_token(request.form.get("csrf_token"))
            if str(request.form.get("website") or "").strip():
                raise AuthValidationError("Não foi possível processar a solicitação.")
            user, delivery_ok = get_auth_service().register(
                {
                    **values,
                    "password": request.form.get("password"),
                    "password_confirm": request.form.get("password_confirm"),
                },
                client_key=_client_key(),
            )
            session["auth_pending_public_id"] = str(user["public_id"])
            if delivery_ok:
                flash("Cadastro criado. Enviamos um código de confirmação para seu e-mail.", "success")
            else:
                flash(
                    "Cadastro criado, mas o e-mail de confirmação não pôde ser enviado agora. Use 'Reenviar código'.",
                    "warning",
                )
            return redirect(url_for("auth.verify_email"))
        except AuthValidationError as exc:
            error = str(exc)
    return render_template(
        "auth/register.html",
        csrf_token=_csrf(),
        error=error,
        values=values,
        profile_types=PROFILE_TYPES,
        minimum_password=int(current_app.config.get("AUTH_PASSWORD_MIN_LENGTH", 10)),
    )


@auth_bp.route("/confirmar-email", methods=["GET", "POST"])
def verify_email():
    user = _pending_user()
    status = str(user.get("access_status") or "") if user else ""
    if status == "pending_approval":
        return redirect(url_for("auth.pending_approval"))
    if user and status != "email_pending":
        session.pop("auth_pending_public_id", None)
        user = None
    error = ""
    if request.method == "POST":
        try:
            validate_auth_csrf_token(request.form.get("csrf_token"))
            if not user:
                raise AuthValidationError("Faça login novamente para retomar a confirmação do e-mail.")
            get_auth_service().verify_email(
                str(user["public_id"]), request.form.get("code"), client_key=_client_key()
            )
            flash("E-mail confirmado. Sua solicitação está aguardando aprovação.", "success")
            return redirect(url_for("auth.pending_approval"))
        except AuthValidationError as exc:
            error = str(exc)
    email_masked = ""
    if user:
        email = str(user.get("email_normalized") or "")
        if "@" in email:
            local, domain = email.split("@", 1)
            email_masked = (local[:2] + "***" if len(local) > 2 else "***") + "@" + domain
    return render_template(
        "auth/verify_email.html",
        csrf_token=_csrf(),
        error=error,
        has_pending=bool(user),
        email_masked=email_masked,
    )


@auth_bp.route("/reenviar-codigo", methods=["POST"])
def resend_verification():
    try:
        validate_auth_csrf_token(request.form.get("csrf_token"))
        user = _pending_user()
        if not user:
            raise AuthValidationError("Faça login novamente para retomar a confirmação do e-mail.")
        sent = get_auth_service().resend_verification(str(user["public_id"]), client_key=_client_key())
        if sent:
            flash("Novo código enviado.", "success")
        else:
            flash("Não há confirmação de e-mail pendente para esta conta.", "info")
    except (AuthValidationError, AuthEmailDeliveryError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("auth.verify_email"))


@auth_bp.route("/aguardando-aprovacao", methods=["GET"])
def pending_approval():
    user = _pending_user()
    status = str((user or {}).get("access_status") or "")
    if status == "email_pending":
        return redirect(url_for("auth.verify_email"))
    if status == "active":
        session.pop("auth_pending_public_id", None)
        flash("Seu acesso foi aprovado. Entre com seu e-mail e senha.", "success")
        return redirect(url_for("auth.login"))
    if status in {"rejected", "suspended", "disabled"}:
        session.pop("auth_pending_public_id", None)
        messages = {
            "rejected": "Sua solicitação de acesso não foi aprovada neste momento.",
            "suspended": "Seu acesso está suspenso.",
            "disabled": "Esta conta está desativada.",
        }
        flash(messages[status], "info" if status == "rejected" else "error")
        return redirect(url_for("auth.login", reason=status))
    return render_template(
        "auth/pending_approval.html",
        user=user if status == "pending_approval" else None,
    )


@auth_bp.route("/esqueci-minha-senha", methods=["GET", "POST"])
def forgot_password():
    error = ""
    sent = False
    if request.method == "POST":
        try:
            validate_auth_csrf_token(request.form.get("csrf_token"))
            get_auth_service().request_password_reset(
                request.form.get("email"), client_key=_client_key()
            )
            sent = True
        except AuthValidationError as exc:
            error = str(exc)
        if sent:
            flash(
                "Se houver uma conta associada a este e-mail, enviaremos instruções de redefinição.",
                "info",
            )
            return redirect(url_for("auth.reset_password"))
    return render_template("auth/forgot_password.html", csrf_token=_csrf(), error=error)


@auth_bp.route("/redefinir-senha", methods=["GET", "POST"])
def reset_password():
    error = ""
    if request.method == "POST":
        try:
            validate_auth_csrf_token(request.form.get("csrf_token"))
            get_auth_service().reset_password(
                request.form.get("email"),
                request.form.get("code"),
                request.form.get("password"),
                request.form.get("password_confirm"),
                client_key=_client_key(),
            )
            flash("Senha redefinida. Você já pode entrar com a nova senha.", "success")
            return redirect(url_for("auth.login"))
        except AuthValidationError as exc:
            error = str(exc)
    return render_template(
        "auth/reset_password.html",
        csrf_token=_csrf(),
        error=error,
        minimum_password=int(current_app.config.get("AUTH_PASSWORD_MIN_LENGTH", 10)),
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    try:
        validate_auth_csrf_token(request.form.get("csrf_token"))
    except AuthValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.index"))
    try:
        auth_user = current_auth_user()
        record_current_usage_event(
            event_type="auth", module="auth", action="logout",
            user_id=str((auth_user or {}).get("public_id") or ""),
        )
    except Exception:
        pass
    clear_auth_session(revoke=True)
    flash("Sessão encerrada.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/privacidade", methods=["GET"])
def privacy():
    return render_template("auth/privacy.html")


@auth_bp.route("/termos", methods=["GET"])
def terms():
    return render_template("auth/terms.html")
