"""Unit tests for the render cache (scripts/render_cache.py).

Exercises hash stability, salt discrimination, hit/miss semantics, file
deletion invalidation, and index persistence — without launching a browser.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(canvas=None, ops=None, theme=None, animation=None):
    return {
        "canvas": canvas or {"width": 100, "height": 80, "fps": 20, "frames": 4},
        "ops": ops or [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "stroke": "#fff"}],
        "bg": "#000",
        "theme": theme or {"core_stroke": "#3b82f6"},
        "animation": animation or {"flow_paths": [], "pulse_targets": []},
        "finish": {"mode": "dark"},
    }


class RenderCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rc = load_module("render_cache")

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="dfcache_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_doc_hash_stable(self):
        d = _doc()
        self.assertEqual(self.rc.doc_hash(d), self.rc.doc_hash(d))

    def test_doc_hash_changes_with_ops(self):
        self.assertNotEqual(
            self.rc.doc_hash(_doc(ops=[{"op": "rect", "x": 1}])),
            self.rc.doc_hash(_doc(ops=[{"op": "rect", "x": 2}])),
        )

    def test_doc_hash_changes_with_canvas(self):
        a = _doc(canvas={"width": 100, "height": 80, "fps": 20, "frames": 4})
        b = _doc(canvas={"width": 200, "height": 80, "fps": 20, "frames": 4})
        self.assertNotEqual(self.rc.doc_hash(a), self.rc.doc_hash(b))

    def test_salt_distinguishes_options(self):
        """text_outlines / fast_capture / animation must change the cache key."""
        d = _doc()
        self.assertNotEqual(self.rc.doc_hash(d, "flow"), self.rc.doc_hash(d, "draw"))
        self.assertNotEqual(self.rc.doc_hash(d, "flow|to=0"), self.rc.doc_hash(d, "flow|to=1"))

    def test_lookup_miss_on_empty_dir(self):
        self.assertIsNone(self.rc.lookup(_doc(), self.tmp, "base", ("png", "svg")))

    def test_store_then_lookup_hits(self):
        d = _doc()
        png = self.tmp / "base.png"; png.write_bytes(b"x")
        svg = self.tmp / "base.svg"; svg.write_bytes(b"x")
        result = {"png": str(png), "svg": str(svg), "canvas": d["canvas"], "elements": 1}
        self.rc.store(d, self.tmp, "base", result, ("png", "svg"), salt="flow")
        hit = self.rc.lookup(d, self.tmp, "base", ("png", "svg"), salt="flow")
        self.assertIsNotNone(hit)
        self.assertTrue(hit.get("cached"))
        self.assertEqual(hit["png"], str(png))

    def test_lookup_miss_when_format_absent(self):
        d = _doc()
        png = self.tmp / "base.png"; png.write_bytes(b"x")
        self.rc.store(d, self.tmp, "base", {"png": str(png)}, ("png",), salt="flow")
        # request svg which was never stored -> miss
        self.assertIsNone(self.rc.lookup(d, self.tmp, "base", ("png", "svg"), salt="flow"))

    def test_lookup_miss_when_file_deleted(self):
        d = _doc()
        png = self.tmp / "base.png"; png.write_bytes(b"x")
        self.rc.store(d, self.tmp, "base", {"png": str(png)}, ("png",), salt="flow")
        png.unlink()
        self.assertIsNone(self.rc.lookup(d, self.tmp, "base", ("png",), salt="flow"))

    def test_lookup_miss_when_salt_changes(self):
        """The core bug: same doc, different option salt must not collide."""
        d = _doc()
        png = self.tmp / "base.png"; png.write_bytes(b"x")
        self.rc.store(d, self.tmp, "base", {"png": str(png)}, ("png",), salt="flow|to=0")
        # Asking with a different salt (text_outlines on) must miss.
        self.assertIsNone(self.rc.lookup(d, self.tmp, "base", ("png",), salt="flow|to=1"))

    def test_invalidate_clears_index(self):
        d = _doc()
        self.rc.store(d, self.tmp, "base", {"png": str(self.tmp / "x.png")}, ("png",), salt="flow")
        self.assertEqual(self.rc.invalidate(self.tmp), 1)
        self.assertIsNone(self.rc.lookup(d, self.tmp, "base", ("png",), salt="flow"))

    def test_invalidate_when_absent(self):
        self.assertEqual(self.rc.invalidate(self.tmp), 0)

    def test_index_persists_across_module_reloads(self):
        d = _doc()
        png = self.tmp / "base.png"; png.write_bytes(b"x")
        self.rc.store(d, self.tmp, "base", {"png": str(png)}, ("png",), salt="flow")
        # reload from disk (simulating a new process)
        rc2 = load_module("render_cache")
        hit = rc2.lookup(d, self.tmp, "base", ("png",), salt="flow")
        self.assertIsNotNone(hit)


if __name__ == "__main__":
    unittest.main()
