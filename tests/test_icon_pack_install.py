"""tests for scripts/icon_pack_install.py — offline: a fixture zip via file://."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import icon_pack_install


def _fixture_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("community-master/icons/svg/resources/compute/k8s_Node_Light.svg", "<svg id='light'/>")
        zf.writestr("community-master/icons/svg/resources/compute/k8s_Node_Dark-bg.svg", "<svg id='dark'/>")
        zf.writestr("community-master/icons/svg/resources/storage/k8s_PV_Light.svg", "<svg id='pv'/>")
        zf.writestr("community-master/icons/README.md", "not an icon")
    return buf.getvalue()


class NormalizeTests(unittest.TestCase):
    def test_kebab(self):
        self.assertEqual(icon_pack_install.kebab("Amazon-EC2_light-bg.svg"), "amazon-ec2-light-bg")
        self.assertEqual(icon_pack_install.kebab("GCE  VM Instance.svg"), "gce-vm-instance")
        self.assertEqual(icon_pack_install.kebab("A--B.svg"), "a-b")

    def test_collect_prefers_light_over_dark_and_strips_prefix(self):
        svg_map = icon_pack_install.collect_svgs(_fixture_zip(), strip_prefix="community-master/icons/")
        self.assertEqual(set(svg_map), {"k8s-node", "k8s-pv"})
        self.assertIn(b"id='light'", svg_map["k8s-node"])
        self.assertNotIn(b"id='dark'", b"".join(svg_map.values()))

    def test_collect_without_prefix_still_flattens(self):
        svg_map = icon_pack_install.collect_svgs(_fixture_zip())
        self.assertEqual(set(svg_map), {"k8s-node", "k8s-pv"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(icon_pack_install, "VENDOR_DIR", self.tmpdir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup_tmp)

    def _cleanup_tmp(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_fixture(self):
        zpath = self.tmpdir / "pack.zip"
        zpath.write_bytes(_fixture_zip())
        return zpath

    def test_install_from_local_zip(self):
        rc = icon_pack_install.main(["--url", self._write_fixture().as_uri(), "--pack", "k8s-test"])
        self.assertEqual(rc, 0)
        pack_dir = icon_pack_install.VENDOR_DIR / "k8s-test"
        svgs = sorted(p.name for p in pack_dir.glob("*.svg"))
        self.assertEqual(svgs, ["k8s-node.svg", "k8s-pv.svg"])
        license_text = (pack_dir / "LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("not redistributed", license_text)

    def test_dry_run_writes_nothing(self):
        rc = icon_pack_install.main(["--url", self._write_fixture().as_uri(), "--pack", "k8s-test", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse((icon_pack_install.VENDOR_DIR / "k8s-test").exists())

    def test_list_reports_installed_counts(self):
        icon_pack_install.install_pack("demo", {"a": b"<svg/>"}, "MIT", "test")
        rc = icon_pack_install.main(["--list"])
        self.assertEqual(rc, 0)
        self.assertTrue((icon_pack_install.VENDOR_DIR / "demo" / "a.svg").is_file())

    def test_missing_pack_arg_fails(self):
        with self.assertRaises(SystemExit):
            icon_pack_install.main(["--url", "file:///nonexistent.zip"])

    def test_missing_file_is_named_network_error(self):
        # A file:// URL that does not exist exercises the URLError path offline.
        rc = icon_pack_install.main(["--url", "file:///nonexistent/pack.zip", "--pack", "x"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
