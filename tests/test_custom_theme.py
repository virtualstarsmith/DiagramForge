"""Custom theme channel tests: theme_loader validation, marker resolution,
contrast enforcement, and renderer integration for style="custom"."""
import contextlib
import importlib.util
import io
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


theme_loader = load_module("theme_loader")
renderer = load_module("render_animated_diagram")
REQUIRED = renderer._THEME_KEYS


def valid_theme():
    return dict(renderer.STYLE_THEMES["report"])


def expect_theme_error(test_case, fn, marker):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        with test_case.assertRaises(SystemExit) as ctx:
            fn()
    test_case.assertEqual(2, ctx.exception.code)
    test_case.assertIn(marker, stderr.getvalue())


class ContrastMathTest(unittest.TestCase):
    def test_black_on_white_is_21(self):
        ratio = theme_loader.contrast_ratio((0, 0, 0), (255, 255, 255))
        self.assertAlmostEqual(21.0, ratio, places=1)

    def test_same_color_is_1(self):
        self.assertAlmostEqual(1.0, theme_loader.contrast_ratio((10, 20, 30), (10, 20, 30)))

    def test_hex_shorthand_expands(self):
        self.assertEqual((255, 255, 255), theme_loader.hex_to_rgb("#fff"))

    def test_suggest_fix_moves_toward_passing(self):
        # Gray ink on near-white bg fails; nudging toward black must fix it.
        fg, bg = (150, 150, 150), (245, 245, 245)
        self.assertLess(theme_loader.contrast_ratio(fg, bg), 4.5)
        fix = theme_loader.suggest_contrast_fix(fg, bg, 4.5)
        self.assertIsNotNone(fix)
        self.assertGreaterEqual(
            theme_loader.contrast_ratio(theme_loader.hex_to_rgb(fix), bg), 4.5
        )

    def test_suggest_fix_returns_none_when_impossible(self):
        # Even pure white on mid-gray tops out below 4.5 — honest None.
        self.assertIsNone(theme_loader.suggest_contrast_fix((120, 120, 120), (130, 130, 130), 21.0))


class ValidateThemeTest(unittest.TestCase):
    def test_valid_theme_passes(self):
        self.assertEqual([], theme_loader.validate_theme(valid_theme(), REQUIRED))

    def test_missing_and_extra_keys_rejected(self):
        theme = valid_theme()
        del theme["bg"]
        theme["surprise"] = "#123456"
        problems = theme_loader.validate_theme(theme, REQUIRED)
        self.assertTrue(any("missing_keys" in p for p in problems))
        self.assertTrue(any("unknown_keys" in p for p in problems))

    def test_bad_hex_rejected(self):
        theme = valid_theme()
        theme["bg"] = "purple-ish"
        problems = theme_loader.validate_theme(theme, REQUIRED)
        self.assertTrue(any("bad_hex" in p for p in problems))

    def test_contrast_floor_enforced_with_suggestion(self):
        theme = valid_theme()
        theme["white"] = "#bbbbbb"  # too light on the white-ish report bg
        problems = theme_loader.validate_theme(theme, REQUIRED)
        contrast = [p for p in problems if "contrast" in p]
        self.assertTrue(contrast, problems)
        self.assertIn("suggested white=", contrast[0])

    def test_not_a_mapping_rejected(self):
        problems = theme_loader.validate_theme(["#fff"], REQUIRED)
        self.assertTrue(any("not_a_mapping" in p for p in problems))


class MarkerResolutionTest(unittest.TestCase):
    def test_theme_file_wins_over_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            theme_path = tmp / "direct.json"
            theme = valid_theme()
            theme["core_stroke"] = "#123abc"
            theme_path.write_text(json.dumps(theme), encoding="utf-8")
            (tmp / ".diagramforge").write_text("theme: ignored-slug", encoding="utf-8")
            resolved = theme_loader.resolve_theme(
                {"theme_file": "direct.json"}, tmp, REQUIRED
            )
        self.assertEqual("#123abc", resolved["core_stroke"])

    def test_marker_resolves_named_profile(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            tmp, home = Path(tmp), Path(home)
            nested = tmp / "deep" / "deeper"
            nested.mkdir(parents=True)
            (tmp / ".diagramforge").write_text("theme: acme\n", encoding="utf-8")
            theme_dir = home / ".diagramforge" / "themes"
            theme_dir.mkdir(parents=True)
            theme = valid_theme()
            theme["core_stroke"] = "#a1b2c3"
            (theme_dir / "acme.json").write_text(json.dumps(theme), encoding="utf-8")

            original = theme_loader.themes_dir
            theme_loader.themes_dir = lambda: theme_dir
            try:
                resolved = theme_loader.resolve_theme({}, nested, REQUIRED)
            finally:
                theme_loader.themes_dir = original
        self.assertEqual("#a1b2c3", resolved["core_stroke"])

    def test_malformed_marker_fails_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".diagramforge").write_text("hello world", encoding="utf-8")
            expect_theme_error(
                self,
                lambda: theme_loader.resolve_theme({}, tmp, REQUIRED),
                "theme_error:marker_malformed",
            )

    def test_missing_theme_file_fails_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            expect_theme_error(
                self,
                lambda: theme_loader.resolve_theme({"theme_file": "nope.json"}, tmp, REQUIRED),
                "theme_error:not_found",
            )

    def test_no_source_fails_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            expect_theme_error(
                self,
                lambda: theme_loader.resolve_theme({}, tmp, REQUIRED),
                "theme_error:no_source",
            )

    def test_finish_mode_derives_from_bg(self):
        dark = valid_theme()
        dark["bg"] = "#0f172a"
        dark["white"] = "#e2e8f0"
        self.assertEqual("dark", theme_loader.finish_mode(dark))
        self.assertEqual("light", theme_loader.finish_mode(valid_theme()))


class RendererIntegrationTest(unittest.TestCase):
    def test_validate_spec_accepts_custom_with_theme_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "theme.json").write_text(json.dumps(valid_theme()), encoding="utf-8")
            spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))
            spec["style"] = "custom"
            spec["theme_file"] = "theme.json"
            result = renderer.validate_spec(spec, spec_dir=tmp)
        self.assertTrue(result["ok"], result["errors"])

    def test_validate_spec_rejects_custom_without_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))
            spec["style"] = "custom"
            result = renderer.validate_spec(spec, spec_dir=Path(tmp))
        self.assertFalse(result["ok"])
        self.assertTrue(any("theme source" in e["message"] for e in result["errors"]))

    def test_validate_spec_rejects_missing_theme_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))
            spec["style"] = "custom"
            spec["theme_file"] = "missing.json"
            result = renderer.validate_spec(spec, spec_dir=Path(tmp))
        self.assertFalse(result["ok"])
        self.assertTrue(any("theme_file" in e["path"] for e in result["errors"]))

    def test_apply_custom_theme_switches_palette(self):
        saved = dict(renderer.THEME)
        saved_style, saved_finish = renderer.CURRENT_STYLE, renderer.FINISH_MODE
        try:
            theme = valid_theme()
            theme["core_stroke"] = "#7c3aed"
            renderer.apply_custom_theme(theme)
            self.assertEqual("#7c3aed", renderer.THEME["core_stroke"])
            self.assertEqual("custom", renderer.CURRENT_STYLE)
            self.assertEqual("light", renderer.FINISH_MODE)
        finally:
            renderer.THEME.clear()
            renderer.THEME.update(saved)
            renderer.CURRENT_STYLE = saved_style
            renderer.FINISH_MODE = saved_finish


if __name__ == "__main__":
    unittest.main()
