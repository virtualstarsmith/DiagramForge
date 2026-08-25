"""Tests for the ELK.js layout engine path of ``plan_graph``.

The legacy layout is covered by test_graph_model.py (pinned via
``layout_engine: "legacy"``). These tests exercise the default ELK path —
structural contract, loop styling, canvas fit, and graceful fallback —
without asserting exact coordinates (ELK positions are deterministic but
version-dependent).
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


def _spec(direction="right"):
    return {
        "layout": "graph",
        "direction": direction,
        "nodes": [
            {"id": "ingest", "label": "Ingest", "icon": "ingest"},
            {"id": "plan", "label": "Plan", "icon": "plan"},
            {"id": "act", "label": "Act", "icon": "agent"},
            {"id": "gate", "label": "Pass?", "kind": "decision"},
            {"id": "ship", "label": "Ship", "kind": "terminal"},
        ],
        "edges": [
            {"from": "ingest", "to": "plan"},
            {"from": "plan", "to": "act"},
            {"from": "act", "to": "gate"},
            {"from": "gate", "to": "ship", "label": "yes"},
            {"from": "gate", "to": "act", "kind": "loop", "label": "retry"},
        ],
    }


class ElkLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")
        cls.elk_layout = load_module("elk_layout")
        if not cls.elk_layout.is_available():
            raise unittest.SkipTest("ELK.js not bundled; skipping ELK layout tests")

    def test_elk_plan_has_full_structure(self):
        plan = self.graph_model.plan_graph(_spec())
        for key in ("layout", "canvas", "frame", "graph_nodes", "graph_edges",
                    "graph_meta", "flow_paths", "pulse_targets", "icons",
                    "nodes", "edges"):
            self.assertIn(key, plan, key)
        self.assertEqual(plan["layout"], "graph")
        self.assertEqual(plan["graph_meta"].get("layout_engine"), "elk")

    def test_every_node_has_private_geometry_fields(self):
        plan = self.graph_model.plan_graph(_spec())
        for node in plan["graph_nodes"]:
            for field in ("_box", "_center", "_accent", "_fill", "_kind"):
                self.assertIn(field, node, (field, node.get("id")))
            box = node["_box"]
            self.assertEqual(len(box), 4)
            self.assertGreater(box[2], 0)  # width
            self.assertGreater(box[3], 0)  # height

    def test_loop_edges_are_dashed(self):
        plan = self.graph_model.plan_graph(_spec())
        loops = [e for e in plan["graph_edges"] if e["loop"]]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["style"], "dashed")
        # non-loop edges are solid by default
        forwards = [e for e in plan["graph_edges"] if not e["loop"]]
        self.assertTrue(all(e["style"] == "solid" for e in forwards))

    def test_content_fits_within_canvas(self):
        plan = self.graph_model.plan_graph(_spec())
        width = plan["canvas"]["width"]
        height = plan["canvas"]["height"]
        xs, ys = [], []
        for node in plan["graph_nodes"]:
            x, y, w, h = node["_box"]
            xs += [x, x + w]
            ys += [y, y + h]
        for edge in plan["graph_edges"]:
            for px, py in edge["points"]:
                xs.append(px)
                ys.append(py)
        # Content must stay inside the frame with a little slack; ELK routes
        # can touch the frame edge but should never clip badly.
        self.assertGreaterEqual(min(xs), 10, msg=f"left clip: {min(xs)}")
        self.assertLessEqual(max(xs), width - 10, msg=f"right clip: {max(xs)} > {width}")
        self.assertGreaterEqual(min(ys), 100, msg=f"top clip: {min(ys)}")
        self.assertLessEqual(max(ys), height - 30, msg=f"bottom clip: {max(ys)} > {height}")

    def test_flow_paths_match_edge_count(self):
        plan = self.graph_model.plan_graph(_spec())
        self.assertEqual(len(plan["flow_paths"]), len(plan["graph_edges"]))
        for fp in plan["flow_paths"]:
            self.assertGreaterEqual(len(fp["points"]), 2)
            self.assertIn("color", fp)
            self.assertIn("offset", fp)

    def test_pulse_targets_match_node_count(self):
        plan = self.graph_model.plan_graph(_spec())
        self.assertEqual(len(plan["pulse_targets"]), len(plan["graph_nodes"]))

    def test_plan_is_json_serializable(self):
        plan = self.graph_model.plan_graph(_spec())
        # tuples (points) must be converted before json.dumps; mirror what the
        # renderer does when emitting the ops document.
        edges = [dict(e, points=[list(p) for p in e["points"]]) for e in plan["edges"]]
        json.dumps({"nodes": plan["nodes"], "edges": edges,
                    "flow": plan["flow_paths"], "pulse": plan["pulse_targets"]})

    def test_direction_down_produces_tall_canvas(self):
        plan = self.graph_model.plan_graph(_spec(direction="down"))
        # Vertical layout: the content should span meaningfully down the canvas
        # (the loop back-edge means ELK may not place every node in a strict
        # monotonic y order, so we assert vertical span instead).
        ys = [n["_box"][1] for n in plan["graph_nodes"]]
        self.assertGreater(max(ys) - min(ys), 200)
        self.assertGreater(plan["canvas"]["height"], 500)

    def test_large_graph_does_not_explode_canvas(self):
        nodes = [{"id": f"n{i}", "label": f"N{i}"} for i in range(15)]
        edges = [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(14)]
        spec = {"layout": "graph", "direction": "right", "nodes": nodes, "edges": edges}
        plan = self.graph_model.plan_graph(spec)
        self.assertLess(plan["canvas"]["height"], 3000)
        self.assertEqual(plan["canvas"]["width"], 1210)


if __name__ == "__main__":
    unittest.main()
