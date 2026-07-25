import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class V43InstitutionalPagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.templates = cls.root / "templates"

    def test_institutional_templates_parse(self):
        env = Environment(loader=FileSystemLoader(self.templates))
        for name in ("base.html", "sobre.html", "contato.html"):
            env.get_template(name)

    def test_about_keeps_requested_profile_order_and_contacts(self):
        html = (self.templates / "sobre.html").read_text(encoding="utf-8")
        daywes = html.index("Prof. Dr. Daywes Pinheiro Neto")
        carlos = html.index("Prof. Dr. Carlos Roberto da Silveira Jr.")
        alisson = html.index("Alisson Vieira da Silva")
        self.assertLess(daywes, carlos)
        self.assertLess(carlos, alisson)
        for value in (
            "daywes.neto@ifg.edu.br",
            "carlos.junior@ifg.edu.br",
            "sv.alisson@gmail.com",
            "3885723899789699",
            "5503461601783322",
            "1978825412536553",
        ):
            self.assertIn(value, html)
        self.assertIn("https://teclimpa.ifg.edu.br", html)
        self.assertEqual(html.count('class="author-popover"'), 3)


    def test_about_v43_06_author_card_and_hover_popovers(self):
        html = (self.templates / "sobre.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "sobre.js").read_text(encoding="utf-8")
        css = (self.root / "static" / "css" / "institucional.css").read_text(encoding="utf-8")

        self.assertIn(">Autores<", html)
        self.assertNotIn(">Criadores<", html)
        self.assertIn('class="authors-card card"', html)
        self.assertEqual(html.count('class="author-entry '), 3)
        self.assertEqual(html.count('class="author-name-link"'), 3)
        self.assertEqual(html.count('class="author-popover"'), 3)
        self.assertNotIn('<dialog class="author', html)
        self.assertNotIn("Ver perfil", html)
        self.assertEqual(html.count('class="author-prefix"'), 2)
        self.assertIn('>Prof. Dr.<', html)
        self.assertNotIn('class="creator-profile"', html)

        for url in (
            "https://www.youtube.com/@ppgtgs-ifg",
            "https://x.com/ppgtgs",
            "https://www.facebook.com/ppgtgs",
            "https://www.instagram.com/teclimpa/",
            "https://www.linkedin.com/company/ppgtgs",
            "https://www.linkedin.com/in/svalisson/",
            "https://www.linkedin.com/in/carlos-roberto-da-silveira-junior-957b47298/",
        ):
            self.assertIn(url, html)

        self.assertNotIn('class="author-lattes-link"', html)
        self.assertEqual(html.count('>Lattes</a>'), 3)
        self.assertIn("Carlos Roberto da Silveira Jr.", html)
        self.assertNotIn("Carlos Roberto da Silveira Júnior", html)
        self.assertIn("Estudante do PPGTGS em Energias Renováveis", html)
        self.assertIn("com ênfase em Energias Renováveis", html)
        self.assertNotIn("Autor da CurVE", html)
        self.assertIn("mouseenter", script)
        self.assertIn("focusin", script)
        self.assertIn("aria-expanded", script)
        self.assertIn(".author-entry:hover .author-popover", css)
        self.assertIn(".author-entry:focus-within .author-popover", css)
        self.assertIn(".authors-card {", css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", css)
        self.assertIn(".author-entry + .author-entry", css)
        self.assertIn(".author-summary {", css)
        self.assertIn("font-weight: 400;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn("position: absolute;", css)


    def test_about_v43_07_engagement_and_comments_interface(self):
        html = (self.templates / "sobre.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "sobre.js").read_text(encoding="utf-8")
        css = (self.root / "static" / "css" / "institucional.css").read_text(encoding="utf-8")
        for value in (
            'data-vote="like"',
            'data-vote="dislike"',
            'data-visitor-count',
            'id="share-about-dialog"',
            'id="sobre-comment-form"',
            'data-comments-more',
            'maxlength="{{ comment_max_length }}"',
        ):
            self.assertIn(value, html)
        self.assertIn('/api/sobre/vote', script)
        self.assertIn('/api/sobre/comments', script)
        self.assertIn('textContent', script)
        self.assertIn('.share-dialog {', css)
        self.assertIn('.comments-card {', css)
        self.assertIn('id="comment-about-dialog"', html)
        self.assertIn('data-open-comment', html)
        self.assertIn('>Deixar seu comentário<', html)
        self.assertIn('.comment-dialog {', css)
        self.assertIn('showModal()', script)
        self.assertNotIn("Seu e-mail não será exibido.", html)
        self.assertIn(".comments-form-grid .field + .field", css)
        self.assertIn("height: 48px;", css)

    def test_contact_form_sends_directly_and_lists_requested_contacts(self):
        html = (self.templates / "contato.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "contato.js").read_text(encoding="utf-8")
        self.assertIn('id="contact-form"', html)
        self.assertIn('data-contact-csrf="{{ contato_csrf_token }}"', html)
        self.assertIn('>Enviar mensagem</button>', html)
        self.assertNotIn("Abrir no e-mail", html)
        self.assertNotIn("mailto:sv.alisson@gmail.com?subject", script)
        self.assertIn('fetch("/api/contato"', script)
        self.assertIn("reportValidity", script)

        alisson = html.index("sv.alisson@gmail.com")
        daywes = html.index("daywes.neto@ifg.edu.br")
        carlos = html.index("carlos.junior@ifg.edu.br")
        self.assertLess(alisson, daywes)
        self.assertLess(daywes, carlos)
        for value in (
            "teclimpa@ifg.edu.br",
            "+55 (62) 3227-2811",
            "Rua 75, nº 46, Centro, CEP 74055-110, Goiânia–GO.",
        ):
            self.assertIn(value, html)

        self.assertIn('class="card contact-workspace"', html)
        self.assertIn('class="contact-sidebar"', html)
        self.assertIn('class="contact-map"', html)
        self.assertIn('output=embed', html)
        self.assertEqual(html.count('class="contact-simple-icon"'), 6)
        self.assertNotIn('class="card contact-directory"', html)
        self.assertNotIn('class="contact-directory-group"', html)

    def test_about_v43_12_social_preview_is_short_and_complete(self):
        html = (self.templates / "sobre.html").read_text(encoding="utf-8")
        script = (self.root / "static" / "js" / "sobre.js").read_text(encoding="utf-8")
        for value in (
            'property="og:title" content="CurVE — Calculadora Veicular"',
            'property="og:description" content="Compare custos, depreciação, consumo e valor futuro de veículos."',
            'property="og:url" content="https://curveveicular.com.br/sobre"',
            'property="og:image" content="https://curveveicular.com.br/static/img/social/curve-sobre-share.png"',
            'name="twitter:card" content="summary_large_image"',
            'rel="canonical" href="https://curveveicular.com.br/sobre"',
        ):
            self.assertIn(value, html)
        self.assertIn('const shareTitle = "CurVE — Calculadora Veicular";', script)
        self.assertIn('const shareText = "Compare custos, depreciação, consumo e valor futuro de veículos.";', script)
        self.assertIn('Conheça a ${shareTitle}', script)
        self.assertTrue((self.root / "static" / "img" / "social" / "curve-sobre-share.png").is_file())

    def test_footer_has_ifg_logo_and_official_channels(self):
        html = (self.templates / "base.html").read_text(encoding="utf-8")
        self.assertIn("logo-ifg-horizontal-branco.png", html)
        for url in (
            "https://www.instagram.com/ifg_oficial/",
            "https://www.facebook.com/IFG.oficial",
            "https://x.com/IFG_Goias",
            "https://www.youtube.com/user/ifgoficial",
            "https://www.linkedin.com/school/instituto-federal-de-goi%C3%A1s-ifg/",
        ):
            self.assertIn(url, html)
        self.assertIn("CurVE © 2026 — Instituto Federal de Goiás. Todos os direitos reservados.", html)

    def test_footer_is_consistent_on_home_and_simulator(self):
        required = (
            "logo-ifg-horizontal-branco.png",
            "Acompanhe o IFG",
            "Conheça o PPGTGS",
            "CurVE © 2026 — Instituto Federal de Goiás. Todos os direitos reservados.",
        )
        for name in ("base.html", "index.html", "home.html", "simular.html"):
            html = (self.templates / name).read_text(encoding="utf-8")
            self.assertIn('class="footer institutional-footer"', html, name)
            for value in required:
                self.assertIn(value, html, f"{name}: {value}")

    def test_footer_starts_below_the_initial_viewport(self):
        app_css = (self.root / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".site-main {", app_css)
        self.assertIn("min-height: calc(100svh - 72px);", app_css)
        simular = (self.templates / "simular.html").read_text(encoding="utf-8")
        self.assertIn(".curve-shell{position:relative;z-index:1;flex:0 0 auto;min-height:calc(100vh - 72px);min-height:calc(100svh - 72px);", simular)

    def test_institutional_assets_exist(self):
        for relative in (
            "static/css/institucional.css",
            "static/js/sobre.js",
            "static/js/contato.js",
            "static/img/institucional/logo-ifg-horizontal-branco.png",
            "static/img/institucional/daywes-pinheiro-neto.webp",
            "static/img/institucional/carlos-roberto-silveira-junior.webp",
            "static/img/institucional/alisson-vieira-da-silva.webp",
        ):
            self.assertTrue((self.root / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
