import unittest
from pathlib import Path

from PIL import Image


class HomeAssetsAndNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_home_uses_optimized_assets_and_loading_hints(self):
        html = (self.root / "templates" / "home.html").read_text(encoding="utf-8")
        self.assertIn("curve-home-main.webp", html)
        self.assertIn('fetchpriority="high"', html)
        self.assertIn('rel="preload" as="image"', html)
        for name in ("home-card-tco.webp", "home-card-depreciacao.webp", "home-card-fipe.webp"):
            self.assertIn(name, html)
        self.assertGreaterEqual(html.count('loading="lazy"'), 3)

    def test_optimized_home_assets_are_small_and_have_expected_dimensions(self):
        expected = {
            "curve-home-main.webp": (1600, 900, 100_000),
            "home-card-tco.webp": (900, 507, 50_000),
            "home-card-depreciacao.webp": (900, 507, 50_000),
            "home-card-fipe.webp": (900, 533, 50_000),
        }
        for name, (width, height, max_bytes) in expected.items():
            path = self.root / "static" / "img" / name
            self.assertTrue(path.exists(), name)
            self.assertLess(path.stat().st_size, max_bytes, name)
            with Image.open(path) as image:
                self.assertEqual(image.size, (width, height), name)

    def test_all_visible_nav_labels_use_simular_tco(self):
        for path in (self.root / "templates").glob("*.html"):
            html = path.read_text(encoding="utf-8")
            self.assertNotIn(">Simular</a>", html, path.name)
        for name in ("base.html", "home.html", "index.html", "simular.html"):
            html = (self.root / "templates" / name).read_text(encoding="utf-8")
            self.assertIn("Simular TCO", html, name)


if __name__ == "__main__":
    unittest.main()
