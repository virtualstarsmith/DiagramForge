"""Tests for scripts/onboard_brand.py — URL -> brand theme extraction.

Color-parsing helpers run without a browser; the extraction flow is gated on
Chromium and samples a local file:// fixture, never the network.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "brand-page.html"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


onboard_brand = load_module("onboard_brand")


class ColorParsingTest(unittest.TestCase):
    def test_rgb_and_rgba(self):
        self.assertEqual((31, 41, 55), onboard_brand.parse_rgb("rgb(31, 41, 55)"))
        self.assertEqual((31, 41, 55), onboard_brand.parse_rgb("rgba(31, 41, 55, 0.9)"))

    def test_transparent_is_none(self):
        self.assertIsNone(onboard_brand.parse_rgb("rgba(0, 0, 0, 0)"))

    def test_hex_and_garbage(self):
        self.assertEqual((255, 255, 255), onboard_brand.parse_rgb("#fff"))
        self.assertIsNone(onboard_brand.parse_rgb("not-a-color"))
        self.assertIsNone(onboard_brand.parse_rgb(""))

    def test_neutral_detection(self):
        self.assertTrue(onboard_brand._is_neutral((200, 200, 200)))
        self.assertFalse(onboard_brand._is_neutral((212, 56, 13)))


class OnboardFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; needs Chromium")

    def test_extracts_fixture_brand(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme_path = Path(tmp) / "acme.json"
            url = FIXTURE.resolve().as_uri()
            rc = onboard_brand.onboard(url, slug="acme-test", out=str(theme_path))
            self.assertEqual(0, rc)
            theme = json.loads(theme_path.read_text(encoding="utf-8"))

        renderer = load_module("render_animated_diagram")
        self.assertEqual(set(renderer._THEME_KEYS), set(theme))
        self.assertEqual("#faf7f2", theme["bg"])
        self.assertEqual("#1f2937", theme["white"])
        self.assertEqual("#d4380d", theme["core_stroke"])  # button background wins

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme_path = Path(tmp) / "nope.json"
            import contextlib
            import io

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = onboard_brand.onboard(
                    FIXTURE.resolve().as_uri(), slug="dry", out=str(theme_path), dry_run=True
                )
            self.assertEqual(0, rc)
            self.assertFalse(theme_path.exists())
            receipt = json.loads(stdout.getvalue())
        self.assertTrue(receipt["dry_run"])
        self.assertIn("button background", json.dumps(receipt["roles"], ensure_ascii=False))
        self.assertIn("white_on_bg", receipt["contrast"])


if __name__ == "__main__":
    unittest.main()
