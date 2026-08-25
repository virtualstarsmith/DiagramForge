import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spec_graph = load_module("spec_graph")

GRAPH_SPEC = json.loads((ROOT / "assets" / "examples" / "graph-workflow-spec.json").read_text(encoding="utf-8"))
SWIMLANE_SPEC = json.loads((ROOT / "assets" / "examples" / "swimlane-spec.json").read_text(encoding="utf-8"))
PANORAMA_SPEC = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))


class LintTest(unittest.TestCase):
    def test_clean_graph_has_no_cycle_or_orphan_noise(self):
        result = spec_graph.lint(GRAPH_SPEC)
        kinds = {issue["kind"] for issue in result["issues"]}
        self.assertNotIn("cycle", kinds)  # loops are declared kind:'loop'
        self.assertNotIn("orphan_node", kinds)
        self.assertNotIn("disconnected", kinds)

    def test_undeclared_cycle_is_flagged(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},
            ],
        }
        result = spec_graph.lint(spec)
        cycles = [i for i in result["issues"] if i["kind"] == "cycle"]
        self.assertTrue(cycles, result)

    def test_declared_loop_edge_is_not_a_cycle(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a", "kind": "loop"},
            ],
        }
        kinds = {i["kind"] for i in spec_graph.lint(spec)["issues"]}
        self.assertNotIn("cycle", kinds)

    def test_orphan_and_disconnected_detected(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "lost"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        kinds = {i["kind"] for i in spec_graph.lint(spec)["issues"]}
        self.assertIn("orphan_node", kinds)
        self.assertIn("disconnected", kinds)

    def test_chain_middle_nodes_are_not_spofs(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": c} for c in "abcde"],
            "edges": [{"from": x, "to": y} for x, y in zip("abcd", "bcde")],
        }
        kinds = {i["kind"] for i in spec_graph.lint(spec)["issues"]}
        self.assertNotIn("single_point_of_failure", kinds)

    def test_branching_junction_is_spof(self):
        spec = {
            "layout": "graph",
            "nodes": [{"id": c} for c in "abcde"],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "b", "to": "d"},
                {"from": "b", "to": "e"},
            ],
        }
        spofs = [i for i in spec_graph.lint(spec)["issues"] if i["kind"] == "single_point_of_failure"]
        self.assertTrue(any("b" in i["nodes"] for i in spofs), spofs)

    def test_swimlane_comparison_chart_is_not_disconnected(self):
        result = spec_graph.lint(SWIMLANE_SPEC)
        self.assertNotIn("disconnected", {i["kind"] for i in result["issues"]})

    def test_panorama_template_skips_topology_checks(self):
        result = spec_graph.lint(PANORAMA_SPEC)
        self.assertEqual(result["issues"], [])


class NeighborsTest(unittest.TestCase):
    def test_neighbors_reports_both_directions(self):
        result = spec_graph.neighbors_of(GRAPH_SPEC, "gate")
        self.assertEqual(result["node"]["kind"], "decision")
        self.assertIn("test", {n["id"] for n in result["depends_on"]})
        self.assertIn("ship", {n["id"] for n in result["affects"]})

    def test_unknown_node_exits(self):
        with self.assertRaises(SystemExit):
            spec_graph.neighbors_of(GRAPH_SPEC, "nope")


class AroundTest(unittest.TestCase):
    def test_one_hop_neighborhood(self):
        sub = spec_graph.neighborhood(GRAPH_SPEC, "gate", 1)
        ids = {n["id"] for n in sub["nodes"]}
        self.assertEqual(ids, {"gate", "test", "ship", "build", "plan"})
        self.assertEqual(sub["layout"], "graph")
        for edge in sub["edges"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)

    def test_decision_kind_preserved(self):
        sub = spec_graph.neighborhood(GRAPH_SPEC, "gate", 1)
        gate = next(n for n in sub["nodes"] if n["id"] == "gate")
        self.assertEqual(gate["kind"], "decision")


class DiffTest(unittest.TestCase):
    def test_diff_reports_changes(self):
        modified = json.loads(json.dumps(GRAPH_SPEC))
        modified["nodes"].append({"id": "observe", "label": "Observe"})
        modified["edges"].append({"from": "ship", "to": "observe"})
        modified["nodes"] = [n for n in modified["nodes"] if n["id"] != "memory"]
        modified["edges"] = [e for e in modified["edges"]
                             if "memory" not in (e["from"], e["to"])]
        result = spec_graph.diff_specs(GRAPH_SPEC, modified)
        self.assertIn("observe", result["nodes"]["added"])
        self.assertIn("memory", result["nodes"]["removed"])
        self.assertTrue(any(e["to"] == "observe" for e in result["edges"]["added"]))


class ExportTest(unittest.TestCase):
    def test_mermaid_export_shapes_and_edges(self):
        text = spec_graph.export_mermaid(GRAPH_SPEC)
        self.assertIn("graph LR", text)
        self.assertIn('gate{"Pass?"}', text)
        self.assertIn('ship(["Ship"])', text)
        self.assertIn('gate -. "replan" .-> plan', text)
        self.assertIn("ingest --> plan", text)

    def test_dot_export(self):
        text = spec_graph.export_dot(GRAPH_SPEC)
        self.assertIn("digraph", text)
        self.assertIn('"gate" [label="Pass?", shape=diamond];', text)
        self.assertIn("style=dashed", text)


if __name__ == "__main__":
    unittest.main()
