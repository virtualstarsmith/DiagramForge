"""Coverage for the opt-in rAF raster capture path (capture_frames_raster).

The default pipeline uses per-frame page.screenshot; capture_frames_raster is
only exercised when a spec sets fast_capture: true, so it needs a dedicated
test that calls it directly through write_outputs_browser.
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


class FastCaptureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        cls.svg = load_module("svg_renderer")
        if not cls.svg.is_available():
            raise unittest.SkipTest("browser renderer unavailable")
        # opentype.js must be bundled for the raster path to engage
        if not (ROOT / "assets" / "vendor" / "opentype.min.js").is_file():
            raise unittest.SkipTest("opentype.js not bundled")

    def test_fast_capture_produces_gif(self):
        from PIL import Image
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec["fast_capture"] = True
        spec.setdefault("canvas", {})["frames"] = 6
        tmp = Path(tempfile.mkdtemp(prefix="fastcap_"))
        result = self.rad.write_outputs_browser(spec, tmp, "f", formats=("gif",))
        self.assertIn("gif", result)
        with Image.open(result["gif"]) as g:
            self.assertGreaterEqual(g.n_frames, 2)

    def test_fast_capture_with_text_outlines(self):
        # fast_capture already converts text to outlines internally; combining
        # with text_outlines must not double-convert or crash.
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec["fast_capture"] = True
        spec["text_outlines"] = True
        spec.setdefault("canvas", {})["frames"] = 4
        tmp = Path(tempfile.mkdtemp(prefix="fastcap_to_"))
        result = self.rad.write_outputs_browser(spec, tmp, "f", formats=("gif", "svg"))
        self.assertIn("gif", result)
        self.assertIn("svg", result)
        svg = Path(result["svg"]).read_text(encoding="utf-8")
        self.assertNotIn("@font-face", svg)  # text_outlines dropped fonts


if __name__ == "__main__":
    unittest.main()
