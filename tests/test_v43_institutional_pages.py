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
        carlos = html.index("Prof. Dr. Carlos Roberto da Silveira Júnior")
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
        self.assertEqual(html.count("<dialog"), 3)


    def test_about_v43_03_compact_creator_layout_and_program_links(self):
        html = (self.templates / "sobre.html").read_text(encoding="utf-8")
        self.assertIn(">Criadores<", html)
        self.assertIn('class="creators-card card"', html)
        self.assertEqual(html.count('class="creator-profile"'), 3)
        for removed in (
            "Produto técnico de mestrado",
            "Da pesquisa à ferramenta",
            "Referências rastreáveis",
            "Orientação acadêmica",
            "Autor e desenvolvimento",
        ):
            self.assertNotIn(removed, html)
        self.assertGreater(html.index('class="card program-card"'), html.index('class="creators-card card"'))
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
        self.assertIn('class="profile-lattes-link"', html)

    def test_contact_form_does_not_post_to_unimplemented_route(self):
        html = (self.templates / "contato.html").read_text(encoding="utf-8")
        self.assertIn('id="contact-form"', html)
        self.assertNotIn('method="POST"', html)
        self.assertNotIn('action="#"', html)
        self.assertIn("O site não armazena os dados preenchidos", html)
        script = (self.root / "static" / "js" / "contato.js").read_text(encoding="utf-8")
        self.assertIn("mailto:sv.alisson@gmail.com", script)
        self.assertIn("reportValidity", script)

    def test_footer_has_ifg_logo_and_official_channels(self):
        html = (self.templates / "base.html").read_text(encoding="utf-8")
        self.assertIn("logo-ifg-horizontal.webp", html)
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
            "logo-ifg-horizontal.webp",
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
            "static/img/institucional/logo-ifg-horizontal.webp",
            "static/img/institucional/daywes-pinheiro-neto.webp",
            "static/img/institucional/carlos-roberto-silveira-junior.webp",
            "static/img/institucional/alisson-vieira-da-silva.webp",
        ):
            self.assertTrue((self.root / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
