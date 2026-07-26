import tempfile
import unittest
from pathlib import Path

from services.contact_email_service import ContactMessage
from services.contact_inbox_service import ContactInboxService, ContactInboxValidationError


class ContactInboxServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = ContactInboxService(Path(self.tempdir.name) / "contact.sqlite3")
        self.contact = ContactMessage(
            name="Maria da Silva",
            email="maria@example.com",
            subject="Dúvida sobre a CurVE",
            message="Gostaria de esclarecer uma informação da plataforma.",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_message_is_saved_and_status_can_be_managed(self):
        created = self.service.create_message(self.contact)
        self.assertEqual(created["status"], "unread")
        self.assertEqual(created["delivery_status"], "pending")
        sent = self.service.update_delivery(created["id"], "sent")
        self.assertEqual(sent["delivery_status"], "sent")
        read = self.service.update_status(created["id"], "read")
        self.assertEqual(read["status"], "read")
        page = self.service.list_messages()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["unread"], 0)
        self.assertEqual(page["messages"][0]["email"], "maria@example.com")

    def test_failed_delivery_is_visible_and_delete_is_permanent(self):
        created = self.service.create_message(self.contact)
        failed = self.service.update_delivery(created["id"], "failed", "SMTP indisponível")
        self.assertEqual(failed["delivery_status"], "failed")
        self.assertIn("SMTP", failed["delivery_error"])
        self.assertTrue(self.service.delete_message(created["id"]))
        self.assertEqual(self.service.list_messages()["total"], 0)

    def test_invalid_status_is_rejected(self):
        created = self.service.create_message(self.contact)
        with self.assertRaises(ContactInboxValidationError):
            self.service.update_status(created["id"], "unknown")
