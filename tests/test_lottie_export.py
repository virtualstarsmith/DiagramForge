"""Unit tests for Lottie export (scripts/lottie_export.py).

Validates the Bodymovin JSON structure produced from a synthetic ops
document — every op type converter, flow-dot animation, pulse halos, color
parsing — without rendering. Confirms the export is structurally valid for
any lottie-web / Bodymovin consumer.
"""
import importlib.util
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(ops=None, flow_paths=None, pulse_targets=None):
    return {
        "canvas": {"width": 800, "height": 600, "fps": 20, "frames": 24},
        "bg": "#0f172a",
        "theme": {"core_stroke": "#3b82f6", "green": "#22c55e", "purple": "#a855f7"},
        "ops": ops or [],
        "animation": {
            "flow_paths": flow_paths or [],
            "pulse_targets": pulse_targets or [],
        },
        "finish": {"mode": "dark"},
    }


class LottieExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.le = load_module("lottie_export")

    def _build(self, **kw):
        return self.le.build_lottie(_doc(**kw))

    def test_top_level_schema(self):
        lt = self._build()
        for key in ("v", "fr", "ip", "op", "w", "h", "nm", "ddd", "assets", "layers"):
            self.assertIn(key, lt)
        self.assertEqual(lt["fr"], 20)
        self.assertEqual(lt["w"], 800)
        self.assertEqual(lt["h"], 600)
        self.assertEqual(lt["ip"], 0)
        self.assertEqual(lt["op"], 24)

    def test_background_layer_present(self):
        lt = self._build()
        self.assertGreaterEqual(len(lt["layers"]), 1)

    def test_rect_op_becomes_shape_layer(self):
        ops = [{"op": "rect", "x": 10, "y": 20, "w": 100, "h": 50, "stroke": "#fff", "fill": "#3b82f6", "width": 2}]
        lt = self._build(ops=ops)
        names = [l.get("nm") for l in lt["layers"]]
        self.assertIn("rect", names)

    def test_ellipse_op_becomes_shape_layer(self):
        ops = [{"op": "ellipse", "x": 0, "y": 0, "w": 40, "h": 40, "stroke": "#fff", "fill": "#22c55e", "width": 2}]
        lt = self._build(ops=ops)
        self.assertIn("ellipse", [l.get("nm") for l in lt["layers"]])

    def test_diamond_op_becomes_shape_layer(self):
        ops = [{"op": "diamond", "x": 0, "y": 0, "w": 80, "h": 80, "stroke": "#a855f7", "fill": "#0f172a", "width": 2}]
        lt = self._build(ops=ops)
        self.assertIn("diamond", [l.get("nm") for l in lt["layers"]])

    def test_line_op_becomes_shape_layer(self):
        ops = [{"op": "line", "points": [[0, 0], [100, 50]], "stroke": "#fff", "width": 2, "style": "solid", "arrow": False}]
        lt = self._build(ops=ops)
        self.assertIn("line", [l.get("nm") for l in lt["layers"]])

    def test_line_with_arrowhead(self):
        ops = [{"op": "line", "points": [[0, 0], [100, 0]], "stroke": "#fff", "width": 2, "style": "solid", "arrow": "open"}]
        lt = self._build(ops=ops)
        line_layer = next(l for l in lt["layers"] if l.get("nm") == "line")
        # the arrow is a nested group inside the line group's items
        line_group = next(g for g in line_layer["shapes"] if g.get("nm") == "LineGroup")
        names = [it.get("nm") for it in line_group["it"]]
        self.assertIn("ArrowGroup", names)

    def test_text_op_becomes_text_layer(self):
        ops = [{"op": "text", "text": "Hello", "x": 10, "y": 10, "w": 100, "h": 30, "size": 16, "color": "#ffffff", "align": "center"}]
        lt = self._build(ops=ops)
        text_layers = [l for l in lt["layers"] if l.get("ty") == 5]
        self.assertEqual(len(text_layers), 1)
        self.assertEqual(text_layers[0]["t"]["d"]["k"][0]["s"]["t"], "Hello")

    def test_icon_op_becodes_breathing_layer(self):
        ops = [{"op": "icon", "name": "brain", "x": 10, "y": 10, "tile": 50, "accent": "#3b82f6"}]
        lt = self._build(ops=ops)
        icon_layer = next(l for l in lt["layers"] if l.get("nm") == "icon")
        # scale is animated (breathing)
        self.assertEqual(icon_layer["ks"]["s"]["a"], 1)
        self.assertGreaterEqual(len(icon_layer["ks"]["s"]["k"]), 2)

    def test_flow_path_becomes_animated_dot(self):
        flow = [{"points": [[0, 0], [100, 0], [200, 50]], "color": "core_stroke", "offset": 0.0}]
        lt = self._build(flow_paths=flow)
        flow_layers = [l for l in lt["layers"] if l.get("nm") == "flow"]
        self.assertEqual(len(flow_layers), 1)
        # position is animated along the polyline
        self.assertEqual(flow_layers[0]["ks"]["p"]["a"], 1)
        self.assertGreaterEqual(len(flow_layers[0]["ks"]["p"]["k"]), 4)

    def test_pulse_target_becomes_breathing_halo(self):
        pulse = [{"box": [10, 10, 110, 60], "color": "green"}]
        lt = self._build(pulse_targets=pulse)
        pulse_layers = [l for l in lt["layers"] if l.get("nm") == "pulse"]
        self.assertEqual(len(pulse_layers), 1)

    def test_layers_have_unique_inds(self):
        ops = [
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "stroke": "#fff", "fill": "#fff", "width": 1},
            {"op": "ellipse", "x": 0, "y": 0, "w": 10, "h": 10, "stroke": "#fff", "fill": "#fff", "width": 1},
        ]
        lt = self._build(ops=ops)
        inds = [l["ind"] for l in lt["layers"]]
        self.assertEqual(len(inds), len(set(inds)))

    def test_export_lottie_writes_valid_json(self):
        import tempfile
        ops = [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "stroke": "#fff", "width": 1}]
        d = _doc(ops=ops)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = Path(f.name)
        try:
            self.le.export_lottie(d, path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["v"], self.le.LOTTIE_VERSION)
        finally:
            path.unlink(missing_ok=True)

    def test_hex_to_rgb(self):
        self.assertEqual(self.le._hex_to_rgb("#ffffff"), [1.0, 1.0, 1.0])
        self.assertEqual(self.le._hex_to_rgb("#000000"), [0.0, 0.0, 0.0])
        self.assertEqual(self.le._hex_to_rgb("#f00"), [1.0, 0.0, 0.0])  # short form
        self.assertIsNone(self.le._hex_to_rgb("none"))
        self.assertIsNone(self.le._hex_to_rgb("transparent"))

    def test_polyline_sampling_loops(self):
        pts = [[0, 0], [100, 0]]
        sampled = self.le._sample_polyline(pts, 5)
        self.assertEqual(len(sampled), 5)
        # evenly spaced along x (covers [0, total); loop dots close the seam)
        self.assertAlmostEqual(sampled[0][0], 0, places=1)
        xs = [p[0] for p in sampled]
        self.assertEqual(xs, sorted(xs))  # monotonically increasing
        gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        self.assertTrue(all(abs(g - gaps[0]) < 0.5 for g in gaps))  # uniform spacing

    def test_signature_op_skipped(self):
        """signature ops are decorative watermarks; they must not crash export."""
        ops = [{"op": "signature", "text": "@x", "x": 0, "y": 0}]
        lt = self._build(ops=ops)
        # no layer named signature
        self.assertNotIn("signature", [l.get("nm") for l in lt["layers"]])


if __name__ == "__main__":
    unittest.main()
