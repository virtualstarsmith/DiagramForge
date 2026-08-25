"""Coverage for the Pillow-only rendering branches the browser E2E matrix
doesn't reach: the legacy primitive icon set, the grid layout's Pillow painter,
the legend strip, and the glyph-stamping path used when icons render via the
Pillow engine (not the browser).
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


def _grid_spec():
    return {
        "layout": "grid",
        "style": "report",
        "title": {"prefix": "Four", "highlight": "Patterns", "subtitle": "grid"},
        "columns": 2,
        "cells": [
            {"title": "Ingest", "steps": ["Read", "Clean"]},
            {"title": "Plan", "steps": ["Decompose", "Route"]},
            {"title": "Act", "steps": ["Call", "Observe"]},
            {"title": "Ship", "steps": ["Format", "Emit"]},
        ],
    }


class PillowBranchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def test_grid_layout_pillow_renders(self):
        from PIL import Image
        tmp = Path(tempfile.mkdtemp(prefix="grid_pil_"))
        result = self.rad.write_outputs(_grid_spec(), tmp, "g", icon_engine="pillow",
                                        formats=("png", "gif", "excalidraw"))
        self.assertIn("png", result)
        with Image.open(result["png"]) as im:
            self.assertGreaterEqual(im.size[0], 400)

    def test_legend_renders_when_present(self):
        from PIL import Image
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec["legend"] = [{"label": "data", "color": "green"}, {"label": "control", "color": "cyan"}]
        spec.setdefault("canvas", {})["frames"] = 4
        tmp = Path(tempfile.mkdtemp(prefix="legend_pil_"))
        result = self.rad.write_outputs(spec, tmp, "l", icon_engine="pillow", formats=("png",))
        self.assertIn("png", result)
        with Image.open(result["png"]) as im:
            self.assertGreaterEqual(im.size[1], 300)

    def test_primitive_icons_cover_all_kinds(self):
        # draw_primitive_icon handles the legacy fallback glyphs; exercise each
        # known kind through a pillow render of a spec that uses them.
        kinds = ["folder", "file", "scan", "shield", "db", "hash", "package"]
        for kind in kinds:
            with self.subTest(kind=kind):
                spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
                spec["nodes"][0]["icon"] = kind
                spec.setdefault("canvas", {})["frames"] = 2
                tmp = Path(tempfile.mkdtemp(prefix="prim_"))
                result = self.rad.write_outputs(spec, tmp, "t", icon_engine="pillow", formats=("png",))
                self.assertIn("png", result)

    def test_custom_icon_file_stamps(self):
        # icon_file with a local SVG exercises the custom-icon resolution path.
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        icon_src = ROOT / "assets" / "icons" / "tabler" / "api.svg"
        if not icon_src.is_file():
            self.skipTest("no bundled tabler api icon")
        spec["nodes"][0]["icon_file"] = str(icon_src)
        spec.setdefault("canvas", {})["frames"] = 2
        tmp = Path(tempfile.mkdtemp(prefix="custom_"))
        result = self.rad.write_outputs(spec, tmp, "t", icon_engine="pillow", formats=("png",))
        self.assertIn("png", result)


if __name__ == "__main__":
    unittest.main()
