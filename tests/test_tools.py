"""Tests for the standalone tool scripts: doctor.py, prepare_fonts.py, and
icon_search.py. These are not exercised by the render pipeline, so they have
their own module. Network-dependent paths (Iconify search/fetch) are skipped
when offline.
"""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorTest(unittest.TestCase):
    """doctor.py reports the runtime environment as JSON and exits 0/1."""

    def test_doctor_runs_and_reports_structure(self):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "doctor.py")],
            capture_output=True, text=True, timeout=60,
        )
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        report = json.loads(proc.stdout)
        for key in ("ok", "python", "packages", "tools", "assets", "capabilities"):
            self.assertIn(key, report)
        self.assertIn("version", report["python"])
        self.assertIn("PIL", report["packages"])
        # base packages must be present for any rendering
        self.assertTrue(report["packages"]["PIL"]["available"])
        self.assertTrue(report["packages"]["svg.path"]["available"])
        # assets list the bundled files the renderer needs
        asset_names = set(report["assets"].keys())
        self.assertTrue(any("rough.js" in a for a in asset_names))

    def test_doctor_capabilities_field(self):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "doctor.py")],
            capture_output=True, text=True, timeout=60,
        )
        report = json.loads(proc.stdout)
        caps = report["capabilities"]
        for flag in ("base_ok", "browser_ok", "publish_ok", "notes"):
            self.assertIn(flag, caps)


class PrepareFontsTest(unittest.TestCase):
    """prepare_fonts.py is a one-shot build script; test its pure helpers."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.pf = load_module("prepare_fonts")
        except Exception:
            cls.pf = None

    def setUp(self):
        if self.pf is None:
            self.skipTest("prepare_fonts import failed (fonttools missing?)")

    def test_build_charset_contains_ascii_and_cjk(self):
        chars = self.pf.build_charset()
        s = "".join(chr(c) for c in chars) if isinstance(next(iter(chars)), int) else "".join(chars)
        self.assertIn("A", s)
        self.assertIn("0", s)
        # CJK must be represented (GB2312 hanzi)
        self.assertTrue(any(0x4E00 <= (ord(c) if isinstance(c, str) else c) <= 0x9FFF for c in chars))

    def test_coverage_ranges_compresses_to_intervals(self):
        ranges = self.pf.coverage_ranges({32, 33, 34, 65, 66, 200})  # 32-34, 65-66, 200
        # should produce contiguous [start,end] inclusive intervals
        self.assertIn([32, 34], ranges)
        self.assertIn([65, 66], ranges)
        self.assertIn([200, 200], ranges)


class IconSearchTest(unittest.TestCase):
    """icon_search.py — only the offline `list` command is tested here;
    `search`/`fetch` hit the Iconify API and are skipped offline."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ise = load_module("icon_search")
        except Exception:
            cls.ise = None

    def setUp(self):
        if self.ise is None:
            self.skipTest("icon_search import failed")

    def test_list_returns_vendor_structure(self):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "icon_search.py"), "list"],
            capture_output=True, text=True, timeout=30,
        )
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["vendor_dir"], str(ROOT / "assets" / "icons" / "vendor"))
        # packs is a dict (possibly empty if no vendor icons installed)
        self.assertIsInstance(result["packs"], dict)


if __name__ == "__main__":
    unittest.main()
