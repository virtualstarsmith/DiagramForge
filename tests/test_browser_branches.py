"""Browser-pipeline branch coverage: exception fallbacks inside
svg_renderer.render_all and render_animated_diagram.write_outputs_browser
that only execute with a live Chromium plus a mocked failure.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rad = load_module("render_animated_diagram")
sr = load_module("svg_renderer")

SPEC = {
    "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
    "canvas": {"frames": 2, "fps": 10},
    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    "edges": [{"from": "a", "to": "b"}],
}


def real_doc():
    """A genuine ops document for SPEC (render_all needs the full schema)."""
    _ex, _static, doc = rad.render_static_with_ops(dict(SPEC))
    return doc


@unittest.skipUnless(sr.is_available(), "browser renderer unavailable")
class BrowserBranchTest(unittest.TestCase):
    def test_svg_optimize_failure_falls_back(self):
        bad = mock.MagicMock()
        bad_optimize = mock.MagicMock(side_effect=RuntimeError("optimizer exploded"))
        bad.optimize_svg = bad_optimize
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(sys.modules, {"svg_optimize": bad}):
            result = sr.render_all(real_doc(), Path(d), "t", formats=("svg",))
        self.assertIn("svg", result)

    def test_text_outlines_failure_falls_back(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(sr, "svg_text_to_path", side_effect=RuntimeError("ot exploded")):
            result = sr.render_all(real_doc(), Path(d), "t", formats=("svg",), text_outlines=True)
        self.assertIn("svg", result)

    def test_avif_unsupported_is_skipped(self):
        from PIL import Image
        real_save = Image.Image.save

        def guarded_save(self, fp, format=None, **kw):
            if (format or "").upper() == "AVIF":
                raise OSError("no libavif")
            return real_save(self, fp, format=format, **kw)

        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(Image.Image, "save", guarded_save):
            result = sr.render_all(real_doc(), Path(d), "t", formats=("png", "avif"))
        self.assertIn("png", result)
        self.assertIn("avif_skipped", result)

    def test_mp4_encode_failure_is_skipped(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(sr, "_encode_mp4", return_value=False):
            result = sr.render_all(real_doc(), Path(d), "t", formats=("mp4",))
        self.assertEqual(result.get("mp4_skipped"), "ffmpeg unavailable or failed")

    def test_cache_hit_skips_chromium(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            first = rad.write_outputs_browser(dict(SPEC), d, "t", formats=("png",))
            self.assertIn("png", first)
            second = rad.write_outputs_browser(dict(SPEC), d, "t", formats=("png",))
            self.assertTrue(second.get("cached"), "second render should hit the cache")

    def test_lottie_failure_is_skipped(self):
        if rad.lottie_export is None:
            raise unittest.SkipTest("lottie_export unavailable")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(rad.lottie_export, "export_lottie",
                               side_effect=RuntimeError("lottie exploded")):
            result = rad.write_outputs_browser(dict(SPEC), Path(d), "t", formats=("png", "lottie"))
        self.assertIn("png", result)
        self.assertIn("lottie_skipped", result)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(sr.is_available(), "browser renderer unavailable")
class BrowserGlyphRequestTest(unittest.TestCase):
    def test_render_browser_glyphs_with_real_requests(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A", "icon": "gear"}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
        }
        out = rad.render_browser_glyphs(spec)
        self.assertTrue(out, "expected glyph frames for the bundled gear icon")
