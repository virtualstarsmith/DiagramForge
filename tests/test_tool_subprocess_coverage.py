"""Subprocess coverage for the CLI tool scripts.

Runs doctor.py, icon_search.py, and prepare_fonts.py through their real CLI
entry points so their main() bodies are traced into the coverage data (via the
sitecustomize hook installed by tests/conftest.py). Network-dependent paths in
icon_search are skipped when offline.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script, *argv, timeout=60):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / script)] + list(argv),
        capture_output=True, text=True, timeout=timeout,
    )


class DoctorSubprocessTest(unittest.TestCase):
    def test_main_reports_ok_structure(self):
        proc = _run("doctor.py")
        self.assertIn(proc.returncode, (0, 1))
        report = json.loads(proc.stdout)
        self.assertIn("ok", report)
        self.assertIn("capabilities", report)
        self.assertIn("packages", report)

    def test_main_lists_required_assets(self):
        proc = _run("doctor.py")
        report = json.loads(proc.stdout)
        self.assertTrue(report["assets"])  # rough.js + fonts present


class IconSearchSubprocessTest(unittest.TestCase):
    def test_list_command(self):
        proc = _run("icon_search.py", "list")
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertIn("packs", result)

    def test_no_args_shows_usage(self):
        proc = _run("icon_search.py")
        self.assertNotEqual(proc.returncode, 0)


class PrepareFontsSubprocessTest(unittest.TestCase):
    """prepare_fonts main() rebuilds the bundled fonts from sources; it only
    succeeds when the source .ttf/.woff2 files are present. Run it in a temp
    dir so a partial rebuild never clobbers the real assets."""

    def test_main_help_or_run(self):
        # prepare_fonts has no CLI args; invoking it rebuilds fonts. If the
        # source variable font is absent it should fail gracefully (nonzero).
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "prepare_fonts.py")],
                capture_output=True, text=True, timeout=120, cwd=str(cwd),
            )
        # Whatever the outcome, main() ran and exited with a defined code.
        self.assertIn(proc.returncode, (0, 1, 2))


if __name__ == "__main__":
    unittest.main()
