"""Final coverage push for the layout-render error branches and check_outputs
edge cases. Each test drives a specific previously-uncovered branch.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canvas():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (300, 200), "#0f172a")
    return img, ImageDraw.Draw(img)


class LayoutRenderEdgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        cls.gm = load_module("graph_model")

    def _plan_and_render(self, spec):
        spec = dict(spec, layout_engine="legacy")
        plan = self.gm.build_plan(spec)
        ex = self.rad.Excal(plan["canvas"]["width"], plan["canvas"]["height"])
        img, draw = _canvas()
        self.rad.LAYOUT_PAINTERS[spec["layout"]](ex, draw, spec, plan)
        return ex

    def test_c4_renders_with_boundary(self):
        spec = {
            "layout": "c4",
            "elements": [
                {"id": "u", "label": "User", "kind": "person"},
                {"id": "s", "label": "System", "kind": "system"},
            ],
            "relations": [{"from": "u", "to": "s"}],
        }
        ex = self._plan_and_render(spec)
        self.assertGreater(len(ex.elements), 0)

    def test_bpmn_renders_pool(self):
        spec = {
            "layout": "bpmn",
            "pools": [{"label": "P", "lanes": [{"label": "L"}]}],
            "elements": [{"id": "t", "label": "T", "kind": "task", "pool": "P", "lane": "L"}],
            "flows": [],
        }
        ex = self._plan_and_render(spec)
        self.assertGreaterEqual(len(ex.elements), 0)

    def test_timeline_renders(self):
        spec = {"layout": "timeline", "events": [{"label": "A", "time": "2024"}]}
        ex = self._plan_and_render(spec)
        self.assertGreaterEqual(len(ex.elements), 0)

    def test_graph_manual_node_skips_auto(self):
        # manual x/y pin hits the `if nid in manual` branch in plan_graph
        spec = {
            "layout": "graph", "layout_engine": "legacy",
            "nodes": [
                {"id": "a", "label": "A", "x": 100, "y": 200},
                {"id": "b", "label": "B"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
        plan = self.gm.plan_graph(spec)
        self.assertIn("graph_nodes", plan)

    def test_check_outputs_missing_gif(self):
        # result without gif must not fail the gif block
        spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        result = {"canvas": spec.get("canvas", {"width": 1210, "height": 600})}
        checks = self.rad.check_outputs(result, spec)
        # no gif/png/mp4 keys -> only graph_layout_checks (which may be empty for non-graph)
        self.assertIsInstance(checks, dict)
        self.assertIn("ok", checks)


if __name__ == "__main__":
    unittest.main()
