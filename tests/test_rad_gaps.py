"""Targeted branch coverage for render_animated_diagram helpers and main().

Covers the defensive and rarely-hit branches the feature tests miss:
style/preset rejection, font and icon fallback chains, SVG shape tags,
icon-motion kinds, glyph stamping edge cases, check_outputs for every
format, and main()'s warning/exit paths.
"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rad = load_module("render_animated_diagram")


def fresh_draw():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 200), "#000000")
    return ImageDraw.Draw(img)


class StyleAndFontFallbackTest(unittest.TestCase):
    def tearDown(self):
        rad.apply_style("slate")

    def test_unknown_style_raises(self):
        with self.assertRaises(SystemExit):
            rad.apply_style("nonexistent-style")

    def test_unknown_canvas_preset_ignored(self):
        spec = {"canvas": {"preset": "no-such-preset"}}
        rad.resolve_canvas_preset(spec)
        self.assertNotIn("width", spec["canvas"])

    def test_cjk_coverage_corrupt_json_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "notosanssc-coverage.json").write_text("{corrupt", encoding="utf-8")
            with mock.patch.object(rad, "FONT_DIR", Path(d)), \
                 mock.patch.object(rad, "_CJK_COVERAGE_RANGES", None), \
                 mock.patch.object(rad, "_CJK_COVERAGE_STARTS", None):
                ranges, starts = rad.cjk_coverage_ranges()
                self.assertEqual(ranges, [])
                self.assertFalse(rad.bundled_cjk_covers("中文"))

    def test_wrap_token_empty_and_text_variants_no_wrap(self):
        draw = fresh_draw()
        font = rad.load_font(12) if hasattr(rad, "load_font") else None
        from PIL import ImageFont
        font = font or ImageFont.load_default()
        self.assertEqual(rad.wrap_token(draw, "", font, 100), [""])
        self.assertEqual(rad.text_variants(draw, "raw", font, 100, wrap=False), ["raw"])


class IconFallbackTest(unittest.TestCase):
    def test_find_icon_svg_rejects_empty_and_custom(self):
        self.assertIsNone(rad.find_icon_svg(None))
        self.assertIsNone(rad.find_icon_svg("@custom/x.png"))

    def test_load_svg_icon_needs_parse_path(self):
        with mock.patch.object(rad, "parse_path", None):
            rad.SVG_ICON_CACHE.clear()
            self.assertIsNone(rad.load_svg_icon("gear", "#ffffff", 32))

    def test_load_svg_icon_unknown_and_render_failure(self):
        rad.SVG_ICON_CACHE.clear()
        self.assertIsNone(rad.load_svg_icon("definitely-not-an-icon", "#fff", 32))
        with mock.patch.object(rad, "render_svg_outline", side_effect=ValueError("bad svg")):
            rad.SVG_ICON_CACHE.clear()
            self.assertIsNone(rad.load_svg_icon("gear", "#ffffff", 32))

    def test_svg_number_default(self):
        self.assertEqual(rad.svg_number(None, 7.5), 7.5)

    def test_single_point_polyline_draws_dot(self):
        draw = fresh_draw()
        rad.draw_svg_polyline(draw, [(50, 50)], "#ffffff", 4)  # must not raise

    def test_sample_svg_segment_length_failure(self):
        class BadSegment:
            def length(self, error=1e-3):
                raise RuntimeError("no length")

            def point(self, t):
                return complex(t * 8, t * 8)

        pts = rad.sample_svg_segment(BadSegment(), 1.0, 0)
        self.assertTrue(pts)

    def test_draw_svg_shape_all_tags(self):
        draw = fresh_draw()
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<line x1="1" y1="2" x2="10" y2="20"/>'
            '<polyline points="1,1 5,5 9,1"/>'
            '<polygon points="2,2 6,6 2,6"/>'
            '<circle cx="10" cy="10" r="4"/>'
            '<rect x="2" y="2" width="8" height="6" rx="1"/>'
            '<path d="M0 0 L5 5"/>'
            "</svg>"
        )
        root = ElementTree.fromstring(svg)
        for element in root:
            rad.draw_svg_shape(draw, element, "#ffffff", 2, 1.0, 0)

    def test_svg_icon_tile_returns_false_when_unloadable(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (120, 120))
        draw = ImageDraw.Draw(img)
        draw._image = img
        ok = rad.draw_svg_icon_tile(mock.MagicMock(), draw, "definitely-not-an-icon", 10, 10, "#ffffff", 1.0)
        self.assertFalse(ok)

    def test_custom_icon_image_missing_and_svg_failure(self):
        rad.SVG_ICON_CACHE.clear()
        self.assertIsNone(rad.load_custom_icon_image(Path("/nope/x.png"), 32))
        with tempfile.TemporaryDirectory() as d:
            svg = Path(d) / "icon.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L4 4"/></svg>',
                           encoding="utf-8")
            with mock.patch.object(rad, "render_svg_outline", side_effect=ValueError("x")):
                rad.SVG_ICON_CACHE.clear()
                self.assertIsNone(rad.load_custom_icon_image(svg, 32))
            # success path through the svg branch
            rad.SVG_ICON_CACHE.clear()
            if rad.parse_path is not None:
                img = rad.load_custom_icon_image(svg, 32)
                self.assertIsNotNone(img)
                cached = rad.load_custom_icon_image(svg, 32)  # cache hit
                self.assertIsNotNone(cached)

    def test_icon_motion_package_and_hash_kinds(self):
        draw = fresh_draw()
        for kind in ("package", "hash", "scan", "shield", "db", "folder", "file"):
            rad.draw_icon_specific_motion(draw, kind, 10, 10, 1.0, "#ffffff", 0.3, 0.7, active=True)
        # inactive returns immediately
        rad.draw_icon_specific_motion(draw, "package", 10, 10, 1.0, "#ffffff", 0.3, 0.7, active=False)


class GlyphStampBranchTest(unittest.TestCase):
    def test_icon_requests_skips_custom_icons(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A", "icon": "@custom/icon.png"}],
            "steps": [{"label": "B", "icon": "gear"}],
            "outputs": [{"label": "C"}],
        }
        requests = rad.icon_requests(spec)
        kinds = {k for k, _color in requests}
        self.assertNotIn("@custom/icon.png", kinds)

    def test_stamp_glyphs_edge_cases(self):
        from PIL import Image
        base = Image.new("RGB", (400, 300), "#101010")
        self.assertIs(rad.stamp_glyphs(base, {"layout": "panorama"}, {}, 0.0), base)
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A", "icon": "gear"}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
        }
        # key present but empty sequence -> skip; and a key that matches a
        # real icon gets stamped.
        key = (rad.resolve_icon_name("gear"), rad.THEME["cyan"])
        out = rad.stamp_glyphs(base, spec, {key: []}, 0.0)
        self.assertIsNotNone(out)
        glyph = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        out = rad.stamp_glyphs(base, spec, {key: [glyph] * 2}, 0.5)
        self.assertIsNotNone(out)

    def test_render_browser_glyphs_unavailable_and_empty(self):
        with mock.patch.object(rad, "icon_browser", None):
            self.assertEqual(rad.render_browser_glyphs({"layout": "panorama"}), {})
        if rad.icon_browser is not None and rad.icon_browser.is_available():
            with mock.patch.object(rad, "icon_requests", return_value=[]):
                self.assertEqual(rad.render_browser_glyphs({"layout": "graph"}), {})


class WriteOutputsBranchTest(unittest.TestCase):
    def test_browser_engine_fallback_warning(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"frames": 2},
            "inputs": [{"label": "A", "icon": "gear"}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
        }
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(rad, "render_browser_glyphs", return_value={}), \
             redirect_stderr(buf):
            result = rad.write_outputs(spec, Path(d), "t", icon_engine="browser", formats=("png",))
        self.assertIn("png", result)
        self.assertIn("browser icon engine unavailable", buf.getvalue())

    def test_browser_glyph_stamping_path(self):
        from PIL import Image
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"frames": 2},
            "inputs": [{"label": "A", "icon": "gear"}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
        }
        key = (rad.resolve_icon_name("gear"), rad.THEME["cyan"])
        glyph = Image.new("RGBA", (24, 24), (255, 0, 0, 255))
        fake_frames = {key: [glyph] * 4}
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(rad, "render_browser_glyphs", return_value=fake_frames):
            result = rad.write_outputs(spec, Path(d), "t", icon_engine="browser",
                                       formats=("png", "gif"))
        self.assertIn("png", result)
        self.assertIn("gif", result)


class CheckOutputsFormatsTest(unittest.TestCase):
    """check_outputs branches for mp4/webp/avif/pdf/lottie/text-outlined svg."""

    def _spec(self, **over):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 1210, "height": 760, "fps": 12, "frames": 6},
            "nodes": [{"id": "a", "label": "A"}],
        }
        spec.update(over)
        return spec

    def test_all_format_checks(self):
        from PIL import Image
        import shutil
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            img = Image.new("RGB", (1210, 760), "#202020")
            png = d / "x.png"; img.save(png)
            gif = d / "x.gif"
            # distinct frames: Pillow collapses identical frames into one
            frames6 = [Image.new("RGB", (1210, 760), (20 + i * 30, 32, 32)) for i in range(6)]
            frames6[0].save(gif, save_all=True, append_images=frames6[1:])
            webp = d / "x.webp"; img.save(webp, "WEBP")
            avif = d / "x.avif"
            try:
                img.save(avif, "AVIF")
            except Exception:
                avif = None
            pdf = d / "x.pdf"; pdf.write_bytes(b"%PDF-1.4 fake")
            lottie = d / "x.json"
            lottie.write_text(json.dumps({"v": "5.7.6", "w": 1, "h": 1, "layers": [1]}))
            svg = d / "x.svg"; svg.write_text("<svg><path d='M0 0L1 1'/></svg>")
            html = d / "x.html"; html.write_text("<html><svg></svg></html>")
            result = {"png": str(png), "gif": str(gif), "webp": str(webp),
                      "pdf": str(pdf), "lottie": str(lottie), "svg": str(svg),
                      "html": str(html)}
            if avif:
                result["avif"] = str(avif)
            # real mp4 via ffmpeg when present, else a stub (mp4_exists still runs)
            mp4 = d / "x.mp4"
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                import subprocess
                subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.2",
                                "-pix_fmt", "yuv420p", str(mp4)],
                               capture_output=True)
            if not mp4.is_file():
                mp4.write_bytes(b"\x00" * 2048)
            result["mp4"] = str(mp4)
            checks = rad.check_outputs(result, self._spec())
            names = {c["name"] for c in checks["checks"]}
            self.assertIn("webp_exists", names)
            self.assertIn("pdf_exists", names)
            self.assertIn("lottie_exists", names)
            self.assertIn("mp4_exists", names)

    def test_svg_text_outlined_check(self):
        with tempfile.TemporaryDirectory() as d:
            svg = Path(d) / "x.svg"
            svg.write_text("<svg><path d='M0 0L1 1'/></svg>", encoding="utf-8")
            checks = rad.check_outputs({"svg": str(svg)}, self._spec(text_outlines=True))
            names = {c["name"] for c in checks["checks"]}
            self.assertIn("svg_text_outlined", names)

    def test_probe_mp4_without_ffprobe(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(rad._probe_mp4(Path("whatever.mp4")))

    def test_graph_layout_checks_with_groups(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "groups": [{"id": "g", "label": "G", "members": ["a", "b"]}],
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        checks = rad.graph_layout_checks(spec)
        self.assertIsInstance(checks, list)

    def test_missing_requested_formats(self):
        self.assertEqual(rad.missing_requested_formats({"png": 1}, ("png", "gif")), ["gif"])


class MainBranchTest(unittest.TestCase):
    def _write_spec(self, d, spec):
        p = Path(d) / "spec.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        return p

    def _run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
            try:
                rad.main()
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_validation_warnings_print_and_failure_exits(self):
        with tempfile.TemporaryDirectory() as d:
            # warning-only spec: prints warnings, continues (render then runs;
            # use --validate-only to stop before rendering)
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "nodes": [{"id": "a", "label": "A", "accent": "banana"},
                              {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            spec["canvas"] = {"frames": 2}
            code, _out, err = self._run_main(
                ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                 "--formats", "png"])
            self.assertIsNone(code)
            self.assertIn("warning:", err)

            # error spec: prints warnings + JSON and raises
            bad = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"}}
            bad_path = self._write_spec(d, bad)
            code, _out, err = self._run_main(
                ["rad", "--spec", str(bad_path), "--outdir", d])
            self.assertIsNotNone(code)
            self.assertIn("spec validation failed", str(code))

    def test_unknown_animation_exits(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "animation": "wormhole",
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            # validate_spec already rejects unknown animations; main's check is
            # the second line of defense, exercised by bypassing validation.
            with mock.patch.object(rad, "validate_spec",
                                   return_value={"ok": True, "errors": [], "warnings": []}):
                code, _out, _err = self._run_main(
                    ["rad", "--spec", str(spec_path), "--outdir", d])
            self.assertIn("unknown animation", str(code))

    def test_pillow_renderer_warnings_and_strict_formats(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "canvas": {"frames": 2},
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            # pillow + non-flow animation + browser-only format -> two warnings
            code, out, err = self._run_main(
                ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                 "--animation", "chapter", "--formats", "png,mp4"])
            self.assertIn("requires the browser renderer", err)
            self.assertIn('"renderer": "pillow"', out)

            # strict formats with a browser-only format on pillow -> exit
            code, _out, _err = self._run_main(
                ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                 "--formats", "png,svg", "--strict-formats"])
            self.assertIn("require the browser renderer", str(code))

            # strict formats satisfied -> success
            code, _out, _err = self._run_main(
                ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                 "--formats", "png", "--strict-formats"])
            self.assertIsNone(code)

    def test_check_failure_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "canvas": {"frames": 2},
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            with mock.patch.object(rad, "check_outputs", return_value={"ok": False, "checks": []}):
                code, _out, _err = self._run_main(
                    ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                     "--formats", "png", "--check"])
            self.assertEqual(code, 1)

    def test_browser_renderer_unavailable_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "canvas": {"frames": 2},
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            with mock.patch.object(rad, "svg_renderer", None):
                code, out, err = self._run_main(
                    ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "browser",
                     "--formats", "png"])
            self.assertIn("browser renderer unavailable", err)
            self.assertIn('"renderer": "pillow"', out)

    def test_strict_formats_missing_after_render_exits(self):
        with tempfile.TemporaryDirectory() as d:
            spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                    "canvas": {"frames": 2},
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}]}
            spec_path = self._write_spec(d, spec)
            # produce png only while requesting gif too -> strict detects the gap
            with mock.patch.object(rad, "write_outputs",
                                   return_value={"png": str(Path(d) / "x.png")}):
                code, _out, err = self._run_main(
                    ["rad", "--spec", str(spec_path), "--outdir", d, "--renderer", "pillow",
                     "--formats", "png,gif", "--strict-formats"])
            self.assertEqual(code, 1)
            self.assertIn("missing requested format", err)


if __name__ == "__main__":
    unittest.main()
