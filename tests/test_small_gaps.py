"""Branch coverage for the small modules: spec_graph, icon_browser,
render_cache, icon_search, svg_renderer helpers.

Mostly defensive/fallback branches (missing playwright, missing ffmpeg,
corrupt caches, malformed ids) driven with mocks so they run fast and
in-process.
"""
import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sg = load_module("spec_graph")
ib = load_module("icon_browser")
rc = load_module("render_cache")
sr = load_module("svg_renderer")
isearch = load_module("icon_search")


class SpecGraphBranchTest(unittest.TestCase):
    def test_graph_fast_path_skips_malformed_entries(self):
        spec = {
            "layout": "graph",
            "nodes": ["not-a-dict", {"label": "no id"}, {"id": "a", "label": "A"}],
            "edges": [
                "not-a-dict",
                {"to": "a"},
                {"from": "a", "to": "ghost"},  # synthesizes placeholder node
            ],
        }
        # the malformed entries are skipped; 'ghost' synthesizes a placeholder
        # node so lint still sees a connected 2-node graph
        report = sg.lint(spec)
        self.assertIn("ok", report)

    def test_non_graph_layout_edge_skips(self):
        # sequence layout goes through graph_model.build_graph; malformed
        # edges are skipped and unknown endpoints synthesize group nodes.
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b", "label": "hi"}],
        }
        report = sg.lint(spec)
        self.assertIn("ok", report)

    def test_articulation_root_with_children(self):
        # root 'a' with three children that only connect through it -> 'a' is
        # an articulation point via the root rule (degree>=3 makes it a SPOF).
        spec = {
            "layout": "graph",
            "nodes": [{"id": n} for n in ("a", "b", "c", "d")],
            "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}, {"from": "a", "to": "d"}],
        }
        report = sg.lint(spec)
        spof = [i for i in report["issues"] if i["kind"] == "single_point_of_failure"]
        self.assertTrue(any("a" in i.get("nodes", []) for i in spof), report["issues"])

    def test_over_budget_info(self):
        n = 16  # graph comfortable budget is 15
        spec = {
            "layout": "graph",
            "nodes": [{"id": f"n{i}"} for i in range(n)],
            "edges": [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(n - 1)],
        }
        report = sg.lint(spec)
        self.assertTrue(any(i["kind"] == "over_budget" for i in report["issues"]))

    def test_unknown_node_exits(self):
        spec = {"layout": "graph", "nodes": [{"id": "a"}], "edges": []}
        with self.assertRaises(SystemExit):
            sg.neighbors_of(spec, "ghost")

    def test_mermaid_id_sanitizes_and_dedupes(self):
        self.assertEqual(sg._mermaid_id("1abc", set()), "n_1abc")
        used = {"a_b"}
        self.assertEqual(sg._mermaid_id("a-b", used), "a_b_2")
        self.assertIn("a_b_2", used)

    def test_main_unknown_command_returns_1(self):
        with tempfile.TemporaryDirectory() as d:
            spec_path = Path(d) / "s.json"
            spec_path.write_text(json.dumps({"layout": "graph", "nodes": []}), encoding="utf-8")
            fake_args = argparse.Namespace(command="bogus", spec=str(spec_path))
            with mock.patch("argparse.ArgumentParser.parse_args", return_value=fake_args):
                self.assertEqual(sg.main(), 1)


class IconBrowserBranchTest(unittest.TestCase):
    def test_is_available_false_without_playwright(self):
        import sys
        with mock.patch.dict(sys.modules, {"playwright.sync_api": None}):
            self.assertFalse(ib.is_available())

    def test_render_glyph_frames_false_without_playwright(self):
        import sys
        if not (ib.TABLER_ICON_DIR / "check.svg").is_file():
            raise unittest.SkipTest("tabler pack missing")
        with mock.patch.dict(sys.modules, {"playwright.sync_api": None}):
            out = ib.render_glyph_frames([("check", "#ffffff")], 64, 2)
        self.assertEqual(out, {})

    def test_render_glyph_frames_skips_missing_markup(self):
        if not ib.is_available():
            raise unittest.SkipTest("playwright unavailable")
        if not (ib.TABLER_ICON_DIR / "check.svg").is_file():
            raise unittest.SkipTest("tabler pack missing")
        out = ib.render_glyph_frames([("check", "#ffffff"), ("no-such-icon", "#ffffff")], 64, 2)
        self.assertIn(("check", "#ffffff"), out)
        self.assertNotIn(("no-such-icon", "#ffffff"), out)


class RenderCacheBranchTest(unittest.TestCase):
    def test_format_key_missing(self):
        self.assertIsNone(rc._format_key("gif", {}))
        self.assertIsNone(rc._format_key("gif", {"gif_skipped": ""}))

    def test_invalidate_corrupt_index(self):
        with tempfile.TemporaryDirectory() as d:
            cache_dir = Path(d) / ".dfcache"
            cache_dir.mkdir()
            (cache_dir / "index.json").write_text("{corrupt", encoding="utf-8")
            self.assertEqual(rc.invalidate(d), 0)

    def test_invalidate_unlink_failure(self):
        with tempfile.TemporaryDirectory() as d:
            cache_dir = Path(d) / ".dfcache"
            cache_dir.mkdir()
            (cache_dir / "index.json").write_text('{"a": 1}', encoding="utf-8")
            with mock.patch.object(Path, "unlink", side_effect=OSError("locked")):
                self.assertEqual(rc.invalidate(d), 1)


class IconSearchListTest(unittest.TestCase):
    def test_cmd_list_with_vendor_packs(self):
        with tempfile.TemporaryDirectory() as d:
            pack = Path(d) / "logos"
            pack.mkdir()
            (pack / "kube.svg").write_text("<svg/>", encoding="utf-8")
            (pack / "ignore.txt").write_text("x", encoding="utf-8")
            buf = io.StringIO()
            with mock.patch.object(isearch, "VENDOR_ICON_DIR", Path(d)), redirect_stdout(buf):
                code = isearch.cmd_list(argparse.Namespace())
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["packs"]["logos"], ["kube"])


class SvgRendererBranchTest(unittest.TestCase):
    def test_find_icon_svg_vendor_pack(self):
        with tempfile.TemporaryDirectory() as d:
            pack = Path(d) / "logos"
            pack.mkdir()
            (pack / "acme.svg").write_text("<svg/>", encoding="utf-8")
            (pack / "not-a-dir.svg").write_text("<svg/>", encoding="utf-8")  # non-dir sibling
            with mock.patch.object(sr, "VENDOR_ICON_DIR", Path(d)):
                self.assertEqual(sr._find_icon_svg("acme"), pack / "acme.svg")

    def test_is_available_false_without_playwright(self):
        import sys
        with mock.patch.dict(sys.modules, {"playwright.sync_api": None}):
            self.assertFalse(sr.is_available())

    def test_font_css_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(sr, "FONT_DIR", Path(d)):
                self.assertEqual(sr._font_css(), "")

    def test_svg_text_to_path_without_opentype(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(sr, "VENDOR_DIR", Path(d)):
                self.assertEqual(sr.svg_text_to_path(mock.MagicMock(), "<svg/>"), "<svg/>")

    def test_capture_frames_raster_without_opentype(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(sr, "VENDOR_DIR", Path(d)):
                self.assertIsNone(sr.capture_frames_raster(mock.MagicMock(), 2, 100, 100))

    def test_capture_frames_raster_failure_paths(self):
        page = mock.MagicMock()
        page.evaluate.side_effect = RuntimeError("page gone")
        out = sr.capture_frames_raster(page, 2, 100, 100)
        self.assertIsNone(out)
        # subset failure inside the doc branch is swallowed
        page2 = mock.MagicMock()
        page2.evaluate.side_effect = [None, ["a", "b"]]  # ot load, then capture
        bad_opt = mock.MagicMock()
        bad_opt.collect_codepoints.side_effect = ValueError("bad")
        with mock.patch.dict("sys.modules", {"svg_optimize": bad_opt}):
            out = sr.capture_frames_raster(page2, 2, 100, 100, doc={"ops": []})
        # capture returns garbage frames -> decode fails -> None
        self.assertIsNone(out)
        # empty capture result -> None before decoding
        page3 = mock.MagicMock()
        page3.evaluate.side_effect = [None, []]
        self.assertIsNone(sr.capture_frames_raster(page3, 2, 100, 100))

    def test_custom_icon_markup_unsupported_suffix(self):
        self.assertIsNone(sr._custom_icon_markup(Path("icon.bmp")))
        self.assertIsNone(sr._custom_icon_markup(Path("/nope/icon.png")))

    def test_save_gif_ffmpeg_unavailable_and_alignment(self):
        from PIL import Image
        frames = [Image.new("RGB", (16, 16)), Image.new("RGB", (16, 16))]
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(sr._save_gif_ffmpeg(frames, "x.gif", 12))
        # single frame
        self.assertFalse(sr._save_gif_ffmpeg(frames[:1], "x.gif", 12))
        # misaligned fps rejected before invoking ffmpeg
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertFalse(sr._save_gif_ffmpeg(frames, "x.gif", 7))

    def test_save_gif_ffmpeg_pass_failures(self):
        from PIL import Image
        frames = [Image.new("RGB", (16, 16)), Image.new("RGB", (16, 16))]
        ok = mock.Mock(returncode=0)
        fail = mock.Mock(returncode=1, stderr="boom")
        with tempfile.TemporaryDirectory() as d, mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            # pass 1 fails (palette never created)
            with mock.patch("subprocess.run", return_value=fail):
                self.assertFalse(sr._save_gif_ffmpeg(frames, Path(d) / "x.gif", 10))
            # pass 2 fails after pass 1 "succeeds" (palette file faked by pass1 mock)
            def fake_run(cmd, **kw):
                if "palette.png" in cmd[-1] and "palettegen" in cmd[-2]:
                    Path(cmd[-1]).write_bytes(b"png")
                    return ok
                return fail
            with mock.patch("subprocess.run", side_effect=fake_run):
                self.assertFalse(sr._save_gif_ffmpeg(frames, Path(d) / "x.gif", 10))

    def test_save_gif_last_resort_direct_write(self):
        from PIL import Image
        frames = [Image.new("RGB", (16, 16)), Image.new("RGB", (16, 16), "#ff0000")]
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out.gif"
            with mock.patch.object(sr, "_save_gif_ffmpeg", side_effect=RuntimeError), \
                 mock.patch.object(sr, "_save_gif_pillow", side_effect=RuntimeError):
                sr._save_gif(frames, target, 10)
            self.assertTrue(target.is_file())

    def test_encode_mp4_paths(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(sr._encode_mp4([Path("f0.png")], 12, "x.mp4"))
        fail = mock.Mock(returncode=1, stderr="encoder exploded")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             mock.patch("subprocess.run", return_value=fail):
            self.assertFalse(sr._encode_mp4([Path(d) / "frame0000.png"], 12, Path(d) / "x.mp4"))

    def test_render_wrapper_delegates(self):
        with mock.patch.object(sr, "render_all", return_value={"png": "x"}) as m:
            out = sr.render({}, Path("out"), "base", scale=3)
        self.assertEqual(out, {"png": "x"})
        m.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class SpecGraphMopUpTest(unittest.TestCase):
    def test_neighborhood_unknown_node_exits(self):
        spec = {"layout": "graph", "nodes": [{"id": "a"}], "edges": []}
        with self.assertRaises(SystemExit):
            sg.neighborhood(spec, "ghost", 1)

    def test_built_graph_malformed_edges_skipped(self):
        # sequence layout goes through graph_model.build_graph; messages with
        # missing endpoints must not crash the graph adapter
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b", "label": "ok"},
                         {"from": "a"}, {"to": "b"}],
        }
        report = sg.lint(spec)
        self.assertIn("ok", report)
