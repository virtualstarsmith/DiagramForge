"""Accessible SVG contract tests.

Every exported diagram SVG must be an accessible figure: role="img", an
aria-labelledby that resolves to this diagram's prefixed <title>/<desc>, and
<title> as the first child. The interactive HTML embeds the same SVG, so the
contract holds there too.
"""
import importlib.util
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


svg_renderer = load_module("svg_renderer")

NS = "{http://www.w3.org/2000/svg}"


class A11yMetaTest(unittest.TestCase):
    def test_slug_sanitizes(self):
        self.assertEqual("my-diagram-v2", svg_renderer._a11y_slug("My Diagram v2"))
        self.assertEqual("diagram", svg_renderer._a11y_slug("!!!"))

    def test_title_from_spec_prefix_highlight(self):
        doc = {"title": {"prefix": "RAG", "highlight": "架构", "subtitle": "总览"}, "graph": {"nodes": [1, 2], "edges": [1]}}
        meta = svg_renderer._a11y_meta(doc, "x")
        self.assertEqual("RAG 架构", meta["title"])
        self.assertIn("总览", meta["desc"])
        self.assertIn("2 elements, 1 connections.", meta["desc"])

    def test_title_falls_back_to_basename(self):
        meta = svg_renderer._a11y_meta({"graph": {}}, "fallback-name")
        self.assertEqual("fallback-name", meta["title"])
        self.assertEqual("fallback-name", meta["slug"])


def assert_svg_accessible(test_case, svg_text):
    root = ET.fromstring(svg_text)
    test_case.assertEqual("img", root.attrib.get("role"))
    refs = root.attrib.get("aria-labelledby", "").split()
    test_case.assertEqual(2, len(refs), "aria-labelledby must name title and desc")
    # First child is the title, and every reference resolves to an element id.
    test_case.assertEqual(f"{NS}title", root[0].tag)
    by_id = {el.attrib.get("id"): el for el in root.iter() if el.attrib.get("id")}
    for ref in refs:
        test_case.assertIn(ref, by_id, f"aria-labelledby reference {ref!r} unresolved")
    title_el = by_id[refs[0]]
    desc_el = by_id[refs[1]]
    test_case.assertTrue((title_el.text or "").strip(), "<title> must be filled in")
    test_case.assertTrue((desc_el.text or "").strip(), "<desc> must be filled in")
    # Prefixed IDs, never bare title/desc — two inlined SVGs must not collide.
    for ref in refs:
        test_case.assertRegex(ref, r"^[a-z0-9-]+-(title|desc)$")


class RenderedA11yTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; needs Chromium")
        cls.renderer = load_module("render_animated_diagram")
        cls.spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))

    def _render(self, **spec_overrides):
        import tempfile

        spec = dict(self.spec, **spec_overrides)
        tmp = tempfile.TemporaryDirectory(dir=ROOT / "out")
        self.addCleanup(tmp.cleanup)
        result = self.renderer.write_outputs_browser(spec, Path(tmp.name), "a11y-demo", formats=("svg", "html"))
        return result

    def test_svg_contract(self):
        result = self._render()
        svg_text = Path(result["svg"]).read_text(encoding="utf-8")
        assert_svg_accessible(self, svg_text)

    def test_svg_contract_with_text_outlines(self):
        result = self._render(text_outlines=True)
        svg_text = Path(result["svg"]).read_text(encoding="utf-8")
        assert_svg_accessible(self, svg_text)

    def test_interactive_html_embeds_accessible_svg(self):
        result = self._render()
        html_text = Path(result["html"]).read_text(encoding="utf-8")
        self.assertIn('role="img"', html_text)
        match = re.search(r'aria-labelledby="([^"]+)"', html_text)
        self.assertTrue(match, "interactive HTML svg must carry aria-labelledby")
        for ref in match.group(1).split():
            self.assertIn(f'id="{ref}"', html_text)

    def test_check_outputs_enforces_contract(self):
        result = self._render()
        checks = self.renderer.check_outputs(result, self.spec)
        by_name = {check["name"]: check["ok"] for check in checks["checks"]}
        self.assertTrue(by_name["svg_role_img"])
        self.assertTrue(by_name["svg_accessible_name_resolves"])
        self.assertTrue(by_name["svg_title_first_child"])


if __name__ == "__main__":
    unittest.main()
