"""Tests for scripts/lint_output.py — the output security contract linter.

Unit cases run on string fixtures (no browser). The e2e case lints a real
browser-rendered SVG + interactive HTML and is skipped without Chromium.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_output = load_module("lint_output")

CLEAN_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<title>Diagram</title><desc>demo</desc>
<defs><style>@font-face{font-family:'X';src:url(data:font/woff2;base64,AAAA)}</style>
<linearGradient id="g"><stop offset="0"/></linearGradient></defs>
<rect fill="url(#g)" width="10" height="10"/>
<image xlink:href="data:image/png;base64,AAAA" href="data:image/png;base64,AAAA"/>
</svg>"""

CLEAN_HTML = """<!doctype html><html><head><style>.a{background:url(#paper)}</style></head>
<body><svg role="img" aria-labelledby="d-title d-desc"><title id="d-title">t</title><desc id="d-desc">d</desc></svg>
<script>(() => { document.addEventListener("click", () => {}); })();</script>
</body></html>"""


def categories(result):
    return {v["category"] for v in result["violations"]}


class LintTextTest(unittest.TestCase):
    def lint(self, text):
        violations = lint_output.lint_text(text)
        return {"ok": not violations, "violations": violations}

    def test_clean_svg_passes(self):
        self.assertEqual([], lint_output.lint_text(CLEAN_SVG))

    def test_clean_html_passes(self):
        # Inline <script> is allowed by design (interactive HTML ships one IIFE).
        self.assertEqual([], lint_output.lint_text(CLEAN_HTML))

    def test_remote_src_rejected(self):
        result = self.lint('<img src="https://evil.example/x.png">')
        self.assertFalse(result["ok"])
        self.assertIn("remote-asset", categories(result))

    def test_protocol_relative_rejected(self):
        result = self.lint('<script src="//cdn.example/lib.js"></script>')
        self.assertIn("remote-asset", categories(result))

    def test_relative_reference_rejected(self):
        # Artifacts must be self-contained; even local file refs break that.
        result = self.lint('<img src="logo.png">')
        self.assertIn("remote-asset", categories(result))

    def test_javascript_url_rejected(self):
        result = self.lint('<a href="javascript:alert(1)">x</a>')
        self.assertIn("js-url", categories(result))

    def test_css_import_rejected(self):
        result = self.lint("<style>@import url('https://fonts.example/x.css');</style>")
        cats = categories(result)
        self.assertIn("css-import", cats)
        self.assertIn("css-url", cats)

    def test_external_css_url_rejected(self):
        result = self.lint("<style>.a{background:url( https://x.example/bg.png )}</style>")
        self.assertIn("css-url", categories(result))

    def test_fragment_and_data_urls_allowed(self):
        result = self.lint("<style>.a{fill:url(#g)} .b{src:url(data:image/png;base64,AA)}</style>")
        self.assertEqual([], result["violations"])

    def test_executable_attributes_rejected(self):
        for snippet in (
            '<div onclick="f()">',
            '<iframe srcdoc="<p>x</p>"></iframe>',
            '<button formaction="https://x.example">',
            '<svg onload="f()"></svg>',
        ):
            result = self.lint(snippet)
            self.assertIn("executable-attr", categories(result), snippet)

    def test_active_elements_rejected(self):
        for tag in ("iframe", "object", "embed", "form", "base"):
            result = self.lint(f"<{tag}></{tag}>")
            self.assertIn("active-element", categories(result), tag)

    def test_violations_carry_positions(self):
        result = self.lint('line1\nline2\n<img src="https://evil.example/x.png">')
        violation = result["violations"][0]
        self.assertEqual(3, violation["line"])
        self.assertTrue(violation["snippet"])


class LintFileTest(unittest.TestCase):
    def test_lint_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.svg"
            path.write_text(CLEAN_SVG, encoding="utf-8")
            self.assertEqual([], lint_output.lint_file(path))

    def test_unsupported_extension_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            path.write_bytes(b"PNG")
            with self.assertRaises(ValueError):
                lint_output.lint_file(path)


class LintCliTest(unittest.TestCase):
    def run_cli(self, *paths):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "lint_output.py"), *map(str, paths)],
            capture_output=True,
            text=True,
        )

    def test_cli_clean_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.svg"
            path.write_text(CLEAN_SVG, encoding="utf-8")
            proc = self.run_cli(path)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_cli_violation_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.html"
            path.write_text('<img src="https://evil.example/x.png">', encoding="utf-8")
            proc = self.run_cli(path)
        self.assertEqual(1, proc.returncode, proc.stdout)
        self.assertFalse(json.loads(proc.stdout)["ok"])

    def test_cli_missing_file_exit_two(self):
        proc = self.run_cli("does-not-exist.svg")
        self.assertEqual(2, proc.returncode)


class LintRenderedArtifactsTest(unittest.TestCase):
    """The real artifacts the renderer ships must satisfy the contract."""

    @classmethod
    def setUpClass(cls):
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; needs Chromium")
        cls.renderer = load_module("render_animated_diagram")
        cls.spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))

    def test_rendered_svg_and_html_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.renderer.write_outputs_browser(
                self.spec, Path(tmp), "linted", formats=("svg", "html")
            )
            report = lint_output.lint_files([result["svg"], result["html"]])
        self.assertTrue(report["ok"], json.dumps(report["violations"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    unittest.main()
