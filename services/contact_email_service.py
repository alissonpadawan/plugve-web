from __future__ import annotations

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Mapping, Any


NAME_MAX_LENGTH = 100
SUBJECT_MAX_LENGTH = 120
MESSAGE_MAX_LENGTH = 3000

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ContactEmailError(Exception):
    """Erro controlado do envio de contato."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ContactEmailConfigurationError(ContactEmailError):
    pass


class ContactEmailDeliveryError(ContactEmailError):
    pass


@dataclass(frozen=True)
class ContactMessage:
    name: str
    email: str
    subject: str
    message: str


def _clean_single_line(value: Any, *, field_name: str, max_length: int) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not text:
        raise ContactEmailError(f"Preencha o campo {field_name}.")
    if len(text) > max_length:
        raise ContactEmailError(f"O campo {field_name} ultrapassa o limite de {max_length} caracteres.")
    return text


def validate_contact_message(
    *,
    name: Any,
    email: Any,
    subject: Any,
    message: Any,
    honeypot: Any = "",
) -> ContactMessage:
    if str(honeypot or "").strip():
        raise ContactEmailError("Não foi possível enviar a mensagem.", 400)

    clean_name = _clean_single_line(name, field_name="Nome", max_length=NAME_MAX_LENGTH)
    clean_email = _clean_single_line(email, field_name="E-mail", max_length=254).lower()
    clean_subject = _clean_single_line(subject, field_name="Assunto", max_length=SUBJECT_MAX_LENGTH)
    clean_message = str(message or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    if not _EMAIL_RE.fullmatch(clean_email):
        raise ContactEmailError("Informe um endereço de e-mail válido.")
    if len(clean_name) < 2:
        raise ContactEmailError("Informe seu nome completo.")
    if len(clean_subject) < 3:
        raise ContactEmailError("Informe um assunto com pelo menos 3 caracteres.")
    if len(clean_message) < 8:
        raise ContactEmailError("Escreva uma mensagem com pelo menos 8 caracteres.")
    if len(clean_message) > MESSAGE_MAX_LENGTH:
        raise ContactEmailError(f"A mensagem ultrapassa o limite de {MESSAGE_MAX_LENGTH} caracteres.")

    return ContactMessage(
        name=clean_name,
        email=clean_email,
        subject=clean_subject,
        message=clean_message,
    )


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "sim", "yes", "on"}


def send_contact_email(contact: ContactMessage, config: Mapping[str, Any]) -> None:
    host = str(config.get("CONTACT_SMTP_HOST") or "").strip()
    port = int(config.get("CONTACT_SMTP_PORT") or 587)
    username = str(config.get("CONTACT_SMTP_USERNAME") or "").strip()
    password = str(config.get("CONTACT_SMTP_PASSWORD") or "").strip()
    recipient = str(config.get("CONTACT_TO_EMAIL") or "").strip()
    sender = str(config.get("CONTACT_FROM_EMAIL") or username or recipient).strip()
    timeout = int(config.get("CONTACT_SMTP_TIMEOUT") or 20)
    use_tls = _as_bool(config.get("CONTACT_SMTP_USE_TLS", True))
    use_ssl = _as_bool(config.get("CONTACT_SMTP_USE_SSL", False))

    if not host or not username or not password or not recipient or not sender:
        raise ContactEmailConfigurationError(
            "O envio direto ainda não está configurado no servidor.", 503
        )

    email_message = EmailMessage()
    email_message["Subject"] = f"[CurVE] {contact.subject}"
    email_message["From"] = sender
    email_message["To"] = recipient
    email_message["Reply-To"] = contact.email
    email_message.set_content(
        "\n".join(
            (
                "Nova mensagem enviada pela página Contato da CurVE.",
                "",
                f"Nome: {contact.name}",
                f"E-mail para retorno: {contact.email}",
                f"Assunto: {contact.subject}",
                "",
                "Mensagem:",
                contact.message,
            )
        )
    )

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
                smtp.login(username, password)
                smtp.send_message(email_message)
            return

        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(email_message)
    except (smtplib.SMTPException, OSError) as exc:
        raise ContactEmailDeliveryError(
            "Não foi possível enviar a mensagem agora. Tente novamente em alguns minutos.", 502
        ) from exc
