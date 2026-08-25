"""Pillow fallback rendering across every layout.

The E2E matrix exercises the browser renderer; this module exercises the
Pillow pipeline (the dependency-light fallback used when Chromium is absent),
so the per-layout ``render_*`` painters and Pillow icon/stamp code are covered.
It verifies the PNG/GIF/Excalidraw contract for the layouts Pillow supports.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAYOUTS = [
    "panorama", "swimlane", "graph", "sequence", "er", "usecase", "class",
    "activity", "state", "dfd", "deployment", "component", "package", "object",
    "composite", "profile", "communication", "timing", "interaction", "c4",
    "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone",
]
LAYOUT_SPEC = {
    "panorama": "homepage-panorama-spec.json", "swimlane": "swimlane-spec.json",
    "graph": "graph-workflow-spec.json", "sequence": "sequence-spec.json",
    "er": "er-spec.json", "usecase": "usecase-spec.json", "class": "class-spec.json",
    "activity": "activity-spec.json", "state": "state-spec.json", "dfd": "dfd-spec.json",
    "deployment": "deployment-spec.json", "component": "component-spec.json",
    "package": "package-spec.json", "object": "object-spec.json",
    "composite": "composite-spec.json", "profile": "profile-spec.json",
    "communication": "communication-spec.json", "timing": "timing-spec.json",
    "interaction": "interaction-spec.json", "c4": "c4-spec.json",
    "gantt": "gantt-spec.json", "bpmn": "bpmn-spec.json",
    "orgchart": "orgchart-spec.json", "mindmap": "mindmap-spec.json",
    "timeline": "timeline-spec.json", "fishbone": "fishbone-spec.json",
}


class PillowRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_module("render_animated_diagram")

    def test_every_layout_pillow_png_and_gif(self):
        from PIL import Image
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                spec = json.loads((EXAMPLES / LAYOUT_SPEC[layout]).read_text(encoding="utf-8"))
                # keep it fast: small frame count
                spec.setdefault("canvas", {})["frames"] = 4
                tmp = Path(tempfile.mkdtemp(prefix="pillow_"))
                result = self.renderer.write_outputs(spec, tmp, "t", icon_engine="pillow",
                                                     formats=("png", "gif", "excalidraw"))
                self.assertIn("png", result, f"{layout}: pillow png missing")
                self.assertIn("gif", result, f"{layout}: pillow gif missing")
                with Image.open(result["png"]) as im:
                    self.assertGreaterEqual(im.size[0], 400)
                    self.assertGreaterEqual(im.size[1], 300)
                with Image.open(result["gif"]) as g:
                    self.assertGreaterEqual(g.n_frames, 1)
                # Excalidraw must be valid JSON with elements
                ex = json.loads(Path(result["excalidraw"]).read_text(encoding="utf-8"))
                self.assertEqual(ex["type"], "excalidraw")
                self.assertGreater(len(ex["elements"]), 0, f"{layout}: no excalidraw elements")

    def test_pillow_skips_browser_only_formats_silently(self):
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        tmp = Path(tempfile.mkdtemp(prefix="pillow_skip_"))
        result = self.renderer.write_outputs(spec, tmp, "t", icon_engine="pillow",
                                             formats=("png", "gif", "excalidraw"))
        # Pillow result must not claim browser-only formats
        self.assertNotIn("svg", result)
        self.assertNotIn("mp4", result)


if __name__ == "__main__":
    unittest.main()
