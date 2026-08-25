"""In-process coverage for doctor.py (module-level script).

doctor.py runs its logic at import time (no main() function). Importing it
under coverage tracing executes every line, which is how it gets counted.
The subprocess tests in test_tool_subprocess_coverage.py verify the CLI
contract; this module covers the importable logic.
"""
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DoctorInProcessTest(unittest.TestCase):
    def test_import_runs_and_reports(self):
        """Importing doctor.py executes its module-level logic and prints JSON."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except SystemExit:
                pass  # doctor raises SystemExit(0/1) after printing
        output = buf.getvalue()
        self.assertTrue(output.strip().startswith("{"))
        report = json.loads(output)
        self.assertIn("ok", report)
        self.assertIn("capabilities", report)
        self.assertIn("packages", report)
        self.assertIn("assets", report)

    def test_report_contains_required_assets(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except SystemExit:
                pass
        report = json.loads(buf.getvalue())
        self.assertTrue(report["assets"])  # rough.js + fonts present

    def test_version_returns_none_on_command_failure(self):
        """version() must swallow missing/binary-error failures into None."""
        from unittest import mock
        buf = io.StringIO()
        with redirect_stdout(buf):
            spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except SystemExit:
                pass
        with mock.patch("subprocess.run", side_effect=OSError("not found")):
            self.assertIsNone(module.version(["definitely-not-a-binary", "-version"]))


if __name__ == "__main__":
    unittest.main()
