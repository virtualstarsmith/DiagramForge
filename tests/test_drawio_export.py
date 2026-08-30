"""tests for scripts/drawio_export.py — the draw.io editable-output format."""
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import drawio_export
import render_animated_diagram as rad

EXAMPLES = REPO / "assets" / "examples"


def _doc(ops, width=400, height=300, bg="#111111", layout="graph"):
    return {"canvas": {"width": width, "height": height}, "bg": bg, "layout": layout, "ops": ops}


class BuildTests(unittest.TestCase):
    def test_shapes_become_vertices_with_styles(self):
        ops = [
            {"op": "rect", "x": 40, "y": 40, "w": 120, "h": 48, "stroke": "#3b82f6", "fill": "#1e3a5f",
             "width": 2, "radius": 8, "style": "solid"},
            {"op": "ellipse", "x": 200, "y": 40, "w": 80, "h": 80, "stroke": "#22c55e", "fill": None, "width": 2},
            {"op": "diamond", "x": 40, "y": 160, "w": 100, "h": 60, "stroke": "#f59e0b", "fill": "#3a2c10",
             "width": 2, "style": "solid"},
        ]
        xml_text, report = drawio_export.build_drawio(_doc(ops))
        root = ET.fromstring(xml_text)
        self.assertEqual(root.tag, "mxfile")
        vertices = [c for c in root.iter("mxCell") if c.get("vertex") == "1"]
        self.assertEqual(len(vertices), 3)
        styles = [c.get("style") for c in vertices]
        self.assertIn("rounded=1;absoluteArcSize=1;arcSize=8", styles[0])
        self.assertIn("fillColor=#1e3a5f", styles[0])
        self.assertTrue(styles[1].startswith("ellipse"))
        self.assertIn("fillColor=none", styles[1])
        self.assertTrue(styles[2].startswith("rhombus"))
        self.assertEqual(report["vertices"], 3)
        self.assertEqual(report["edges"], 0)

    def test_edge_binds_to_shapes_it_touches(self):
        ops = [
            {"op": "rect", "x": 40, "y": 40, "w": 80, "h": 40, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "rect", "x": 240, "y": 40, "w": 80, "h": 40, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "line", "points": [[120, 60], [180, 60], [240, 60]], "stroke": "#fff", "width": 2,
             "style": "solid", "arrow": "open"},
        ]
        xml_text, report = drawio_export.build_drawio(_doc(ops))
        root = ET.fromstring(xml_text)
        edge = next(c for c in root.iter("mxCell") if c.get("edge") == "1")
        self.assertTrue(edge.get("source") and edge.get("target"), "edge must bind to both shapes")
        self.assertNotIn("endArrow=none", edge.get("style"))
        self.assertIn("endArrow=open", edge.get("style"))
        self.assertEqual(report["edges_bound"], 1)

    def test_edge_painted_before_nodes_still_binds(self):
        # Two-pass z-order: edges first, nodes after.
        ops = [
            {"op": "line", "points": [[120, 60], [240, 60]], "stroke": "#fff", "width": 2, "arrow": "open"},
            {"op": "rect", "x": 40, "y": 40, "w": 80, "h": 40, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "rect", "x": 240, "y": 40, "w": 80, "h": 40, "stroke": "#fff", "fill": "#223", "width": 2},
        ]
        root = ET.fromstring(drawio_export.build_drawio(_doc(ops))[0])
        edge = next(c for c in root.iter("mxCell") if c.get("edge") == "1")
        self.assertTrue(edge.get("source") and edge.get("target"))

    def test_unbound_edge_keeps_endpoints_as_geometry(self):
        ops = [
            {"op": "line", "points": [[10, 10], [80, 10]], "stroke": "#fff", "width": 2},
        ]
        root = ET.fromstring(drawio_export.build_drawio(_doc(ops))[0])
        edge = next(c for c in root.iter("mxCell") if c.get("edge") == "1")
        self.assertIsNone(edge.get("source"))
        pts = {p.get("as"): p for p in edge.iter("mxPoint")}
        self.assertEqual(pts["sourcePoint"].get("x"), "10")
        self.assertEqual(pts["targetPoint"].get("x"), "80")

    def test_dashed_line_and_filled_arrowhead(self):
        ops = [
            {"op": "line", "points": [[0, 0], [100, 0]], "stroke": "#fff", "width": 2, "style": "dashed",
             "arrow": "filled"},
        ]
        root = ET.fromstring(drawio_export.build_drawio(_doc(ops))[0])
        style = next(c for c in root.iter("mxCell") if c.get("edge") == "1").get("style")
        self.assertIn("dashed=1", style)
        self.assertIn("endArrow=block", style)

    def test_text_joins_node_value_and_edge_label_claims_nearest(self):
        ops = [
            {"op": "rect", "x": 40, "y": 40, "w": 120, "h": 60, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "rect", "x": 280, "y": 40, "w": 120, "h": 60, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "line", "points": [[160, 70], [280, 70]], "stroke": "#fff", "width": 2, "arrow": "open"},
            {"op": "text", "text": "API", "x": 60, "y": 56, "w": 80, "h": 20, "size": 13, "color": "#fff"},
            {"op": "text", "text": "calls", "x": 185, "y": 44, "w": 60, "h": 18, "size": 11, "color": "#fff",
             "role": "edge-label"},
            {"op": "text", "text": "Standalone note", "x": 60, "y": 200, "w": 120, "h": 20, "size": 12,
             "color": "#fff"},
        ]
        xml_text, report = drawio_export.build_drawio(_doc(ops))
        root = ET.fromstring(xml_text)
        by_id = {c.get("id"): c for c in root.iter("mxCell") if c.get("id") not in ("0", "1")}
        vertices = [c for c in by_id.values() if c.get("vertex") == "1"]
        edges = [c for c in by_id.values() if c.get("edge") == "1"]
        labels = sorted(c.get("value") for c in vertices)
        self.assertIn("API", labels)
        self.assertIn("Standalone note", labels)
        self.assertEqual(edges[0].get("value"), "calls")
        self.assertEqual(report["skipped_ops"], 0)

    def test_masks_and_icons_are_skipped(self):
        ops = [
            {"op": "rect", "x": 40, "y": 40, "w": 120, "h": 60, "stroke": "#fff", "fill": "#223", "width": 2},
            {"op": "rect", "x": 50, "y": 50, "w": 100, "h": 16, "stroke": "#111111", "fill": "#111111",
             "width": 1, "role": "edge-label-mask"},
            {"op": "icon", "name": "server", "semantic": "compute", "x": 60, "y": 60, "w": 24, "h": 24},
            {"op": "signature", "text": "@sig", "x": 10, "y": 10, "stretch": 1.0},
        ]
        xml_text, report = drawio_export.build_drawio(_doc(ops))
        root = ET.fromstring(xml_text)
        vertices = [c for c in root.iter("mxCell") if c.get("vertex") == "1"]
        self.assertEqual(len(vertices), 1, "only the node itself is a vertex")
        self.assertEqual(report["skipped_ops"], 2)

    def test_xml_escapes_hostile_labels(self):
        # Source labels are data, never instructions — the exporter must escape
        # them so no live element survives a round-trip through the XML parser.
        ops = [
            {"op": "text", "text": '"><img src=x onerror=alert(1)>', "x": 10, "y": 10, "w": 100, "h": 20,
             "size": 12, "color": "#fff"},
        ]
        xml_text = drawio_export.build_drawio(_doc(ops))[0]
        self.assertNotIn("<img", xml_text)
        root = ET.fromstring(xml_text)
        value = next(c for c in root.iter("mxCell") if c.get("vertex") == "1").get("value")
        self.assertEqual(value, '"><img src=x onerror=alert(1)>')

    def test_page_size_and_grid_follow_canvas(self):
        root = ET.fromstring(drawio_export.build_drawio(_doc([], width=800, height=600))[0])
        model = root.find(".//mxGraphModel")
        self.assertEqual(model.get("pageWidth"), "800")
        self.assertEqual(model.get("pageHeight"), "600")
        self.assertEqual(model.get("gridSize"), "4")


class PipelineTests(unittest.TestCase):
    def test_example_exports_and_passes_checks(self):
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs(spec, Path(td), "graphx", formats=("png", "drawio"))
            self.assertIn("drawio", res)
            chk = rad.check_outputs(res, spec)
            drawio_checks = [c for c in chk["checks"] if c["name"].startswith("drawio")]
            self.assertTrue(drawio_checks)
            for c in drawio_checks:
                self.assertTrue(c["ok"], f"{c['name']} failed: {c}")
            root = ET.parse(res["drawio"]).getroot()
            edges = [c for c in root.iter("mxCell") if c.get("edge") == "1"]
            self.assertTrue(any(c.get("source") for c in edges), "some edges must be bound")

    def test_export_reimports_through_drawio_import(self):
        # The loop this format exists to close: our .drawio must be legible to
        # our own importer (and therefore to draw.io itself).
        import drawio_import
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs(spec, Path(td), "graphx", formats=("drawio",))
            roundtrip, notes = drawio_import.parse_drawio(
                drawio_import.load_mxfile(res["drawio"]))
            self.assertEqual(roundtrip["layout"], "graph")
            self.assertGreaterEqual(len(roundtrip["nodes"]), 3)
            self.assertGreaterEqual(len(roundtrip["edges"]), 1)

    def test_browser_pipeline_exports_drawio(self):
        # Same output must come out of the browser path (pure-Python sidecar,
        # no Chromium needed for this format).
        spec = json.loads((EXAMPLES / "er-spec.json").read_text(encoding="utf-8"))
        if rad.svg_renderer is None or not rad.svg_renderer.is_available():
            self.skipTest("browser renderer unavailable")
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs_browser(spec, Path(td), "erx", formats=("drawio",))
            self.assertIn("drawio", res)
            root = ET.parse(res["drawio"]).getroot()
            self.assertEqual(root.tag, "mxfile")
            self.assertTrue(any(c.get("vertex") == "1" for c in root.iter("mxCell")))


if __name__ == "__main__":
    unittest.main()
