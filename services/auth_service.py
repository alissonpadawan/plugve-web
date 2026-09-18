from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from flask import current_app

from services.auth_email_service import (
    AuthEmailDeliveryError,
    send_password_reset_code,
    send_verification_code,
)
from services.auth_repository import AuthRepository, parse_iso_utc, utc_now
from services.auth_security import (
    AuthValidationError,
    challenge_digest,
    clean_single_line,
    constant_time_equal,
    generate_numeric_code,
    generate_session_token,
    hash_password,
    normalize_email,
    session_token_digest,
    subject_digest,
    validate_email,
    validate_password,
    verify_password,
)


PROFILE_TYPES = {
    "aluno_ifg": "Aluno do IFG",
    "professor_ifg": "Professor do IFG",
    "servidor_ifg": "Servidor do IFG",
    "aluno_outra": "Aluno de outra instituição",
    "pesquisador_outra": "Professor/Pesquisador de outra instituição",
    "empresa": "Empresa",
    "profissional": "Profissional",
    "outro": "Outro",
}

ACCESS_STATUSES = {
    "email_pending",
    "pending_approval",
    "active",
    "rejected",
    "suspended",
    "disabled",
}

DUMMY_PASSWORD_HASH = hash_password("curve-auth-dummy-password-never-used")


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    status: str
    user: dict[str, Any] | None = None
    session_token: str = ""
    message: str = ""


class AuthService:
    def __init__(self, database_path: str, secret_key: str, config: Mapping[str, Any]):
        self.repo = AuthRepository(database_path)
        self.secret_key = str(secret_key)
        self.config = config

    def _rate(self, scope: str, subject: str, *, window: int, limit: int) -> None:
        digest = subject_digest(self.secret_key, subject)
        allowed, retry = self.repo.rate_limit_hit(
            scope=scope,
            subject_hash=digest,
            window_seconds=int(window),
            max_events=int(limit),
        )
        if not allowed:
            raise AuthValidationError(
                f"Muitas tentativas. Aguarde {retry} segundos e tente novamente.", 429
            )

    def _create_challenge(self, user: dict[str, Any], purpose: str) -> str:
        code = generate_numeric_code(6)
        self.repo.invalidate_challenges(int(user["id"]), purpose)
        self.repo.create_challenge(
            user_id=int(user["id"]),
            purpose=purpose,
            token_hash=challenge_digest(
                self.secret_key,
                user_public_id=str(user["public_id"]),
                purpose=purpose,
                code=code,
            ),
            ttl_seconds=int(self.config.get("AUTH_CODE_TTL_SECONDS", 900)),
            max_attempts=int(self.config.get("AUTH_CODE_MAX_ATTEMPTS", 5)),
        )
        return code

    def _send_verification(self, user: dict[str, Any], code: str) -> None:
        send_verification_code(
            recipient=str(user["email_normalized"]),
            full_name=str(user["full_name"]),
            code=code,
            ttl_minutes=max(1, int(self.config.get("AUTH_CODE_TTL_SECONDS", 900)) // 60),
            config=self.config,
        )

    def register(self, payload: Mapping[str, Any], *, client_key: str) -> tuple[dict[str, Any], bool]:
        self._rate(
            "register",
            client_key,
            window=int(self.config.get("AUTH_RATE_REGISTER_WINDOW_SECONDS", 3600)),
            limit=int(self.config.get("AUTH_RATE_REGISTER_MAX", 5)),
        )
        full_name = clean_single_line(payload.get("full_name"), field="Nome completo", max_length=120)
        if len(full_name) < 3:
            raise AuthValidationError("Informe seu nome completo.")
        email = validate_email(payload.get("email"))
        password = validate_password(
            payload.get("password"), minimum_length=int(self.config.get("AUTH_PASSWORD_MIN_LENGTH", 10))
        )
        if password != str(payload.get("password_confirm") or ""):
            raise AuthValidationError("As senhas informadas não conferem.")
        profile_type = str(payload.get("profile_type") or "").strip()
        if profile_type not in PROFILE_TYPES:
            raise AuthValidationError("Selecione um perfil válido.")
        institution = clean_single_line(payload.get("institution"), field="Instituição / empresa", max_length=160, required=False)
        course_area = clean_single_line(payload.get("course_area"), field="Curso / área", max_length=160, required=False)
        purpose = clean_single_line(payload.get("purpose"), field="Finalidade de uso", max_length=300)
        if not bool(payload.get("privacy_accepted")):
            raise AuthValidationError("É necessário aceitar a Política de Privacidade para solicitar acesso.")
        if self.repo.get_user_by_email(email) is not None:
            raise AuthValidationError("Já existe uma solicitação ou conta associada a este e-mail.", 409)

        try:
            user = self.repo.create_user(
                public_id=str(uuid.uuid4()),
                full_name=full_name,
                email_normalized=email,
                password_hash=hash_password(password),
                profile_type=profile_type,
                institution=institution,
                course_area=course_area,
                purpose=purpose,
                access_status="email_pending",
                privacy_version=str(self.config.get("AUTH_PRIVACY_VERSION", "2026-09")),
            )
        except sqlite3.IntegrityError as exc:
            raise AuthValidationError("Já existe uma solicitação ou conta associada a este e-mail.", 409) from exc

        self.repo.audit(user_id=int(user["id"]), action="registration_created", metadata={"profile_type": profile_type})
        code = self._create_challenge(user, "email_verification")
        delivery_ok = True
        try:
            self._send_verification(user, code)
        except AuthEmailDeliveryError:
            delivery_ok = False
            self.repo.audit(user_id=int(user["id"]), action="verification_email_failed")
        else:
            self.repo.audit(user_id=int(user["id"]), action="verification_email_sent")
        return user, delivery_ok

    def resend_verification(self, public_id: str, *, client_key: str) -> bool:
        user = self.repo.get_user_by_public_id(public_id)
        if not user or user.get("access_status") != "email_pending":
            return False
        cooldown = int(self.config.get("AUTH_CODE_RESEND_COOLDOWN_SECONDS", 60))
        latest = self.repo.latest_challenge(int(user["id"]), "email_verification")
        if latest:
            created = parse_iso_utc(str(latest.get("created_at") or ""))
            if created is not None:
                elapsed = (utc_now() - created).total_seconds()
                if elapsed < cooldown:
                    raise AuthValidationError(
                        f"Aguarde {max(1, int(cooldown - elapsed))} segundos antes de reenviar o código.", 429
                    )
        self._rate(
            "verification_resend",
            f"{client_key}|{public_id}",
            window=cooldown,
            limit=1,
        )
        code = self._create_challenge(user, "email_verification")
        self._send_verification(user, code)
        self.repo.audit(user_id=int(user["id"]), action="verification_email_resent")
        return True

    def _validate_challenge(self, user: dict[str, Any], purpose: str, code: object, *, client_key: str) -> None:
        self._rate(
            f"challenge:{purpose}",
            f"{client_key}|{user['public_id']}",
            window=int(self.config.get("AUTH_RATE_VERIFY_WINDOW_SECONDS", 900)),
            limit=int(self.config.get("AUTH_RATE_VERIFY_MAX", 10)),
        )
        challenge = self.repo.latest_challenge(int(user["id"]), purpose)
        if not challenge:
            raise AuthValidationError("Código inexistente ou já utilizado. Solicite um novo código.")
        expires = parse_iso_utc(str(challenge.get("expires_at") or ""))
        if expires is None or expires <= utc_now():
            self.repo.invalidate_challenge(int(challenge["id"]))
            raise AuthValidationError("Este código expirou. Solicite um novo código.")
        if int(challenge.get("attempts") or 0) >= int(challenge.get("max_attempts") or 5):
            self.repo.invalidate_challenge(int(challenge["id"]))
            raise AuthValidationError("Número máximo de tentativas atingido. Solicite um novo código.", 429)
        digest = challenge_digest(
            self.secret_key,
            user_public_id=str(user["public_id"]),
            purpose=purpose,
            code=str(code or "").strip(),
        )
        if not constant_time_equal(str(challenge["token_hash"]), digest):
            updated = self.repo.increment_challenge_attempt(int(challenge["id"]))
            if int(updated.get("attempts") or 0) >= int(updated.get("max_attempts") or 5):
                self.repo.invalidate_challenge(int(challenge["id"]))
            raise AuthValidationError("Código inválido.")
        if not self.repo.consume_challenge(int(challenge["id"])):
            raise AuthValidationError("Código inválido, expirado ou já utilizado.")

    def verify_email(self, public_id: str, code: object, *, client_key: str) -> dict[str, Any]:
        user = self.repo.get_user_by_public_id(public_id)
        if not user:
            raise AuthValidationError("Solicitação não localizada.", 404)
        if user.get("access_status") == "pending_approval" and user.get("email_verified_at"):
            return user
        if user.get("access_status") != "email_pending":
            raise AuthValidationError("Esta conta não está aguardando confirmação de e-mail.")
        self._validate_challenge(user, "email_verification", code, client_key=client_key)
        user = self.repo.set_email_verified(int(user["id"]))
        self.repo.invalidate_challenges(int(user["id"]), "email_verification")
        self.repo.audit(user_id=int(user["id"]), action="email_verified")
        return user

    def login(self, email_value: object, password_value: object, *, client_key: str) -> LoginResult:
        email = normalize_email(email_value)
        subject = f"{client_key}|{email}"
        login_window = int(self.config.get("AUTH_RATE_LOGIN_WINDOW_SECONDS", 900))
        login_limit = int(self.config.get("AUTH_RATE_LOGIN_MAX", 10))
        # V51.35 — duas camadas: por cliente e por cliente+conta. Assim uma
        # tentativa de pulverizar vários e-mails não contorna o limite principal.
        self._rate(
            "login_client", client_key,
            window=login_window, limit=max(20, login_limit * 5),
        )
        self._rate(
            "login", subject, window=login_window, limit=login_limit,
        )
        user = self.repo.get_user_by_email(email) if email else None
        password = str(password_value or "")
        password_hash = str(user.get("password_hash") if user else DUMMY_PASSWORD_HASH)
        if not verify_password(password_hash, password):
            self.repo.audit(user_id=int(user["id"]) if user else None, action="login_failed")
            return LoginResult(False, "invalid", user=None, message="E-mail ou senha inválidos.")

        status = str(user.get("access_status") or "")
        if status != "active":
            self.repo.audit(user_id=int(user["id"]), action=f"login_blocked_{status}")
            messages = {
                "email_pending": "Confirme seu e-mail antes de continuar.",
                "pending_approval": "Seu e-mail foi confirmado e sua solicitação está aguardando aprovação.",
                "rejected": "Sua solicitação de acesso não foi aprovada neste momento.",
                "suspended": "Seu acesso está suspenso.",
                "disabled": "Esta conta está desativada.",
            }
            return LoginResult(False, status, user=user, message=messages.get(status, "Conta indisponível."))

        token = generate_session_token()
        self.repo.create_session(
            token_hash=session_token_digest(token),
            user_id=int(user["id"]),
            ttl_seconds=int(self.config.get("AUTH_SESSION_TTL_SECONDS", 43200)),
        )
        self.repo.mark_login(int(user["id"]))
        self.repo.audit(user_id=int(user["id"]), action="login_success")
        return LoginResult(True, "active", user=self.repo.get_user_by_id(int(user["id"])), session_token=token)

    def current_session_user(self, token: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        digest = session_token_digest(token)
        if not token:
            return None
        result = self.repo.get_session_user(digest)
        if result:
            auth_session, user = result
            last_seen = parse_iso_utc(str(auth_session.get("last_seen_at") or ""))
            if last_seen is None or (utc_now() - last_seen).total_seconds() >= 60:
                self.repo.touch_session(int(auth_session["id"]))
            return auth_session, user
        return None

    def revoke_session(self, token: str) -> None:
        if token:
            self.repo.revoke_session(session_token_digest(token))

    def request_password_reset(self, email_value: object, *, client_key: str) -> bool:
        email = normalize_email(email_value)
        reset_window = int(self.config.get("AUTH_RATE_RESET_WINDOW_SECONDS", 3600))
        reset_limit = int(self.config.get("AUTH_RATE_RESET_MAX", 5))
        self._rate(
            "password_reset_client", client_key,
            window=reset_window, limit=max(15, reset_limit * 5),
        )
        self._rate(
            "password_reset_request", f"{client_key}|{email}",
            window=reset_window, limit=reset_limit,
        )
        user = self.repo.get_user_by_email(email) if email else None
        if not user:
            return False
        code = self._create_challenge(user, "password_reset")
        try:
            send_password_reset_code(
                recipient=str(user["email_normalized"]),
                full_name=str(user["full_name"]),
                code=code,
                ttl_minutes=max(1, int(self.config.get("AUTH_CODE_TTL_SECONDS", 900)) // 60),
                config=self.config,
            )
        except AuthEmailDeliveryError:
            self.repo.audit(user_id=int(user["id"]), action="password_reset_email_failed")
            return False
        self.repo.audit(user_id=int(user["id"]), action="password_reset_requested")
        return True

    def reset_password(self, email_value: object, code: object, new_password: object, confirm: object, *, client_key: str) -> None:
        email = normalize_email(email_value)
        user = self.repo.get_user_by_email(email) if email else None
        if not user:
            # Mantém resposta indistinguível de código inválido.
            raise AuthValidationError("Código inválido ou expirado.")
        password = validate_password(
            new_password, minimum_length=int(self.config.get("AUTH_PASSWORD_MIN_LENGTH", 10))
        )
        if password != str(confirm or ""):
            raise AuthValidationError("As senhas informadas não conferem.")
        self._validate_challenge(user, "password_reset", code, client_key=client_key)
        self.repo.set_password(int(user["id"]), hash_password(password))
        self.repo.invalidate_challenges(int(user["id"]), "password_reset")
        self.repo.revoke_user_sessions(int(user["id"]))
        self.repo.audit(user_id=int(user["id"]), action="password_reset_completed")

    # Utilitário interno para testes/migração administrativa futura. Não exposto em rota pública.
    def set_status(self, public_id: str, status: str) -> dict[str, Any]:
        if status not in ACCESS_STATUSES:
            raise AuthValidationError("Status inválido.")
        user = self.repo.get_user_by_public_id(public_id)
        if not user:
            raise AuthValidationError("Usuário não localizado.", 404)
        updated = self.repo.set_status(int(user["id"]), status)
        # Não revoga em massa aqui: a próxima requisição de cada sessão ainda
        # consegue ler o novo status e então é negada/revogada pelo guard global.
        # Isso garante efeito imediato e uma mensagem de estado coerente.
        self.repo.audit(user_id=int(user["id"]), action=f"status_changed_{status}")
        return updated


@lru_cache(maxsize=16)
def _cached_auth_service(database_path: str, secret_key: str, config_fingerprint: tuple[tuple[str, str], ...]) -> AuthService:
    config = dict(config_fingerprint)
    return AuthService(database_path, secret_key, config)


def get_auth_service() -> AuthService:
    keys = (
        "AUTH_CODE_TTL_SECONDS", "AUTH_CODE_MAX_ATTEMPTS", "AUTH_CODE_RESEND_COOLDOWN_SECONDS",
        "AUTH_PASSWORD_MIN_LENGTH", "AUTH_SESSION_TTL_SECONDS", "AUTH_PRIVACY_VERSION",
        "AUTH_RATE_LOGIN_WINDOW_SECONDS", "AUTH_RATE_LOGIN_MAX",
        "AUTH_RATE_REGISTER_WINDOW_SECONDS", "AUTH_RATE_REGISTER_MAX",
        "AUTH_RATE_VERIFY_WINDOW_SECONDS", "AUTH_RATE_VERIFY_MAX",
        "AUTH_RATE_RESET_WINDOW_SECONDS", "AUTH_RATE_RESET_MAX",
        "CONTACT_SMTP_HOST", "CONTACT_SMTP_PORT", "CONTACT_SMTP_USERNAME", "CONTACT_SMTP_PASSWORD",
        "CONTACT_FROM_EMAIL", "CONTACT_SMTP_USE_TLS", "CONTACT_SMTP_USE_SSL", "CONTACT_SMTP_TIMEOUT",
    )
    fingerprint = tuple((key, str(current_app.config.get(key, ""))) for key in keys)
    return _cached_auth_service(
        str(current_app.config["ARQUIVO_AUTH_USUARIOS"]),
        str(current_app.config["SECRET_KEY"]),
        fingerprint,
    )
