import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load_renderer():
    path = ROOT / "scripts" / "render_animated_diagram.py"
    spec = importlib.util.spec_from_file_location("render_animated_diagram", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CanvasPresetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_renderer()

    def test_preset_expands_to_dimensions(self):
        spec = {"canvas": {"preset": "square"}}
        self.renderer.resolve_canvas_preset(spec)
        self.assertEqual(spec["canvas"]["width"], 1080)
        self.assertEqual(spec["canvas"]["height"], 1080)

    def test_explicit_dimensions_win_over_preset(self):
        spec = {"canvas": {"preset": "wide", "width": 1280}}
        self.renderer.resolve_canvas_preset(spec)
        self.assertEqual(spec["canvas"]["width"], 1280)
        self.assertEqual(spec["canvas"]["height"], 900)

    def test_all_presets_within_limits(self):
        for name, values in self.renderer.CANVAS_PRESETS.items():
            self.assertGreaterEqual(values["width"], 480, name)
            self.assertLessEqual(values["height"], 4096, name)

    def test_unknown_preset_is_a_validation_error(self):
        spec = {"layout": "graph", "canvas": {"preset": "huge"},
                "nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
        result = self.renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertTrue(any(e["path"] == "$.canvas.preset" for e in result["errors"]), result)

    def test_known_preset_passes_validation(self):
        spec = {"layout": "graph", "canvas": {"preset": "article"},
                "nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
        self.renderer.resolve_canvas_preset(spec)
        result = self.renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)


class VendorIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_renderer()

    def setUp(self):
        self.renderer._ICON_SVG_CACHE.clear()

    def test_alias_fallback_without_vendor_pack(self):
        self.assertEqual(self.renderer.resolve_icon_name("s3"), "package")
        self.assertEqual(self.renderer.resolve_icon_name("k8s"), "cube")
        self.assertEqual(self.renderer.resolve_icon_name("aws"), "world")

    def test_vendor_file_wins_over_alias(self):
        vendor = ROOT / "assets" / "icons" / "vendor"
        pack = vendor / "testpack"
        pack.mkdir(parents=True, exist_ok=True)
        icon = pack / "s3.svg"
        icon.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M4 4h16v16H4z" fill="none" stroke="black"/></svg>',
            encoding="utf-8",
        )
        try:
            self.renderer._ICON_SVG_CACHE.clear()
            self.assertEqual(self.renderer.resolve_icon_name("s3"), "s3")
            found = self.renderer.find_icon_svg("s3")
            self.assertEqual(found, icon)
        finally:
            icon.unlink()
            pack.rmdir()
            try:
                vendor.rmdir()
            except OSError:
                pass  # README.md keeps the directory non-empty
            self.renderer._ICON_SVG_CACHE.clear()

    def test_bundled_tabler_still_found(self):
        found = self.renderer.find_icon_svg("brain")
        self.assertIsNotNone(found)
        self.assertEqual(found.parent.name, "tabler")

    def test_unknown_icon_still_warns(self):
        spec = {"layout": "graph", "nodes": [{"id": "a", "icon": "definitely-not-an-icon"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b"}]}
        result = self.renderer.validate_spec(spec)
        self.assertTrue(any("unknown icon" in w["message"] for w in result["warnings"]), result)


if __name__ == "__main__":
    unittest.main()
