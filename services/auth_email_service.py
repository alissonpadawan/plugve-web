from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Mapping

from services.contact_email_service import send_email_message


class AuthEmailDeliveryError(RuntimeError):
    pass


def _base_message(*, recipient: str, subject: str, body: str, config: Mapping[str, Any]) -> EmailMessage:
    sender = str(config.get("CONTACT_FROM_EMAIL") or config.get("CONTACT_SMTP_USERNAME") or "").strip()
    if not sender:
        raise AuthEmailDeliveryError("Remetente de e-mail não configurado.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = str(recipient or "").strip()
    message.set_content(body)
    return message


def send_verification_code(*, recipient: str, full_name: str, code: str, ttl_minutes: int, config: Mapping[str, Any]) -> None:
    body = "\n".join((
        f"Olá, {full_name}.",
        "",
        "Recebemos sua solicitação de acesso à CurVE.",
        f"Seu código de confirmação é: {code}",
        f"Ele é válido por {ttl_minutes} minutos e pode ser usado uma única vez.",
        "",
        "Depois da confirmação do e-mail, sua solicitação ficará aguardando aprovação administrativa.",
        "Se você não solicitou este acesso, ignore esta mensagem.",
    ))
    message = _base_message(recipient=recipient, subject="[CurVE] Confirme seu e-mail", body=body, config=config)
    try:
        send_email_message(message, config)
    except Exception as exc:
        raise AuthEmailDeliveryError("Não foi possível enviar o código de confirmação agora.") from exc


def send_password_reset_code(*, recipient: str, full_name: str, code: str, ttl_minutes: int, config: Mapping[str, Any]) -> None:
    body = "\n".join((
        f"Olá, {full_name}.",
        "",
        "Foi solicitada uma redefinição de senha da sua conta CurVE.",
        f"Seu código temporário é: {code}",
        f"Ele é válido por {ttl_minutes} minutos e pode ser usado uma única vez.",
        "",
        "Se você não solicitou a redefinição, ignore esta mensagem. Sua senha atual continuará válida.",
    ))
    message = _base_message(recipient=recipient, subject="[CurVE] Redefinição de senha", body=body, config=config)
    try:
        send_email_message(message, config)
    except Exception as exc:
        raise AuthEmailDeliveryError("Não foi possível enviar as instruções de recuperação agora.") from exc


def send_access_approved(*, recipient: str, full_name: str, config: Mapping[str, Any]) -> None:
    body = "\n".join((
        f"Olá, {full_name}.",
        "",
        "Seu acesso à CurVE foi aprovado.",
        "Você já pode entrar utilizando seu e-mail e a senha cadastrada.",
        "",
        "A CurVE nunca envia sua senha por e-mail.",
    ))
    message = _base_message(recipient=recipient, subject="[CurVE] Acesso aprovado", body=body, config=config)
    try:
        send_email_message(message, config)
    except Exception as exc:
        raise AuthEmailDeliveryError("A aprovação foi registrada, mas o e-mail de notificação não pôde ser enviado agora.") from exc


def send_access_rejected(*, recipient: str, full_name: str, config: Mapping[str, Any]) -> None:
    body = "\n".join((
        f"Olá, {full_name}.",
        "",
        "Sua solicitação de acesso à CurVE não foi aprovada neste momento.",
        "",
        "Esta mensagem não contém observações administrativas internas.",
    ))
    message = _base_message(recipient=recipient, subject="[CurVE] Solicitação de acesso", body=body, config=config)
    try:
        send_email_message(message, config)
    except Exception as exc:
        raise AuthEmailDeliveryError("A rejeição foi registrada, mas o e-mail de notificação não pôde ser enviado agora.") from exc
