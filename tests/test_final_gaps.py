"""Targeted coverage for small-module edge branches.

Covers the remaining uncovered lines in svg_optimize, lottie_export,
prepare_fonts, elk_layout, and render_cache that the feature tests do not
reach: error fallbacks, short-input guards, and format parsing edges.
"""
import importlib.util
import shutil
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


class SvgOptimizeEdgesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.so = load_module("svg_optimize")

    def test_collect_codepoints_line_label_and_titles(self):
        doc = {
            "ops": [
                {"op": "text", "text": "ab"},
                {"op": "signature", "text": "sig"},
                {"op": "line", "label": "edge"},
                {"op": "rect"},
            ],
            "title": {"prefix": "Pre", "highlight": "High"},
            "subtitle": "plain string",
        }
        cps = self.so.collect_codepoints(doc)
        for ch in "absigedgePreHighplainstring":
            self.assertIn(ord(ch), cps)

    def test_subset_font_to_ttf_returns_bytes(self):
        font = ROOT / "assets" / "fonts" / "Excalifont-Regular.ttf"
        if not font.is_file():
            raise unittest.SkipTest("Excalifont ttf missing")
        data = self.so.subset_font_to_ttf(font, {ord("A"), ord("B")})
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 100)

    def test_subset_font_requires_fonttools(self):
        with mock.patch.object(self.so, "_HAS_FONTTOOLS", False):
            with self.assertRaises(RuntimeError):
                self.so._subset_font(Path("x.ttf"), {65}, None)

    def test_build_subset_font_css_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as d:
            css = self.so.build_subset_font_css({65}, Path(d))
        self.assertEqual(css, "")

    def test_build_subset_font_css_falls_back_to_full_font(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake = d / "Excalifont-Regular.woff2"
            fake.write_bytes(b"full-font-bytes")
            with mock.patch.object(self.so, "subset_font_to_woff2", side_effect=ValueError("bad font")):
                css = self.so.build_subset_font_css({65}, d)
        import base64
        self.assertIn(base64.b64encode(b"full-font-bytes").decode("ascii"), css)

    def test_optimize_svg_keeps_non_font_style_blocks(self):
        svg = '<svg><style id="anim">.x{animation:a 1s}</style></svg>'
        out = self.so.optimize_svg(svg, {"ops": []}, ROOT / "assets" / "fonts")
        self.assertIn("animation:a 1s", out)

    def test_optimize_svg_failure_returns_minified_original(self):
        svg = "<svg><!--c--><style>@font-face{font-family:Excalifont}</style></svg>"
        with mock.patch.object(self.so, "build_subset_font_css", side_effect=RuntimeError("boom")):
            out = self.so.optimize_svg(svg, {"ops": []}, ROOT / "assets" / "fonts")
        self.assertNotIn("<!--c-->", out)  # still minified
        self.assertIn("@font-face", out)  # original css preserved


class LottieEdgesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.le = load_module("lottie_export")

    def test_hex_to_rgb_falsy_and_none(self):
        self.assertIsNone(self.le._hex_to_rgb(""))
        self.assertIsNone(self.le._hex_to_rgb("none"))
        self.assertIsNone(self.le._hex_to_rgb("transparent"))

    def test_hex_to_rgb_short_hex_expands(self):
        self.assertEqual(self.le._hex_to_rgb("#abc"), [0xAA / 255, 0xBB / 255, 0xCC / 255])

    def test_hex_to_rgb_invalid_hex_falls_back_white(self):
        self.assertEqual(self.le._hex_to_rgb("#zzzzzz"), [1.0, 1.0, 1.0])

    def test_hex_to_rgb_rgb_function(self):
        self.assertEqual(self.le._hex_to_rgb("rgb(255, 0, 128)"), [1.0, 0.0, 128 / 255.0])

    def test_hex_to_rgb_unknown_falls_back_white(self):
        self.assertEqual(self.le._hex_to_rgb("chartreuse"), [1.0, 1.0, 1.0])

    def test_color_kv_none_becomes_white(self):
        kv = self.le._color_kv(None)
        self.assertEqual(kv["k"], [1.0, 1.0, 1.0, 1.0])

    def test_line_layer_requires_two_points(self):
        self.assertIsNone(self.le._line_layer(1, {"kind": "line", "points": [[0, 0]]}, 10))

    def test_sample_polyline_short_input_repeats_first(self):
        out = self.le._sample_polyline([[3, 4]], 3)
        self.assertEqual(out, [[3, 4], [3, 4], [3, 4]])

    def test_sample_polyline_tail_clamps_to_last_point(self):
        # Degenerate zero-length polyline: total falls back to 1.0 but every
        # segment is 0, so targets beyond the first hit the overshoot branch
        # that appends the final point.
        out = self.le._sample_polyline([[5, 5], [5, 5]], 3)
        self.assertEqual(out, [[5, 5], [5, 5], [5, 5]])

    def test_flow_dot_layer_requires_two_points(self):
        self.assertIsNone(
            self.le._flow_dot_layer(1, {"points": [[0, 0]]}, {}, 10)
        )

    def test_pulse_layer_requires_box(self):
        self.assertIsNone(self.le._pulse_layer(1, {"pulse": {}}, {}, 10))


class PrepareFontsEdgesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pf = load_module("prepare_fonts")

    def test_coverage_ranges_extends_adjacent(self):
        self.assertEqual(self.pf.coverage_ranges({1, 2, 3, 7}), [[1, 3], [7, 7]])

    def test_main_converts_excalifont_when_woff2_present(self):
        src_woff2 = ROOT / "assets" / "fonts" / "Excalifont-Regular.woff2"
        if not src_woff2.is_file():
            raise unittest.SkipTest("Excalifont woff2 missing")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            shutil.copy(src_woff2, d / "Excalifont-Regular.woff2")
            argv = ["prepare_fonts.py", str(d / "no-such-var-font.ttf")]
            with mock.patch.object(self.pf, "FONT_DIR", d), \
                 mock.patch.object(sys, "argv", argv), \
                 self.assertRaises(SystemExit) as ctx:
                self.pf.main()
            # exits 1 on the missing variable font, but only *after* the
            # Excalifont conversion branch ran
            self.assertEqual(ctx.exception.code, 1)
            self.assertTrue((d / "Excalifont-Regular.ttf").is_file())


class ElkLayoutEdgesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elk = load_module("elk_layout")

    def test_is_available_reflects_bundled_file(self):
        self.assertEqual(self.elk.is_available(), self.elk.ELK_JS.is_file())

    def test_layout_graph_returns_none_without_elk(self):
        with mock.patch.object(self.elk, "ELK_JS", Path("/nonexistent/elk.min.js")):
            self.assertIsNone(self.elk.layout_graph([], []))

    def test_layout_graph_returns_none_on_browser_failure(self):
        # elk_layout imports sync_playwright lazily inside layout_graph; make
        # that import's symbol raise to exercise the except->None fallback.
        fake_sync = mock.MagicMock(side_effect=RuntimeError("no browser"))
        fake_module = mock.MagicMock(sync_playwright=fake_sync)
        with mock.patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
            result = self.elk.layout_graph([{"id": "a", "label": "A", "w": 10, "h": 10}], [])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
