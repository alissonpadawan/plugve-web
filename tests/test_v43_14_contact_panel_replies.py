import unittest
from pathlib import Path


class V4314IntegrationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_public_comment_replies_and_official_badge_exist(self):
        template = (self.root / "templates" / "sobre.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "sobre.js").read_text(encoding="utf-8")
        css = (self.root / "static" / "css" / "institucional.css").read_text(encoding="utf-8")
        self.assertIn("data-reply-comment", template)
        self.assertIn("comment-reply--official", template)
        self.assertIn("Resposta oficial", template)
        self.assertIn("parent_id", script)
        self.assertIn("Responder comentário", script)
        self.assertIn("official-reply-badge", css)

    def test_admin_routes_cover_official_replies_and_contact_inbox(self):
        routes = (self.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        config = (self.root / "config.py").read_text(encoding="utf-8")
        self.assertIn('/official-replies", methods=["POST"]', routes)
        self.assertIn('/api/contato/admin/messages", methods=["GET"]', routes)
        self.assertIn('methods=["PATCH", "DELETE"]', routes)
        self.assertIn("ARQUIVO_MENSAGENS_CONTATO", config)

    def test_contact_message_is_saved_before_smtp_delivery(self):
        routes = (self.root / "routes" / "tco_routes.py").read_text(encoding="utf-8")
        stored_index = routes.index("stored_message = inbox_service.create_message")
        sent_index = routes.index("send_contact_email(contact_message")
        self.assertLess(stored_index, sent_index)


if __name__ == "__main__":
    unittest.main()
