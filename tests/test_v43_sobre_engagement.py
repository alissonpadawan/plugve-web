import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("PLUGVE_PREWARM_FIPE", "0")

try:
    from app import create_app
except ModuleNotFoundError as exc:
    if exc.name == "flask":
        create_app = None
    else:
        raise
from services.sobre_engagement_service import EngagementValidationError, SobreEngagementService


class SobreEngagementServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "sobre.sqlite3"
        self.service = SobreEngagementService(self.database)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_unique_visitors_and_switchable_votes(self):
        self.assertTrue(self.service.register_visitor("browser-a"))
        self.assertFalse(self.service.register_visitor("browser-a"))
        self.assertTrue(self.service.register_visitor("browser-b"))
        self.assertEqual(self.service.get_stats()["visitors"], 2)

        stats = self.service.set_vote("browser-a", "like")
        self.assertEqual(stats["likes"], 1)
        self.assertEqual(stats["dislikes"], 0)
        stats = self.service.set_vote("browser-a", "dislike")
        self.assertEqual(stats["likes"], 0)
        self.assertEqual(stats["dislikes"], 1)
        stats = self.service.set_vote("browser-a", None)
        self.assertEqual(stats["likes"], 0)
        self.assertEqual(stats["dislikes"], 0)

    def test_comment_is_public_without_exposing_email(self):
        comment = self.service.add_comment(
            visitor_id="visitor-1",
            name="Maria da Silva",
            email="maria@example.com",
            body="A apresentação ficou clara e objetiva.",
        )
        self.assertEqual(comment["name"], "Maria da Silva")
        self.assertNotIn("email", comment)
        page = self.service.list_comments()
        self.assertEqual(page["total"], 1)
        self.assertNotIn("email", page["comments"][0])

    def test_admin_list_exposes_private_email_and_delete_removes_comment(self):
        created = self.service.add_comment(
            visitor_id="visitor-admin",
            name="Pessoa Administradora",
            email="admin@example.com",
            body="Comentário para validação administrativa.",
        )
        page = self.service.list_comments_admin()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["comments"][0]["email"], "admin@example.com")
        self.assertTrue(self.service.delete_comment(created["id"]))
        self.assertEqual(self.service.list_comments()["total"], 0)
        self.assertFalse(self.service.delete_comment(created["id"]))

    def test_comment_rejects_links_phones_emails_html_and_blocked_language(self):
        invalid_comments = (
            "Veja mais em https://example.com agora.",
            "Meu telefone é (62) 99999-9999.",
            "Escreva para teste@example.com.",
            "<script>alert('x')</script>",
            "Seu trabalho é uma merda completa.",
        )
        for index, body in enumerate(invalid_comments):
            with self.subTest(body=body):
                with self.assertRaises(EngagementValidationError):
                    self.service.add_comment(
                        visitor_id=f"visitor-{index}",
                        name="Pessoa Teste",
                        email=f"pessoa{index}@example.com",
                        body=body,
                    )


@unittest.skipIf(create_app is None, "Flask indisponível no ambiente de validação")
class SobreEngagementRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            ARQUIVO_SOBRE_ENGAJAMENTO=Path(self.tempdir.name) / "sobre-route.sqlite3",
            PLUGVE_ADMIN_TOKEN="test-admin-token",
            PLUGVE_SYNC_TOKEN="test-admin-token",
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _csrf_token(self):
        with self.client.session_transaction() as flask_session:
            return flask_session["sobre_csrf_token"]

    def test_about_page_registers_visit_and_renders_controls(self):
        response = self.client.get("/sobre")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-vote="like"', html)
        self.assertIn('id="share-about-dialog"', html)
        self.assertIn('id="sobre-comment-form"', html)
        self.assertNotIn("Não inclua telefone, links, e-mail", html)

        stats = self.client.get("/api/sobre/engagement").get_json()
        self.assertEqual(stats["visitors"], 1)

    def test_vote_and_comment_require_csrf_and_work_with_valid_token(self):
        self.client.get("/sobre")
        token = self._csrf_token()

        invalid = self.client.post("/api/sobre/vote", json={"vote": "like"})
        self.assertEqual(invalid.status_code, 403)

        vote = self.client.post(
            "/api/sobre/vote",
            json={"vote": "like"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(vote.status_code, 200)
        self.assertEqual(vote.get_json()["likes"], 1)

        comment = self.client.post(
            "/api/sobre/comments",
            json={
                "name": "João Teste",
                "email": "joao@example.com",
                "comment": "A página ficou muito clara e organizada.",
                "website": "",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(comment.status_code, 201)
        payload = comment.get_json()
        self.assertNotIn("email", payload["comment"])
        self.assertEqual(payload["stats"]["comments"], 1)

    def test_admin_comments_api_requires_token_lists_email_and_deletes(self):
        self.client.get("/sobre")
        token = self._csrf_token()
        created = self.client.post(
            "/api/sobre/comments",
            json={
                "name": "Pessoa Painel",
                "email": "painel@example.com",
                "comment": "Comentário disponível para o painel administrativo.",
                "website": "",
            },
            headers={"X-CSRF-Token": token},
        ).get_json()["comment"]

        unauthorized = self.client.get("/api/sobre/admin/comments")
        self.assertEqual(unauthorized.status_code, 401)

        headers = {"X-PlugVE-Admin-Token": "test-admin-token"}
        listing = self.client.get("/api/sobre/admin/comments", headers=headers)
        self.assertEqual(listing.status_code, 200)
        payload = listing.get_json()
        self.assertEqual(payload["comments"][0]["email"], "painel@example.com")
        self.assertEqual(payload["comments"][0]["id"], created["id"])

        deleted = self.client.delete(
            f"/api/sobre/admin/comments/{created['id']}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json()["stats"]["comments"], 0)


if __name__ == "__main__":
    unittest.main()


class SobreRepliesServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = SobreEngagementService(Path(self.tempdir.name) / "replies.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_public_reply_is_nested_and_email_remains_private(self):
        root = self.service.add_comment(
            visitor_id="root-browser",
            name="Pessoa Inicial",
            email="inicial@example.com",
            body="Comentário principal para receber respostas.",
        )
        reply = self.service.add_comment(
            visitor_id="reply-browser",
            name="Outra Pessoa",
            email="resposta@example.com",
            body="Esta é uma resposta pública ao comentário.",
            parent_id=root["id"],
        )
        page = self.service.list_comments()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["comments"][0]["replies"][0]["id"], reply["id"])
        self.assertNotIn("email", page["comments"][0]["replies"][0])
        self.assertEqual(self.service.get_stats()["comments"], 1)

    def test_reply_to_reply_is_rejected_and_official_reply_is_identified(self):
        root = self.service.add_comment(
            visitor_id="root-2",
            name="Pessoa Inicial",
            email="inicial2@example.com",
            body="Outro comentário principal para teste.",
        )
        reply = self.service.add_comment(
            visitor_id="reply-2",
            name="Pessoa Resposta",
            email="reply2@example.com",
            body="Resposta comum publicada por visitante.",
            parent_id=root["id"],
        )
        with self.assertRaises(EngagementValidationError):
            self.service.add_comment(
                visitor_id="third-level",
                name="Terceira Pessoa",
                email="third@example.com",
                body="Esta tentativa não pode criar terceiro nível.",
                parent_id=reply["id"],
            )
        official = self.service.add_official_reply(root["id"], "Agradecemos a participação e o retorno enviado.")
        self.assertTrue(official["is_official"])
        self.assertEqual(official["name"], "CurVE")
        page = self.service.list_comments_admin()
        self.assertTrue(any(item["is_official"] for item in page["comments"]))

    def test_delete_root_also_removes_replies(self):
        root = self.service.add_comment(
            visitor_id="root-delete",
            name="Pessoa Inicial",
            email="delete@example.com",
            body="Comentário principal que será excluído.",
        )
        self.service.add_official_reply(root["id"], "Resposta oficial vinculada ao comentário.")
        self.assertTrue(self.service.delete_comment(root["id"]))
        self.assertEqual(self.service.list_comments_admin()["total"], 0)
