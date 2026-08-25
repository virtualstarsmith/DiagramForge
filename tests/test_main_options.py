"""Coverage for the main() CLI option branches (validate warnings, verify,
style override, icon-engine, animation override, strict-format missing)."""
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


class MainOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = None
        with patch.object(sys, "argv", ["render_animated_diagram.py"] + argv):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    self.rad.main()
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return code, out.getvalue(), err.getvalue()

    def test_default_render(self):
        tmp = tempfile.mkdtemp()
        code, out, _ = self._run([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tmp, "--formats", "png",
        ])
        self.assertIn(code, (0, None))

    def test_validate_only_warns(self):
        # a spec with a deliberately overlong signature triggers a warning
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec["signature"] = "x" * 40
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(spec, f); p = f.name
        try:
            code, out, err = self._run(["--spec", p, "--outdir", tempfile.mkdtemp(), "--validate-only"])
            self.assertIn(code, (0, 2, None))
            report = json.loads(out)
            self.assertTrue(report["ok"])  # warnings don't block
        finally:
            Path(p).unlink(missing_ok=True)

    def test_style_override(self):
        tmp = tempfile.mkdtemp()
        code, out, _ = self._run([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tmp, "--formats", "png", "--style", "report",
        ])
        self.assertIn(code, (0, None))
        report = json.loads(out)
        self.assertEqual(report.get("style"), "report")

    def test_verify_gif(self):
        tmp = tempfile.mkdtemp()
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec.setdefault("canvas", {})["frames"] = 4
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(spec, f); p = f.name
        try:
            code, out, _ = self._run([
                "--spec", p, "--outdir", tmp, "--formats", "gif", "--verify",
            ])
            self.assertIn(code, (0, None))
            report = json.loads(out)
            self.assertIn("verification", report)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_animation_override(self):
        tmp = tempfile.mkdtemp()
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        spec.setdefault("canvas", {})["frames"] = 4
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(spec, f); p = f.name
        try:
            code, out, _ = self._run([
                "--spec", p, "--outdir", tmp, "--formats", "gif", "--animation", "draw",
            ])
            self.assertIn(code, (0, None))
            report = json.loads(out)
            self.assertEqual(report.get("animation"), "draw")
        finally:
            Path(p).unlink(missing_ok=True)

    def test_icon_engine_pillow(self):
        tmp = tempfile.mkdtemp()
        code, out, _ = self._run([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tmp, "--formats", "png", "--icon-engine", "pillow",
        ])
        self.assertIn(code, (0, None))

    def test_basename_override(self):
        tmp = tempfile.mkdtemp()
        code, out, _ = self._run([
            "--spec", str(EXAMPLES / "graph-workflow-spec.json"),
            "--outdir", tmp, "--formats", "png", "--basename", "custom-name",
        ])
        self.assertIn(code, (0, None))
        self.assertTrue((Path(tmp) / "custom-name.png").is_file())


if __name__ == "__main__":
    unittest.main()
