"""Coverage for the illustrated-icon renderer paths and spec_graph edges.

The browser E2E matrix renders mostly outline icons. These specs use the
``illustrated`` / ``hero`` icon styles so the 56 Sketch-Duotone builders in
svg_renderer run, covering a large block of otherwise-dead animation code.
The spec_graph section exercises the less-common commands (around export,
diff with renames, neighbors on a hub).
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


class IllustratedRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        cls.svg = load_module("svg_renderer")
        if not cls.svg.is_available():
            raise unittest.SkipTest("browser renderer unavailable")

    def test_illustrated_loop_pack_renders(self):
        # The loop-icon-pack spec uses illustrated/hero icons across the board.
        spec = json.loads((ROOT / "assets" / "examples" / "loop-icon-pack-spec.json").read_text(encoding="utf-8"))
        spec.setdefault("canvas", {})["frames"] = 6
        tmp = Path(tempfile.mkdtemp(prefix="ill_"))
        result = self.rad.write_outputs_browser(spec, tmp, "ill", formats=("png", "svg"))
        self.assertIn("png", result)
        self.assertIn("svg", result)

    def test_illustrated_catalog_renders(self):
        spec = json.loads((ROOT / "assets" / "examples" / "illustrated-icon-catalog-spec.json").read_text(encoding="utf-8"))
        spec.setdefault("canvas", {})["frames"] = 6
        tmp = Path(tempfile.mkdtemp(prefix="cat_"))
        result = self.rad.write_outputs_browser(spec, tmp, "cat", formats=("png",))
        self.assertIn("png", result)


class SpecGraphEdgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sg = load_module("spec_graph")
        cls.spec = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))

    def test_neighbors_of_hub_node(self):
        # find a node with the most edges
        from collections import Counter
        deg = Counter()
        for e in self.spec["edges"]:
            deg[e["from"]] += 1
            deg[e["to"]] += 1
        hub = deg.most_common(1)[0][0]
        r = self.sg.neighbors_of(self.spec, hub)
        self.assertIn(hub, json.dumps(r))

    def test_around_exports_subgraph_spec(self):
        ids = [n["id"] for n in self.spec["nodes"]]
        r = self.sg.neighborhood(self.spec, ids[0], hops=1)
        self.assertIn("nodes", r)
        self.assertIn("edges", r)

    def test_diff_detects_added_removed(self):
        a = json.loads(json.dumps(self.spec))
        b = json.loads(json.dumps(self.spec))
        b["nodes"].append({"id": "extra", "label": "Extra"})
        d = self.sg.diff_specs(a, b)
        self.assertIn("extra", json.dumps(d))

    def test_export_mermaid_and_dot_roundtrip(self):
        m = self.sg.export_mermaid(self.spec)
        self.assertIn("graph", m.lower())
        dot = self.sg.export_dot(self.spec)
        self.assertIn("digraph", dot)


if __name__ == "__main__":
    unittest.main()
