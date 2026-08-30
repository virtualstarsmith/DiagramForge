"""tests for the figurative graph node kinds: person / database / document."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import graph_model
import render_animated_diagram as rad

EXAMPLES = REPO / "assets" / "examples"


def _spec_with_kinds(kinds):
    nodes = [{"id": f"n{i}", "label": f"N{i}", "kind": k} for i, k in enumerate(kinds)]
    edges = [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(len(kinds) - 1)]
    return {"layout": "graph", "style": "slate", "nodes": nodes, "edges": edges}


class KindTests(unittest.TestCase):
    def test_kind_vocabulary(self):
        for kind in ("person", "database", "document"):
            self.assertIn(kind, graph_model.GRAPH_NODE_KINDS)

    def test_unknown_kind_still_rejected(self):
        report = rad.validate_spec(_spec_with_kinds(["card", "megaphone"]))
        kind_errors = [e for e in report["errors"] if e["path"].endswith(".kind")]
        self.assertTrue(kind_errors)
        self.assertIn("person, database, or document", kind_errors[0]["fix"])

    def test_planned_sizes_follow_kind(self):
        spec = _spec_with_kinds(["person", "database", "document"])
        rad.apply_style("slate")
        _ex, _img, doc = rad.render_static_with_ops(spec)
        sizes = {(n["kind"]): (n["w"], n["h"]) for n in doc["graph"]["nodes"]}
        self.assertEqual(sizes["person"], graph_model.PERSON_SIZE)
        self.assertEqual(sizes["database"], graph_model.DATABASE_SIZE)
        self.assertGreaterEqual(sizes["document"][1], 72)


class PainterTests(unittest.TestCase):
    def _render(self, spec):
        rad.apply_style(spec.get("style", "slate"))
        _ex, _img, doc = rad.render_static_with_ops(spec)
        return doc

    def _in_box(self, op, box, margin=2):
        pts = op.get("points") or [[op.get("x"), op.get("y")]]
        return all(
            box[0] - margin <= px <= box[0] + box[2] + margin and
            box[1] - margin <= py <= box[1] + box[3] + margin
            for px, py in pts
        )

    def test_person_draws_head_and_torso(self):
        doc = self._render(_spec_with_kinds(["person", "person"]))
        node = doc["graph"]["nodes"][0]
        box = (node["x"], node["y"], node["w"], node["h"])
        heads = [op for op in doc["ops"] if op["op"] == "ellipse" and self._in_box(op, box)]
        self.assertEqual(len(heads), 1, "one head ellipse per person")
        self.assertEqual((heads[0]["w"], heads[0]["h"]), (20, 20))

    def test_database_draws_cylinder(self):
        doc = self._render(_spec_with_kinds(["database"]))
        node = doc["graph"]["nodes"][0]
        box = (node["x"], node["y"], node["w"], node["h"])
        ellipses = [op for op in doc["ops"] if op["op"] == "ellipse" and self._in_box(op, box)]
        walls = [op for op in doc["ops"] if op["op"] == "line" and self._in_box(op, box)]
        self.assertEqual(len(ellipses), 2, "top and bottom lip")
        self.assertEqual(len(walls), 2, "left and right wall")

    def test_document_has_cut_corner(self):
        doc = self._render(_spec_with_kinds(["document"]))
        node = doc["graph"]["nodes"][0]
        box = (node["x"], node["y"], node["w"], node["h"])
        bg = doc["bg"]
        patches = [op for op in doc["ops"]
                   if op["op"] == "rect" and op.get("fill") == bg and op.get("stroke") == bg
                   and self._in_box(op, box)]
        cuts = [op for op in doc["ops"] if op["op"] == "line" and self._in_box(op, box)]
        self.assertEqual(len(patches), 1, "one paper patch cuts the dog-ear corner")
        self.assertEqual(len(cuts), 1, "one diagonal cut line")

    def test_example_renders_and_is_geometry_clean(self):
        spec = json.loads((EXAMPLES / "graph-shapes-spec.json").read_text(encoding="utf-8"))
        report = rad.validate_spec(spec, spec_dir=str(EXAMPLES))
        self.assertTrue(report["ok"], report["errors"])
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs(spec, Path(td), "shapes", formats=("png", "drawio", "excalidraw"))
            violations = res["geometry_lint"]
            self.assertEqual(
                [v["category"] for v in violations], [],
                f"new shipped example must be geometry-clean: {violations}")
            chk = rad.check_outputs(res, spec)
            drawio_ok = all(c["ok"] for c in chk["checks"] if c["name"].startswith("drawio"))
            self.assertTrue(drawio_ok)


if __name__ == "__main__":
    unittest.main()
