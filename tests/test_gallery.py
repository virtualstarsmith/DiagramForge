"""Gallery builder tests — a one-example miniature build, plus the freshness
gate's drift detection. Gated on Chromium."""
import importlib.util
import json
import unittest
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GalleryBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; needs Chromium")
        cls.build_gallery = load_module("build_gallery")

    def test_mini_build_then_verify_and_drift(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as tmp:
            tmp = Path(tmp)
            manifest = self.build_gallery.render_all(tmp, only=["fishbone-spec"])

            self.assertEqual(["fishbone-spec"], sorted(manifest))
            entry = manifest["fishbone-spec"]
            self.assertEqual("fishbone", entry["layout"])
            for style in self.build_gallery.STYLES:
                self.assertRegex(entry["styles"][style], r"^[0-9a-f]{64}$")
                self.assertTrue((tmp / f"fishbone-spec.{style}.png").is_file())

            # index references both style variants
            index = self.build_gallery.build_index(manifest)
            self.assertIn("fishbone-spec.report.png", index)
            self.assertIn("fishbone-spec.slate.png", index)

            # verify passes on a fresh manifest, fails on a corrupted one
            (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            rc = self.build_gallery.main(["--verify", "--outdir", str(tmp), "--only", "fishbone-spec"])
            self.assertEqual(0, rc)

            bad = json.loads(json.dumps(manifest))
            bad["fishbone-spec"]["styles"]["slate"] = "0" * 64
            (tmp / "manifest.json").write_text(json.dumps(bad), encoding="utf-8")
            rc = self.build_gallery.main(["--verify", "--outdir", str(tmp), "--only", "fishbone-spec"])
            self.assertEqual(1, rc)

    def test_verify_without_manifest_fails_named(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as tmp:
            rc = self.build_gallery.main(["--verify", "--outdir", tmp, "--only", "fishbone-spec"])
        self.assertEqual(2, rc)


if __name__ == "__main__":
    unittest.main()
