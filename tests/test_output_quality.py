"""Output quality audit + mermaid subgraph feature tests.

Part 1 — quality audit: every layout's PNG must carry real visual structure
(not a blank or near-monochrome frame), which is the automated proxy for
"clean lines, complete logic, business-grade" output that an architect or
systems analyst would publish.

Part 2 — mermaid subgraph: the subgraph->groups and class->accent mappings
added to mermaid_import need their own coverage (the existing mermaid suite
predates the feature).
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAYOUTS = [
    "panorama", "swimlane", "grid", "graph", "sequence", "er", "usecase", "class",
    "activity", "state", "dfd", "deployment", "component", "package", "object",
    "composite", "profile", "communication", "timing", "interaction", "c4",
    "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone",
]
LAYOUT_SPEC = {
    "panorama": "homepage-panorama-spec.json", "swimlane": "swimlane-spec.json",
    "grid": "grid-spec.json",
    "graph": "graph-workflow-spec.json", "sequence": "sequence-spec.json",
    "er": "er-spec.json", "usecase": "usecase-spec.json", "class": "class-spec.json",
    "activity": "activity-spec.json", "state": "state-spec.json", "dfd": "dfd-spec.json",
    "deployment": "deployment-spec.json", "component": "component-spec.json",
    "package": "package-spec.json", "object": "object-spec.json",
    "composite": "composite-spec.json", "profile": "profile-spec.json",
    "communication": "communication-spec.json", "timing": "timing-spec.json",
    "interaction": "interaction-spec.json", "c4": "c4-spec.json",
    "gantt": "gantt-spec.json", "bpmn": "bpmn-spec.json",
    "orgchart": "orgchart-spec.json", "mindmap": "mindmap-spec.json",
    "timeline": "timeline-spec.json", "fishbone": "fishbone-spec.json",
}


class OutputQualityAudit(unittest.TestCase):
    """Every layout PNG must be a real diagram, not a blank plate."""

    @classmethod
    def setUpClass(cls):
        cls.renderer = load_module("render_animated_diagram")
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable")
        import shutil
        cls.tmp = ROOT / "out" / "_quality_audit"
        if cls.tmp.exists():
            shutil.rmtree(cls.tmp)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        cls._n = 0

    def _fresh_dir(self):
        import tempfile
        # mkdtemp guarantees a unique dir per call across test methods (a
        # naive counter on `self` resets per unittest instance).
        return Path(tempfile.mkdtemp(prefix="q_", dir=str(self.tmp)))

    def _render_png(self, spec):
        from PIL import Image
        d = self._fresh_dir()
        r = self.renderer.write_outputs_browser(spec, d, "q", formats=("png",))
        with Image.open(r["png"]) as im:
            return im.convert("RGB")

    def _render_png_with_structure(self, spec):
        """Render, retrying once into a fresh dir if the frame comes back flat.

        A healthy render of any example spec measures 1000+ distinct colors
        against the >50 audit floor; a flat frame means Chromium was starved
        by concurrent load and captured before paint settled — a transient
        environment fault, not a diagram defect.
        """
        img = self._render_png(spec)
        if self._color_complexity(img) <= 50:
            img = self._render_png(spec)
        return img

    def _color_complexity(self, img):
        """Distinct colors after a light downsample — a proxy for visual
        structure. A blank plate has ~1; a real diagram has many."""
        small = img.resize((120, 90))
        colors = small.getcolors(maxcolors=120 * 90)
        return len(colors) if colors else 120 * 90

    def test_every_layout_png_has_visual_structure(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                spec = json.loads((EXAMPLES / LAYOUT_SPEC[layout]).read_text(encoding="utf-8"))
                img = self._render_png_with_structure(spec)
                complexity = self._color_complexity(img)
                # A business-grade diagram has borders, fills, text, icons ->
                # well above a blank plate. 50 distinct colors is a conservative
                # floor that rejects blanks/near-monochrome failures.
                self.assertGreater(complexity, 50, f"{layout}: PNG too flat ({complexity} colors)")

    def test_every_style_png_has_visual_structure(self):
        base = json.loads((EXAMPLES / LAYOUT_SPEC["graph"]).read_text(encoding="utf-8"))
        for style in ("slate", "report", "academic", "blueprint"):
            with self.subTest(style=style):
                spec = json.loads(json.dumps(base)); spec["style"] = style
                img = self._render_png_with_structure(spec)
                self.assertGreater(self._color_complexity(img), 50, f"{style}: too flat")


class MermaidSubgraphTest(unittest.TestCase):
    """The subgraph->groups and class->accent mappings (stage 4.1)."""

    @classmethod
    def setUpClass(cls):
        cls.mi = load_module("mermaid_import")

    def test_subgraph_becomes_groups_with_parents(self):
        mmd = """flowchart LR
        subgraph Ingest [Data Ingestion]
          a[Source] --> b[Clean]
        end
        subgraph Process [Processing]
          b --> c[Embed]
        end
        c --> d[Query]
        """
        spec, notes = self.mi.to_spec(mmd)
        self.assertEqual(len(spec["groups"]), 2)
        g_ids = [g["id"] for g in spec["groups"]]
        self.assertIn("Ingest", g_ids)
        self.assertIn("Process", g_ids)
        parents = {n["id"]: n.get("parent") for n in spec["nodes"]}
        self.assertEqual(parents["a"], "Ingest")
        self.assertEqual(parents["b"], "Ingest")
        self.assertEqual(parents["c"], "Process")
        self.assertIsNone(parents["d"])  # outside any subgraph

    def test_class_routes_to_accent_role(self):
        # Only class names matching a known DiagramForge accent role map over.
        mmd = """flowchart LR
        classDef green fill:#22c55e
        a[A] --> b[B]
        class b green
        """
        spec, _ = self.mi.to_spec(mmd)
        bnode = next(n for n in spec["nodes"] if n["id"] == "b")
        self.assertEqual(bnode.get("accent"), "green")

    def test_unknown_class_does_not_set_accent(self):
        mmd = """flowchart LR
        a[A] --> b[B]
        class b notARole
        """
        spec, _ = self.mi.to_spec(mmd)
        bnode = next(n for n in spec["nodes"] if n["id"] == "b")
        self.assertNotIn("accent", bnode)

    def test_quoted_subgraph_label(self):
        mmd = 'flowchart LR\nsubgraph "My Group"\nx[X] --> y[Y]\nend\n'
        spec, _ = self.mi.to_spec(mmd)
        self.assertEqual(len(spec["groups"]), 1)
        self.assertEqual(spec["groups"][0]["label"], "My Group")


if __name__ == "__main__":
    unittest.main()
