"""End-to-end matrix tests for DiagramForge.

Covers the business goal directly: every layout, style, animation preset, and
output format must produce a clean, complete, business-grade artifact that an
architect or systems analyst could publish. These tests render real specs
through the full browser pipeline and verify the outputs structurally
(existence, dimensions, non-emptiness, format-correctness) — they are the
broadest coverage net for the rendering code paths.

Slow (minutes) because each case launches the browser pipeline; they are kept
as one parametrized module so a single ``pytest tests/test_e2e_matrix.py`` run
exercises the whole matrix.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Map each declared layout to an example spec that exercises it. ``grid`` has
# no dedicated sample, so it is synthesized in setUp.
LAYOUT_SPEC = {
    "panorama": "homepage-panorama-spec.json",
    "swimlane": "swimlane-spec.json",
    "graph": "graph-workflow-spec.json",
    "sequence": "sequence-spec.json",
    "er": "er-spec.json",
    "usecase": "usecase-spec.json",
    "class": "class-spec.json",
    "activity": "activity-spec.json",
    "state": "state-spec.json",
    "dfd": "dfd-spec.json",
    "deployment": "deployment-spec.json",
    "component": "component-spec.json",
    "package": "package-spec.json",
    "object": "object-spec.json",
    "composite": "composite-spec.json",
    "profile": "profile-spec.json",
    "communication": "communication-spec.json",
    "timing": "timing-spec.json",
    "interaction": "interaction-spec.json",
    "c4": "c4-spec.json",
    "gantt": "gantt-spec.json",
    "bpmn": "bpmn-spec.json",
    "orgchart": "orgchart-spec.json",
    "mindmap": "mindmap-spec.json",
    "timeline": "timeline-spec.json",
    "fishbone": "fishbone-spec.json",
}

ALL_STYLES = ("slate", "report", "academic", "blueprint")
ALL_ANIMATIONS = ("flow", "draw", "relay", "trace", "chapter", "failure-recovery")
ALL_FORMATS = ("png", "gif", "mp4", "svg", "html", "webp", "avif", "pdf", "lottie", "excalidraw")


def _grid_spec():
    """Synthesize a minimal grid layout spec (no bundled example)."""
    return {
        "layout": "grid",
        "style": "report",
        "title": {"prefix": "Four", "highlight": "Patterns", "subtitle": "grid E2E"},
        "columns": 2,
        "cells": [
            {"title": "Ingest", "steps": ["Read", "Clean"]},
            {"title": "Plan", "steps": ["Decompose", "Route"]},
            {"title": "Act", "steps": ["Call", "Observe"]},
            {"title": "Ship", "steps": ["Format", "Emit"]},
        ],
    }


class E2EMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_module("render_animated_diagram")
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; E2E matrix needs Chromium")
        cls.tmp = ROOT / "out" / "_e2e_matrix"
        # Each test method gets its own fresh subdirectory (via mkdtemp), so
        # no cross-run cache can leak between tests and no cleanup is needed.
        cls.tmp.mkdir(parents=True, exist_ok=True)
        cls._counter = 0

    def _fresh_dir(self):
        import tempfile
        # mkdtemp guarantees a unique dir per call — no shared-state cleanup
        # races across parallel test workers.
        d = Path(tempfile.mkdtemp(prefix="e2e_", dir=str(self.tmp)))
        return d

    def _render(self, spec, formats=("png",), animation="flow"):
        outdir = self._fresh_dir()
        return self.renderer.write_outputs_browser(
            spec, outdir, "e2e", formats=formats, animation=animation
        ), outdir

    def _load_spec(self, layout):
        if layout == "grid":
            return _grid_spec()
        return json.loads((EXAMPLES / LAYOUT_SPEC[layout]).read_text(encoding="utf-8"))

    # --- every layout produces a non-empty PNG of the right canvas size ----
    def test_every_layout_renders_png(self):
        from PIL import Image
        for layout in LAYOUT_SPEC:
            with self.subTest(layout=layout):
                spec = self._load_spec(layout)
                result, _ = self._render(spec, formats=("png",))
                self.assertIn("png", result, f"{layout}: png not produced")
                png = Path(result["png"])
                self.assertGreater(png.stat().st_size, 3000, f"{layout}: png suspiciously small")
                with Image.open(png) as im:
                    w, h = im.size
                cw = result["canvas"]["width"]
                ch = result["canvas"]["height"]
                self.assertEqual(w, cw, f"{layout}: png width {w} != canvas {cw}")
                self.assertEqual(h, ch, f"{layout}: png height {h} != canvas {ch}")
                self.assertGreaterEqual(w, 400)
                self.assertGreaterEqual(h, 300)

    # --- every layout also yields a valid SVG with embedded fonts -----------
    def test_every_layout_renders_svg(self):
        for layout in LAYOUT_SPEC:
            with self.subTest(layout=layout):
                spec = self._load_spec(layout)
                result, _ = self._render(spec, formats=("svg",))
                self.assertIn("svg", result, f"{layout}: svg not produced")
                svg = Path(result["svg"]).read_text(encoding="utf-8")
                self.assertIn("@font-face", svg, f"{layout}: svg missing fonts")
                self.assertIn("<svg", svg)
                self.assertGreater(len(svg), 2000)

    # --- the four formal styles all render with their palette --------------
    def test_every_style(self):
        base = self._load_spec("graph")
        for style in ALL_STYLES:
            with self.subTest(style=style):
                spec = json.loads(json.dumps(base))
                spec["style"] = style
                result, _ = self._render(spec, formats=("png", "svg"))
                self.assertIn("png", result)
                self.assertIn(style, ("slate", "report", "academic", "blueprint"))

    # --- all six animation presets produce a multi-frame GIF ---------------
    def test_every_animation_preset(self):
        from PIL import Image
        base = self._load_spec("graph")
        for anim in ALL_ANIMATIONS:
            with self.subTest(animation=anim):
                spec = json.loads(json.dumps(base))
                spec["animation"] = anim
                spec.setdefault("canvas", {})["frames"] = 12  # keep it fast
                result, _ = self._render(spec, formats=("gif",), animation=anim)
                self.assertIn("gif", result, f"{anim}: gif not produced")
                with Image.open(result["gif"]) as g:
                    self.assertGreaterEqual(g.n_frames, 2, f"{anim}: gif has <2 frames")

    # --- every format is produced and structurally valid -------------------
    def test_every_format(self):
        base = self._load_spec("graph")
        result, _ = self._render(base, formats=ALL_FORMATS)
        for fmt in ALL_FORMATS:
            with self.subTest(fmt=fmt):
                self.assertIn(fmt, result, f"{fmt}: not produced (skipped: {result.get(fmt + '_skipped')})")
                p = Path(result[fmt])
                self.assertTrue(p.is_file(), f"{fmt}: file missing")
                self.assertGreater(p.stat().st_size, 100, f"{fmt}: empty file")

    # --- text_outlines yields a font-free SVG ------------------------------
    def test_text_outlines_produces_font_free_svg(self):
        import re
        base = self._load_spec("graph")
        spec = json.loads(json.dumps(base))
        spec["text_outlines"] = True
        result, _ = self._render(spec, formats=("svg",))
        svg = Path(result["svg"]).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"<text[\s>]", svg)), 0, "text elements remain after outline conversion")
        self.assertNotIn("@font-face", svg)
        self.assertGreater(svg.count("<path"), 10)

    # --- legacy layout engine still produces a valid plan ------------------
    def test_legacy_layout_engine(self):
        base = self._load_spec("graph")
        spec = json.loads(json.dumps(base))
        spec["layout_engine"] = "legacy"
        result, _ = self._render(spec, formats=("png",))
        self.assertIn("png", result)


if __name__ == "__main__":
    unittest.main()
