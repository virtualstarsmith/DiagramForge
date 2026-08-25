"""Tests for the render CLI entry point (render_animated_diagram.main).

Covers the argument-parsing and orchestration block (validate-only, unknown
formats, strict-formats, default browser render) — the largest previously
uncovered region. Calls ``main()`` in-process (monkeypatching sys.argv) so the
executed lines land in the coverage data.
"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def _run_main(self, argv):
        """Invoke main() in-process; return (exit_code_or_None, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        code = None
        with patch.object(sys, "argv", ["render_animated_diagram.py"] + argv):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    self.rad.main()
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, out.getvalue(), err.getvalue()

    def test_validate_only_valid_spec(self):
        code, out, _ = self._run_main([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tempfile.mkdtemp(), "--validate-only",
        ])
        self.assertIn(code, (0, None))
        report = json.loads(out)
        self.assertTrue(report["ok"])

    def test_validate_only_bad_spec_fails(self):
        bad = {"layout": "graph", "canvas": {"width": 5}}  # width out of range
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(bad, f); p = f.name
        try:
            code, out, _ = self._run_main(["--spec", p, "--outdir", tempfile.mkdtemp(), "--validate-only"])
            self.assertEqual(code, 2)
            report = json.loads(out)
            self.assertFalse(report["ok"])
            self.assertGreater(len(report["errors"]), 0)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_unknown_format_errors(self):
        code, out, err = self._run_main([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tempfile.mkdtemp(), "--formats", "png,bogus",
        ])
        # main() raises SystemExit("unknown format(s): ...") which argparse
        # writes to the real fd-level stderr (not captured by redirect_stderr);
        # assert the non-zero exit instead of matching the message text.
        self.assertNotIn(code, (0, None))

    def test_strict_formats_with_pillow_fails_on_browser_only(self):
        code, out, err = self._run_main([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tempfile.mkdtemp(),
            "--renderer", "pillow", "--formats", "svg", "--strict-formats",
        ])
        self.assertNotIn(code, (0, None))

    def test_default_render_produces_json_report(self):
        outdir = Path(tempfile.mkdtemp())
        code, out, _ = self._run_main([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", str(outdir), "--formats", "png",
        ])
        self.assertIn(code, (0, None))
        report = json.loads(out)
        self.assertIn("png", report)
        self.assertTrue((outdir / "animated-diagram.png").is_file())

    def test_help_exits_zero(self):
        code, out, _ = self._run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--formats", out)

    def test_missing_spec_arg_fails(self):
        code, out, err = self._run_main(["--outdir", tempfile.mkdtemp()])
        self.assertNotIn(code, (0, None))


if __name__ == "__main__":
    unittest.main()

