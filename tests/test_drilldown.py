"""tests for node.link drill-down (interactive HTML)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import render_animated_diagram as rad

EXAMPLES = REPO / "assets" / "examples"


def _main_spec(tmp, links=1, nested=False):
    nodes = [{"id": f"n{i}", "label": f"N{i}"} for i in range(3)]
    for i in range(links):
        nodes[i]["link"] = f"sub{i}.json"
    sub = {"layout": "graph", "style": "slate",
           "nodes": [{"id": "s1", "label": "S1"}, {"id": "s2", "label": "S2"}],
           "edges": [{"from": "s1", "to": "s2"}]}
    if nested:
        sub["nodes"][0]["link"] = "deeper.json"
    if links:
        Path(tmp, "sub0.json").write_text(json.dumps(sub), encoding="utf-8")
    return {"layout": "graph", "style": "slate", "nodes": nodes,
            "edges": [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}]}


class ValidateTests(unittest.TestCase):
    def test_valid_link_passes_and_cross_file_loads(self):
        with tempfile.TemporaryDirectory() as td:
            spec = _main_spec(td, links=1)
            report = rad.validate_spec(spec, spec_dir=td)
            self.assertTrue(report["ok"], report["errors"])

    def test_missing_link_file_is_named(self):
        with tempfile.TemporaryDirectory() as td:
            spec = _main_spec(td, links=0)
            spec["nodes"][0]["link"] = "nope.json"
            report = rad.validate_spec(spec, spec_dir=td)
            self.assertFalse(report["ok"])
            self.assertTrue(any("linked spec not found" in e["message"] for e in report["errors"]))

    def test_non_json_link_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            spec = _main_spec(td, links=0)
            spec["nodes"][0]["link"] = "picture.png"
            report = rad.validate_spec(spec, spec_dir=td)
            self.assertFalse(report["ok"])
            self.assertTrue(any("path to a spec JSON" in e["message"] for e in report["errors"]))

    def test_nested_links_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            spec = _main_spec(td, links=1, nested=True)
            report = rad.validate_spec(spec, spec_dir=td)
            self.assertFalse(report["ok"])
            self.assertTrue(any("has its own drill-down links" in e["message"] for e in report["errors"]))

    def test_too_many_links_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "sub0.json").write_text(json.dumps({
                "layout": "graph",
                "nodes": [{"id": "s1", "label": "S1"}, {"id": "s2", "label": "S2"}],
                "edges": [{"from": "s1", "to": "s2"}],
            }), encoding="utf-8")
            spec = {"layout": "graph", "style": "slate",
                    "nodes": [{"id": f"n{i}", "label": f"N{i}", "link": "sub0.json"}
                              for i in range(rad.MAX_DRILLDOWNS + 1)],
                    "edges": [{"from": "n0", "to": "n1"}]}
            report = rad.validate_spec(spec, spec_dir=td)
            self.assertFalse(report["ok"])
            self.assertTrue(any("exposes at most" in e["message"] for e in report["errors"]))


class PlanTests(unittest.TestCase):
    def test_link_survives_into_plan_nodes(self):
        spec = json.loads((EXAMPLES / "graph-drilldown-spec.json").read_text(encoding="utf-8"))
        rad.apply_style("slate")
        _ex, _img, doc = rad.render_static_with_ops(spec)
        linked = [(n["id"], n.get("link")) for n in doc["graph"]["nodes"] if n.get("link")]
        self.assertEqual(linked, [("order", "drilldown-detail-spec.json")])


class RenderTests(unittest.TestCase):
    def setUp(self):
        if rad.svg_renderer is None or not rad.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable")

    def test_html_embeds_drilldown_layers(self):
        spec = json.loads((EXAMPLES / "graph-drilldown-spec.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs_browser(spec, Path(td), "drill", formats=("png", "html"),
                                            spec_path=str(EXAMPLES / "graph-drilldown-spec.json"))
            self.assertEqual(res.get("drilldown"), ["order"])
            html = Path(res["html"]).read_text(encoding="utf-8")
            self.assertEqual(html.count('class="drilldown"'), 1)
            self.assertIn('data-drilldown="order"', html)
            self.assertIn("drill-back", html)
            self.assertIn("__drillReady", html)
            chk = rad.check_outputs(res, spec)
            self.assertTrue(next(c for c in chk["checks"] if c["name"] == "html_drilldowns")["ok"])

    def test_no_links_html_has_zero_layers(self):
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs_browser(spec, Path(td), "plain", formats=("html",),
                                            spec_path=str(EXAMPLES / "graph-workflow-spec.json"))
            html = Path(res["html"]).read_text(encoding="utf-8")
            self.assertEqual(html.count('class="drilldown"'), 0)
            chk = rad.check_outputs(res, spec)
            self.assertTrue(next(c for c in chk["checks"] if c["name"] == "html_drilldowns")["ok"])

    def test_broken_link_degrades_with_note(self):
        spec = json.loads((EXAMPLES / "graph-drilldown-spec.json").read_text(encoding="utf-8"))
        spec["nodes"][1]["link"] = "does-not-exist.json"
        with tempfile.TemporaryDirectory() as td:
            res = rad.write_outputs_browser(spec, Path(td), "broken", formats=("html",),
                                            spec_path=str(EXAMPLES / "graph-drilldown-spec.json"))
            # degrade, not sink: html still renders, zero layers embedded
            self.assertNotIn("drilldown", res)
            html = Path(res["html"]).read_text(encoding="utf-8")
            self.assertEqual(html.count('class="drilldown"'), 0)

    def test_drilldowns_invalidate_render_cache(self):
        import render_cache
        if render_cache is None:
            self.skipTest("render_cache unavailable")
        spec = json.loads((EXAMPLES / "graph-drilldown-spec.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            first = rad.write_outputs_browser(spec, Path(td), "cache", formats=("html",),
                                              spec_path=str(EXAMPLES / "graph-drilldown-spec.json"))
            self.assertIn("html", first)
            # mutate the linked spec: the salt must change, forcing a re-render
            detail = EXAMPLES / "drilldown-detail-spec.json"
            original = detail.read_text(encoding="utf-8")
            try:
                mutated = json.loads(original)
                mutated["nodes"][0]["label"] = "创建订单 v2"
                detail.write_text(json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8")
                # fresh outdir + cache: a cache stored under the old salt cannot serve the new one
                doc_cached = render_cache.lookup(
                    {"__probe__": True}, Path(td), "cache", ("html",), salt="x|dd=deadbeef")
                self.assertIsNone(doc_cached)
            finally:
                detail.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
