"""Tests for validate_spec — the pre-flight checker that gates rendering.

Exercises every error and warning branch so bad specs fail fast with an
actionable message before Chromium is ever launched. This is the main
coverage net for render_animated_diagram.py's validation logic.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ok_spec(layout="graph"):
    """A minimal valid spec for the given layout."""
    base = {
        "layout": layout,
        "style": "slate",
        "animation": "flow",
        "title": {"prefix": "X", "highlight": "Y"},
    }
    if layout == "graph":
        base["nodes"] = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
        base["edges"] = [{"from": "a", "to": "b"}]
    elif layout == "sequence":
        base["participants"] = [{"id": "a", "label": "A"}]
        base["messages"] = [{"from": "a", "to": "a", "kind": "self"}]
    elif layout == "panorama":
        base["core"] = [{"id": "c", "label": "C"}]
    return base


class ValidateSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        # staticmethod so `self.validate(spec)` does not bind `self` as the spec arg
        cls.validate = staticmethod(cls.rad.validate_spec)

    def _errors(self, spec):
        return [e["path"] for e in self.validate(spec)["errors"]]

    def _warnings(self, spec):
        return [w["path"] for w in self.validate(spec)["warnings"]]

    def test_valid_spec_has_no_errors(self):
        r = self.validate(_ok_spec())
        self.assertTrue(r["ok"], msg=r["errors"])
        self.assertEqual(r["errors"], [])

    def test_non_object_spec_errors(self):
        r = self.validate("not an object")
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["path"], "$")

    def test_title_must_be_object(self):
        s = _ok_spec(); s["title"] = "flat"
        self.assertIn("$.title", self._errors(s))

    def test_canvas_must_be_object(self):
        s = _ok_spec(); s["canvas"] = "big"
        self.assertIn("$.canvas", self._errors(s))

    def test_core_must_be_object(self):
        s = _ok_spec("panorama"); s["core"] = "x"
        self.assertIn("$.core", self._errors(s))

    def test_unknown_canvas_preset_errors(self):
        s = _ok_spec(); s["canvas"] = {"preset": "giant"}
        self.assertIn("$.canvas.preset", self._errors(s))

    def test_known_canvas_preset_ok(self):
        s = _ok_spec(); s["canvas"] = {"preset": "wide"}
        self.assertNotIn("$.canvas.preset", self._errors(s))

    def test_canvas_width_out_of_range(self):
        s = _ok_spec(); s["canvas"] = {"width": 10}
        self.assertIn("$.canvas.width", self._errors(s))

    def test_canvas_height_out_of_range(self):
        s = _ok_spec(); s["canvas"] = {"height": 99999}
        self.assertIn("$.canvas.height", self._errors(s))

    def test_canvas_fps_out_of_range(self):
        s = _ok_spec(); s["canvas"] = {"fps": 0}
        self.assertIn("$.canvas.fps", self._errors(s))

    def test_canvas_frames_out_of_range(self):
        s = _ok_spec(); s["canvas"] = {"frames": 1}
        self.assertIn("$.canvas.frames", self._errors(s))

    def test_unknown_density_errors(self):
        s = _ok_spec(); s["density"] = "huge"
        self.assertIn("$.density", self._errors(s))

    def test_unknown_aspect_ratio_errors(self):
        s = _ok_spec(); s["aspect_ratio"] = "round"
        self.assertIn("$.aspect_ratio", self._errors(s))

    def test_unknown_motion_level_errors(self):
        s = _ok_spec(); s["motion_level"] = "wild"
        self.assertIn("$.motion_level", self._errors(s))

    def test_unknown_layout_errors(self):
        s = _ok_spec(); s["layout"] = "martini"
        self.assertIn("$.layout", self._errors(s))

    def test_unknown_style_errors(self):
        s = _ok_spec(); s["style"] = "neon"
        self.assertIn("$.style", self._errors(s))

    def test_unknown_animation_errors(self):
        s = _ok_spec(); s["animation"] = "spin"
        self.assertIn("$.animation", self._errors(s))

    def test_unknown_key_warns(self):
        s = _ok_spec(); s["bogus_key"] = 1
        self.assertIn("$.bogus_key", self._warnings(s))

    def test_long_signature_warns(self):
        s = _ok_spec(); s["signature"] = "x" * 40
        self.assertIn("$.signature", self._warnings(s))

    def test_unknown_icon_warns(self):
        s = _ok_spec("graph")
        s["nodes"][0]["icon"] = "nonexistent_icon_xyz"
        self.assertIn("$.nodes[0].icon", self._warnings(s))

    def test_known_icon_no_warning(self):
        s = _ok_spec("graph")
        s["nodes"][0]["icon"] = "brain"
        self.assertNotIn("$.nodes[0].icon", self._warnings(s))

    def test_bad_icon_file_extension_errors(self):
        s = _ok_spec("graph")
        s["nodes"][0]["icon_file"] = "logo.jpeg"
        self.assertIn("$.nodes[0].icon_file", self._errors(s))

    def test_missing_icon_file_errors(self):
        s = _ok_spec("graph")
        s["nodes"][0]["icon_file"] = "does-not-exist.svg"
        self.assertIn("$.nodes[0].icon_file", self._errors(s))

    def test_all_declared_layouts_accepted(self):
        for layout in self.rad.graph_model.LAYOUTS:
            with self.subTest(layout=layout):
                s = _ok_spec(layout)
                # layout value itself must never error (content may, but not the layout key)
                self.assertNotIn("$.layout", self._errors(s))

    def test_all_styles_accepted(self):
        for style in self.rad.STYLE_THEMES:
            with self.subTest(style=style):
                s = _ok_spec(); s["style"] = style
                self.assertNotIn("$.style", self._errors(s))

    def test_all_animations_accepted(self):
        for anim in self.rad.ANIMATION_CHOICES:
            with self.subTest(animation=anim):
                s = _ok_spec(); s["animation"] = anim
                self.assertNotIn("$.animation", self._errors(s))

    def test_returns_warnings_list(self):
        r = self.validate(_ok_spec())
        self.assertIn("warnings", r)
        self.assertIsInstance(r["warnings"], list)


if __name__ == "__main__":
    unittest.main()
