"""tests for scenario variants (scripts/scenarios.py) — one spec, several states."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import scenarios
import render_animated_diagram as rad

EXAMPLES = REPO / "assets" / "examples"


def _base_spec():
    return json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))


class PatchTests(unittest.TestCase):
    def test_node_merge_by_id_and_status_sugar(self):
        variant = scenarios.expand({
            "layout": "graph",
            "nodes": [
                {"id": "api", "label": "API", "accent": "blue"},
                {"id": "db", "label": "DB", "accent": "blue"},
            ],
            "edges": [{"from": "api", "to": "db", "label": "read"}],
            "scenarios": [{
                "name": "failure",
                "patch": {"nodes": [{"id": "db", "status": "failed"}]},
            }],
        })
        name, spec = variant[0]
        self.assertEqual(name, "failure")
        self.assertNotIn("scenarios", spec)
        db = next(n for n in spec["nodes"] if n["id"] == "db")
        api = next(n for n in spec["nodes"] if n["id"] == "api")
        self.assertEqual(db["accent"], "pink")   # status sugar -> semantic accent
        self.assertEqual(api["accent"], "blue")  # untouched
        self.assertEqual(db["label"], "DB")

    def test_explicit_accent_beats_status(self):
        variant = scenarios.expand({
            "layout": "graph",
            "nodes": [{"id": "db", "accent": "blue"}],
            "scenarios": [{"name": "d", "patch": {"nodes": [{"id": "db", "status": "degraded", "accent": "purple"}]}}],
        })
        node = variant[0][1]["nodes"][0]
        self.assertEqual(node["accent"], "purple")

    def test_edge_merge_by_endpoints_and_dict_merge(self):
        variant = scenarios.expand({
            "layout": "graph",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b", "label": "calls", "style": "solid"}],
            "title": {"prefix": "Sys", "highlight": "up"},
            "scenarios": [{"name": "degraded", "patch": {
                "edges": [{"from": "a", "to": "b", "style": "dashed"}],
                "title": {"highlight": "degraded"},
            }}],
        })
        spec = variant[0][1]
        self.assertEqual(spec["edges"][0]["style"], "dashed")
        self.assertEqual(spec["edges"][0]["label"], "calls")  # untouched
        self.assertEqual(spec["title"]["prefix"], "Sys")      # deep merged
        self.assertEqual(spec["title"]["highlight"], "degraded")

    def test_scenarios_key_stripped_from_variants(self):
        base = _base_spec()
        base["scenarios"] = [{"name": "normal", "patch": {"title": {"highlight": "基线"}}}]
        variants = scenarios.expand(base)
        self.assertEqual(len(variants), 1)
        self.assertNotIn("scenarios", variants[0][1])


class ValidateTests(unittest.TestCase):
    def test_valid_scenarios_pass(self):
        spec = _base_spec()
        spec["scenarios"] = [
            {"name": "degraded", "patch": {"nodes": [{"id": "x", "status": "degraded"}]}},
            {"name": "failure", "patch": {"nodes": [{"id": "x", "label": "X (down)"}]}},
        ]
        spec["nodes"].append({"id": "x", "label": "X"})
        errors, warnings = scenarios.validate(spec)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_bad_layout_errors(self):
        spec = {"layout": "er", "scenarios": [{"name": "a", "patch": {"title": {}}}]}
        errors, _ = scenarios.validate(spec)
        self.assertIn("not defined for layout 'er'", errors[0]["message"])

    def test_forbidden_patch_keys(self):
        spec = {"layout": "graph", "scenarios": [{"name": "a", "patch": {"canvas": {"width": 800}}}]}
        errors, _ = scenarios.validate(spec)
        self.assertTrue(any("cannot change in a scenario" in e["message"] for e in errors))

    def test_bad_names_and_duplicates(self):
        spec = {"layout": "graph", "scenarios": [
            {"name": "Bad Name", "patch": {"title": {}}},
            {"name": "a", "patch": {"title": {}}},
            {"name": "a", "patch": {"title": {}}},
        ]}
        errors, _ = scenarios.validate(spec)
        self.assertTrue(any("invalid scenario name" in e["message"] for e in errors))
        self.assertTrue(any("duplicate scenario name" in e["message"] for e in errors))

    def test_validate_spec_integration(self):
        spec = _base_spec()
        spec["scenarios"] = [{"name": "failure", "patch": {"nodes": []}}]
        report = rad.validate_spec(spec, spec_dir=str(EXAMPLES))
        self.assertTrue(report["ok"], report["errors"])
        spec["layout"] = "er"
        report = rad.validate_spec(spec, spec_dir=str(EXAMPLES))
        self.assertFalse(report["ok"])


class RenderTests(unittest.TestCase):
    def test_variants_render_as_sibling_outputs(self):
        spec = _base_spec()
        spec["scenarios"] = [
            {"name": "degraded", "patch": {"nodes": [{"id": "test", "status": "degraded"}]}},
            {"name": "failure", "patch": {"edges": [{"from": "build", "to": "test", "style": "dashed"}]}},
        ]
        node_ids = {n["id"] for n in spec["nodes"]}
        self.assertIn("test", node_ids)
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs(spec, Path(td), "story", formats=("png",))
            # The renderer loop lives in main(); exercise it directly here.
            for name, variant in scenarios.expand(spec):
                sres = rad.write_outputs(variant, Path(td), f"story-{name}", formats=("png",))
                self.assertTrue(Path(sres["png"]).is_file())
                self.assertEqual(sres["canvas"], res["canvas"])
            self.assertTrue((Path(td) / "story-degraded.png").is_file())
            self.assertTrue((Path(td) / "story-failure.png").is_file())
            self.assertTrue((Path(td) / "story.png").is_file())


if __name__ == "__main__":
    unittest.main()
