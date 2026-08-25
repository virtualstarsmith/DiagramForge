"""Targeted coverage for the skip-edge routing branches and _probe_mp4.

The layered layouts route "skip" edges (edges jumping ≥2 layers) through a
dedicated lane. The bundled examples don't produce skips, so this module
constructs specs that do, covering the skip-edge geometry in plan_graph and
plan_dfd. Also covers _probe_mp4's ffprobe parsing.
"""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkipEdgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = load_module("graph_model")

    def test_graph_skip_edge_horizontal(self):
        # a -> b -> c -> d, plus a -> d (jumps two layers) => skip edge
        spec = {
            "layout": "graph", "layout_engine": "legacy", "direction": "right",
            "nodes": [{"id": c, "label": c} for c in "abcd"],
            "edges": [
                {"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "d"},
                {"from": "a", "to": "d"},  # skip edge
            ],
        }
        plan = self.gm.plan_graph(spec)
        self.assertEqual(plan["graph_meta"]["skips"], 1)

    def test_graph_skip_edge_vertical(self):
        spec = {
            "layout": "graph", "layout_engine": "legacy", "direction": "down",
            "nodes": [{"id": c, "label": c} for c in "abcd"],
            "edges": [
                {"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "d"},
                {"from": "a", "to": "d"},
            ],
        }
        plan = self.gm.plan_graph(spec)
        self.assertEqual(plan["graph_meta"]["skips"], 1)

    def test_dfd_skip_flow(self):
        # producer -> process -> store plus producer -> store (skip)
        spec = {
            "layout": "dfd",
            "nodes": [
                {"id": "ext", "label": "Client", "kind": "external"},
                {"id": "p1", "label": "Validate", "kind": "process"},
                {"id": "store", "label": "DB", "kind": "store"},
            ],
            "flows": [
                {"from": "ext", "to": "p1", "label": "req"},
                {"from": "p1", "to": "store", "label": "write"},
                {"from": "ext", "to": "store", "label": "direct"},  # skip
            ],
        }
        plan = self.gm.plan_dfd(spec)
        # just must not crash and must produce a plan
        self.assertIn("nodes", plan)


class ProbeMp4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")

    def test_probe_mp4_real_file(self):
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg unavailable")
        # create a tiny 1-frame mp4 then probe it
        tmp = Path(tempfile.mkdtemp())
        png = tmp / "frame0000.png"
        from PIL import Image
        Image.new("RGB", (64, 64), "black").save(png)
        mp4 = tmp / "out.mp4"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "1",
                        "-i", str(tmp / "frame%04d.png"), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(mp4)], capture_output=True)
        if not mp4.is_file():
            self.skipTest("ffmpeg failed to create mp4")
        stream = self.rad._probe_mp4(mp4)
        self.assertIsNotNone(stream)
        self.assertEqual(int(stream["width"]), 64)
        self.assertEqual(stream["pix_fmt"], "yuv420p")

    def test_probe_mp4_missing_file_returns_none(self):
        self.assertIsNone(self.rad._probe_mp4(Path("does-not-exist-xyz.mp4")))


if __name__ == "__main__":
    unittest.main()
