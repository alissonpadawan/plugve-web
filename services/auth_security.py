from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from urllib.parse import unquote, urlsplit

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def normalize_email(value: object) -> str:
    return str(value or "").strip().casefold()


def validate_email(value: object) -> str:
    email = normalize_email(value)
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise AuthValidationError("Informe um endereço de e-mail válido.")
    return email


def clean_single_line(value: object, *, field: str, max_length: int, required: bool = True) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if required and not text:
        raise AuthValidationError(f"Preencha o campo {field}.")
    if len(text) > max_length:
        raise AuthValidationError(f"O campo {field} ultrapassa o limite de {max_length} caracteres.")
    return text


def validate_password(password: object, *, minimum_length: int = 10) -> str:
    value = str(password or "")
    if len(value) < int(minimum_length):
        raise AuthValidationError(f"A senha deve ter pelo menos {minimum_length} caracteres.")
    if len(value) > 256:
        raise AuthValidationError("A senha ultrapassa o limite permitido.")
    return value


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(check_password_hash(str(password_hash or ""), str(password or "")))
    except (ValueError, TypeError):
        return False


def generate_numeric_code(length: int = 6) -> str:
    length = max(4, min(10, int(length)))
    upper = 10 ** length
    return f"{secrets.randbelow(upper):0{length}d}"


def challenge_digest(secret_key: str, *, user_public_id: str, purpose: str, code: str) -> str:
    message = f"curve-auth|{user_public_id}|{purpose}|{code}".encode("utf-8")
    return hmac.new(str(secret_key).encode("utf-8"), message, hashlib.sha256).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return bool(left and right and hmac.compare_digest(str(left), str(right)))


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def session_token_digest(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def subject_digest(secret_key: str, value: str) -> str:
    return hmac.new(
        str(secret_key).encode("utf-8"),
        f"curve-rate|{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def ensure_auth_csrf_token() -> str:
    token = str(session.get("auth_csrf_token") or "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session["auth_csrf_token"] = token
    return token


def validate_auth_csrf_token(supplied: object) -> None:
    expected = str(session.get("auth_csrf_token") or "")
    received = str(supplied or "")
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise AuthValidationError("Sessão inválida. Atualize a página e tente novamente.", 403)


def safe_next_path(value: object, *, fallback: str = "/") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback

    # V51.35 — valida também a forma decodificada. Isso fecha variantes de
    # open redirect que tentam esconder //, barras invertidas ou CR/LF com
    # percent-encoding antes de chegar ao Location do redirect.
    decoded = raw
    for _ in range(2):
        try:
            decoded = unquote(decoded)
        except Exception:
            return fallback
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc or not decoded.startswith("/") or decoded.startswith("//"):
        return fallback
    if "\\" in decoded or any(ord(ch) < 32 for ch in decoded):
        return fallback
    return raw
