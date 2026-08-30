#!/usr/bin/env python3
"""tests/test_lint_geometry.py — connector-geometry contract.

Two layers:

1. Unit tests: each lint_geometry check fires on a synthetic bad op stream and
   stays quiet on the equivalent good stream.
2. Examples ratchet: every shipped example spec is linted through the real
   render pipeline; specs not in tests/fixtures/lint_geometry_baseline.json
   must be fully clean, and baselined specs may not gain violations (counts
   per category may only shrink — delete baseline entries as they are fixed).
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import lint_geometry  # noqa: E402

BG = "#0f172a"
NODE = {"op": "rect", "x": 100, "y": 100, "w": 120, "h": 60, "stroke": "#e2e8f0",
        "fill": "#1e293b", "width": 2, "radius": 8, "style": "solid"}
NODE2 = {"op": "rect", "x": 400, "y": 100, "w": 120, "h": 60, "stroke": "#e2e8f0",
         "fill": "#1e293b", "width": 2, "radius": 8, "style": "solid"}


def _line(points, style="solid"):
    return {"op": "line", "points": [list(p) for p in points], "stroke": "#94a3b8",
            "width": 2, "style": style, "arrow": "open"}


def _mask(x, y, w=40, h=14):
    return {"op": "rect", "x": x, "y": y, "w": w, "h": h, "stroke": BG, "fill": BG,
            "width": 1, "radius": 4, "style": "solid", "role": "edge-label-mask"}


def _cats(violations):
    return {v["category"] for v in violations}


class DiagonalConnectorTest(unittest.TestCase):
    def test_flags_long_diagonal(self):
        ops = [_line([(0, 0), (100, 100)])]
        self.assertIn("diagonal-connector", _cats(lint_geometry.lint_ops(ops, layout="graph")))

    def test_short_diagonal_is_glyph(self):
        ops = [_line([(0, 0), (20, 25)])]
        self.assertNotIn("diagonal-connector", _cats(lint_geometry.lint_ops(ops, layout="graph")))

    def test_orthogonal_passes(self):
        ops = [_line([(0, 0), (100, 0), (100, 80)])]
        self.assertEqual([], lint_geometry.lint_ops(ops, layout="graph"))

    def test_exempt_layout(self):
        ops = [_line([(0, 0), (100, 100)])]
        self.assertEqual([], lint_geometry.lint_ops(ops, layout="fishbone"))


class MaskCoveredTest(unittest.TestCase):
    def test_flags_node_drawn_after_mask(self):
        ops = [_mask(150, 110), dict(NODE)]
        self.assertIn("label-mask-covered", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_node_drawn_before_mask_is_fine(self):
        ops = [dict(NODE), _mask(150, 110)]
        self.assertNotIn("label-mask-covered", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_paper_filled_diamond_is_not_a_node(self):
        # Hollow aggregation diamonds (fill == page bg) are glyphs.
        diamond = {"op": "diamond", "x": 150, "y": 108, "w": 24, "h": 14,
                   "stroke": "#e2e8f0", "fill": BG, "width": 2}
        ops = [_mask(148, 106, w=30), diamond]
        self.assertNotIn("label-mask-covered", _cats(lint_geometry.lint_ops(ops, bg=BG)))


class AttachFanTest(unittest.TestCase):
    def test_flags_close_attach_points(self):
        ops = [dict(NODE),
               _line([(120, 160), (120, 220)]),
               _line([(128, 160), (128, 220)])]
        self.assertIn("attach-point-fan", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_fanned_attach_points_pass(self):
        ops = [dict(NODE),
               _line([(120, 160), (120, 220)]),
               _line([(180, 160), (180, 220)])]
        self.assertNotIn("attach-point-fan", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_shared_bus_origin_exempt(self):
        ops = [dict(NODE),
               _line([(160, 160), (160, 220), (60, 260)]),
               _line([(160, 160), (160, 220), (260, 260)])]
        self.assertNotIn("attach-point-fan", _cats(lint_geometry.lint_ops(ops, bg=BG)))


class ThroughNodeTest(unittest.TestCase):
    def test_flags_transit_through_third_node(self):
        blocker = {"op": "rect", "x": 240, "y": 100, "w": 80, "h": 60, "stroke": "#e2e8f0",
                   "fill": "#1e293b", "width": 2, "radius": 8, "style": "solid"}
        ops = [dict(NODE), blocker, dict(NODE2), _line([(220, 130), (400, 130)])]
        self.assertIn("connector-through-node", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_dashed_transit_exempt(self):
        blocker = {"op": "rect", "x": 240, "y": 100, "w": 80, "h": 60, "stroke": "#e2e8f0",
                   "fill": "#1e293b", "width": 2, "radius": 8, "style": "solid"}
        ops = [dict(NODE), blocker, dict(NODE2), _line([(220, 130), (400, 130)], style="dashed")]
        self.assertNotIn("connector-through-node", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_endpoint_node_not_flagged(self):
        ops = [dict(NODE), dict(NODE2), _line([(220, 130), (400, 130)])]
        self.assertNotIn("connector-through-node", _cats(lint_geometry.lint_ops(ops, bg=BG)))


class LabelLineGapTest(unittest.TestCase):
    def test_flags_mask_on_line(self):
        ops = [_line([(0, 100), (300, 100)]), _mask(140, 94)]
        self.assertIn("label-line-gap", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_mask_with_gap_passes(self):
        ops = [_line([(0, 100), (300, 100)]), _mask(140, 76)]  # mask bottom 90, line 100
        self.assertNotIn("label-line-gap", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_dashed_line_not_flagged(self):
        ops = [_line([(0, 100), (300, 100)], style="dashed"), _mask(140, 94)]
        self.assertNotIn("label-line-gap", _cats(lint_geometry.lint_ops(ops, bg=BG)))


class OffGridTest(unittest.TestCase):
    def test_flags_off_grid_rect(self):
        ops = [dict(NODE, x=101)]
        self.assertIn("off-grid", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_snapped_ops_pass(self):
        ops = [dict(NODE), _line([(220, 128), (400, 128)]), dict(NODE2)]
        self.assertNotIn("off-grid", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_label_mask_exempt(self):
        ops = [_mask(150.5, 106.25)]
        self.assertNotIn("off-grid", _cats(lint_geometry.lint_ops(ops, bg=BG)))

    def test_icon_exempt(self):
        ops = [{"op": "icon", "name": "server", "semantic": "server", "x": 101.5, "y": 203.25, "scale": 1.0}]
        self.assertNotIn("off-grid", _cats(lint_geometry.lint_ops(ops, bg=BG)))


class CliTest(unittest.TestCase):
    def _write_ops(self, tmp, ops):
        path = Path(tmp) / "ops.json"
        path.write_text(json.dumps({"ops": ops, "layout": "graph", "bg": BG}), encoding="utf-8")
        return path

    def test_clean_exit_0(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_ops(tmp, [_line([(0, 0), (100, 0)])])
            proc = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "scripts" / "lint_geometry.py"), str(path)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_violation_exit_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_ops(tmp, [_line([(0, 0), (100, 100)])])
            proc = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "scripts" / "lint_geometry.py"), str(path)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["ok"])
            self.assertEqual(report["files"][0]["violations"][0]["category"], "diagonal-connector")

    def test_missing_file_exit_2(self):
        proc = subprocess.run([sys.executable, "-X", "utf8", str(REPO / "scripts" / "lint_geometry.py"), "nope.json"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


class ExamplesRatchetTest(unittest.TestCase):
    """Shipped examples stay inside the grandfathered baseline (counts per
    category may only shrink; specs absent from the baseline must be clean)."""

    @classmethod
    def setUpClass(cls):
        import render_animated_diagram as rad
        cls.rad = rad
        cls.baseline = json.loads(
            (REPO / "tests" / "fixtures" / "lint_geometry_baseline.json").read_text(encoding="utf-8"))
        cls.baseline.pop("_comment", None)

    def _lint_spec(self, path):
        spec = json.loads(path.read_text(encoding="utf-8"))
        _ex, _img, doc = self.rad.render_static_with_ops(spec)
        return lint_geometry.lint_doc(doc)

    def test_examples_within_baseline(self):
        failures = []
        for path in sorted((REPO / "assets" / "examples").glob("*-spec.json")):
            violations = self._lint_spec(path)
            counts = {}
            for v in violations:
                counts[v["category"]] = counts.get(v["category"], 0) + 1
            allowed = self.baseline.get(path.name, {})
            for cat, count in counts.items():
                if count > allowed.get(cat, 0):
                    failures.append(f"{path.name}: {cat} x{count} exceeds baseline x{allowed.get(cat, 0)}")
        self.assertEqual([], failures)


class CheckOutputsWiringTest(unittest.TestCase):
    def test_geometry_violations_surface_as_named_checks(self):
        import render_animated_diagram as rad
        result = {"geometry_lint": [
            {"category": "diagonal-connector", "message": "op#3 diagonal", "op": 3},
        ]}
        report = rad.check_outputs(result, {"layout": "graph", "title": {"prefix": "t", "highlight": "h"}})
        by_name = {c["name"]: c for c in report["checks"]}
        self.assertIn("geometry_diagonal_connector", by_name)
        self.assertFalse(by_name["geometry_diagonal_connector"]["ok"])
        self.assertFalse(report["ok"])

    def test_clean_geometry_passes(self):
        import render_animated_diagram as rad
        result = {"geometry_lint": []}
        report = rad.check_outputs(result, {"layout": "graph", "title": {"prefix": "t", "highlight": "h"}})
        geo = [c for c in report["checks"] if c["name"].startswith("geometry_")]
        self.assertEqual(6, len(geo))
        self.assertTrue(all(c["ok"] for c in geo))


if __name__ == "__main__":
    unittest.main()
