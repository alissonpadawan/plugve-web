import unittest
from unittest.mock import patch

from services.contact_email_service import (
    ContactEmailConfigurationError,
    ContactEmailError,
    send_contact_email,
    validate_contact_message,
)


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in = None
        self.sent_message = None
        self.tls_started = False
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ehlo(self):
        return None

    def starttls(self, context=None):
        self.tls_started = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent_message = message


class ContactEmailServiceTests(unittest.TestCase):
    def setUp(self):
        _FakeSMTP.instances.clear()
        self.contact = validate_contact_message(
            name="Maria da Silva",
            email="maria@example.com",
            subject="Sugestão para a plataforma",
            message="Gostaria de enviar uma sugestão para a CurVE.",
        )

    def test_validation_rejects_invalid_fields_and_honeypot(self):
        with self.assertRaises(ContactEmailError):
            validate_contact_message(
                name="M",
                email="invalido",
                subject="Oi",
                message="curta",
            )
        with self.assertRaises(ContactEmailError):
            validate_contact_message(
                name="Maria da Silva",
                email="maria@example.com",
                subject="Sugestão",
                message="Mensagem válida para teste.",
                honeypot="robô",
            )

    def test_send_uses_smtp_tls_reply_to_and_requested_recipient(self):
        config = {
            "CONTACT_SMTP_HOST": "smtp.gmail.com",
            "CONTACT_SMTP_PORT": 587,
            "CONTACT_SMTP_USERNAME": "sv.alisson@gmail.com",
            "CONTACT_SMTP_PASSWORD": "app-password",
            "CONTACT_TO_EMAIL": "sv.alisson@gmail.com",
            "CONTACT_FROM_EMAIL": "sv.alisson@gmail.com",
            "CONTACT_SMTP_USE_TLS": True,
            "CONTACT_SMTP_USE_SSL": False,
            "CONTACT_SMTP_TIMEOUT": 20,
        }
        with patch("services.contact_email_service.smtplib.SMTP", _FakeSMTP):
            send_contact_email(self.contact, config)

        smtp = _FakeSMTP.instances[-1]
        self.assertTrue(smtp.tls_started)
        self.assertEqual(smtp.logged_in, ("sv.alisson@gmail.com", "app-password"))
        self.assertEqual(smtp.sent_message["To"], "sv.alisson@gmail.com")
        self.assertEqual(smtp.sent_message["Reply-To"], "maria@example.com")
        self.assertIn("Sugestão para a plataforma", smtp.sent_message["Subject"])

    def test_send_requires_server_credentials(self):
        with self.assertRaises(ContactEmailConfigurationError):
            send_contact_email(
                self.contact,
                {
                    "CONTACT_SMTP_HOST": "smtp.gmail.com",
                    "CONTACT_TO_EMAIL": "sv.alisson@gmail.com",
                },
            )


if __name__ == "__main__":
    unittest.main()
