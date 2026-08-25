"""Targeted coverage for the uncovered rendering branches:
- draw_primitive_icon (the legacy fallback glyph set)
- stamp_glyphs + collect_icon_instances + icon_requests (browser-glyph Pillow overlay)
- graph_layout_checks / _graph_content_bounds (browser-path validation)
- render_browser_glyphs / spec_uses_illustrations (icon-engine selection)

These call the functions directly with constructed ex/draw objects so the
previously-unreachable lines execute in-process.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canvas_and_draw(w=200, h=200):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), "#0f172a")
    return img, ImageDraw.Draw(img)


class PrimitiveIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def _ex(self):
        return self.rad.Excal(200, 200)

    def test_each_primitive_icon_kind(self):
        for kind in ("folder", "file", "scan", "shield", "db", "hash", "package", "unknown_kind"):
            with self.subTest(kind=kind):
                img, draw = _canvas_and_draw()
                ex = self._ex()
                self.rad.draw_primitive_icon(ex, draw, kind, 10, 10)
                # the unknown kind hits the else branch (a plain circle)
                self.assertGreaterEqual(len(ex.elements), 1)

    def test_primitive_icon_custom_color_and_scale(self):
        img, draw = _canvas_and_draw()
        ex = self._ex()
        self.rad.draw_primitive_icon(ex, draw, "folder", 0, 0, color="#ff0000", scale=0.5)
        self.assertGreaterEqual(len(ex.elements), 1)


class GlyphStampTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def test_stamp_glyphs_no_frames_returns_base(self):
        img, _ = _canvas_and_draw()
        result = self.rad.stamp_glyphs(img, {"layout": "graph", "nodes": [], "edges": []}, {}, 0.0)
        self.assertIs(result, img)

    def test_stamp_glyphs_with_frames_composites(self):
        from PIL import Image
        img, _ = _canvas_and_draw()
        # build a minimal glyph_frames mapping keyed as stamp_glyphs expects
        glyph = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
        frames = {(self.rad.resolve_icon_name("brain"), "#86b300"): [glyph] * 4}
        spec = {
            "layout": "graph",
            "nodes": [{"id": "n", "label": "N", "icon": "brain", "color": "#86b300"}],
            "edges": [],
        }
        out = self.rad.stamp_glyphs(img, spec, frames, 0.0)
        self.assertIsNotNone(out)
        self.assertEqual(out.mode, "RGB")

    def test_collect_icon_instances_from_spec(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": "a", "label": "A", "icon": "brain"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        insts = self.rad.collect_icon_instances(spec)
        # only the icon-bearing node should appear
        self.assertTrue(any(i.get("kind") == "brain" or "brain" in str(i) for i in insts))

    def test_icon_requests_dedupes(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": "a", "label": "A", "icon": "brain"}, {"id": "b", "label": "B", "icon": "brain"}],
            "edges": [],
        }
        reqs = self.rad.icon_requests(spec)
        # same icon+color deduped
        self.assertEqual(len(reqs), len(set(reqs)))

    def test_spec_uses_illustrations_detects_style(self):
        self.assertTrue(self.rad.spec_uses_illustrations({"icon_style": "illustrated"}))
        self.assertTrue(self.rad.spec_uses_illustrations({"nodes": [{"icon_style": "hero"}]}))
        self.assertFalse(self.rad.spec_uses_illustrations({"icon_style": "outline"}))
        self.assertFalse(self.rad.spec_uses_illustrations({"nodes": []}))

    def test_render_browser_glyphs_empty_spec(self):
        # no icons -> no glyph requests -> empty mapping
        r = self.rad.render_browser_glyphs({"layout": "graph", "nodes": [], "edges": []})
        self.assertEqual(r, {})


class GraphLayoutChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        cls.gm = load_module("graph_model")

    def test_non_graph_layout_returns_no_checks(self):
        for layout in ("panorama", "swimlane", "sequence"):
            self.assertEqual(self.rad.graph_layout_checks({"layout": layout}), [])

    def test_graph_layout_produces_checks(self):
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        checks = self.rad.graph_layout_checks(spec)
        self.assertGreaterEqual(len(checks), 2)
        names = {c["name"] for c in checks}
        self.assertIn("graph_content_inside_canvas", names)
        self.assertIn("graph_vertical_balance", names)
        self.assertIn("graph_long_chain_orientation", names)

    def test_graph_content_bounds_computed(self):
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        plan = self.gm.build_plan(spec)
        bounds = self.rad._graph_content_bounds(plan)
        self.assertIsNotNone(bounds)
        left, top, right, bottom = bounds
        self.assertLess(left, right)
        self.assertLess(top, bottom)

    def test_graph_content_bounds_empty(self):
        empty_plan = {"graph_nodes": [], "graph_groups": [], "graph_edges": []}
        self.assertIsNone(self.rad._graph_content_bounds(empty_plan))


if __name__ == "__main__":
    unittest.main()
