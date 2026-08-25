"""E2E coverage for the Pillow fallback pipeline across all layouts.

The browser E2E matrix covers the browser renderer; this module drives the
Pillow pipeline in-process so the per-layout ``render_*`` painters and
``draw_*`` primitives execute and count toward coverage.
"""
import importlib.util
import json
import tempfile
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


class PillowE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_module("render_animated_diagram")

    def test_every_layout_pillow_pipeline(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                spec = json.loads((EXAMPLES / LAYOUT_SPEC[layout]).read_text(encoding="utf-8"))
                spec.setdefault("canvas", {})["frames"] = 4
                # Subtitle exercises the subtitle draw branch in every
                # layout's render_* painter (example specs omit it).
                spec.setdefault("subtitle", "Coverage subtitle")
                tmp = Path(tempfile.mkdtemp(prefix="pillow_e2e_"))
                result = self.renderer.write_outputs(spec, tmp, "t", icon_engine="pillow",
                                                     formats=("png", "gif", "excalidraw"))
                self.assertIn("png", result, f"{layout}: pillow png missing")
                self.assertIn("gif", result, f"{layout}: pillow gif missing")
                self.assertIn("excalidraw", result, f"{layout}: pillow excalidraw missing")

    def test_pillow_rich_variants(self):
        """Branch-heavy spec features through the Pillow painters: edge
        badges, loop edges, step notes, lane captions, graph groups, circle
        nodes, card bodies, and parallel BPMN gateways."""
        variants = {
            "graph": {
                "layout": "graph", "title": {"prefix": "Graph", "highlight": "Flow"}, "canvas": {"frames": 4},
                "groups": [{"id": "g1", "label": "Cluster"}],
                "nodes": [
                    {"id": "a", "label": "A", "parent": "g1"},
                    {"id": "b", "label": "B", "parent": "g1"},
                    {"id": "c", "label": "C", "kind": "circle"},
                ],
                "edges": [
                    {"from": "a", "to": "b", "label": "go", "badge": 1},
                    {"from": "b", "to": "c", "kind": "loop", "label": "retry", "badge": 2},
                    {"from": "c", "to": "a"},
                ],
            },
            "swimlane": {
                "layout": "swimlane", "title": {"prefix": "Swim", "highlight": "Lane"}, "canvas": {"frames": 4},
                "lanes": [
                    {"title": "Lane", "caption": "caption row text", "steps": [
                        {"id": "s1", "title": "S1", "note": "a long note under the step"},
                        {"id": "s2", "title": "S2"},
                    ]},
                    {"title": "Lane2", "steps": [{"id": "t1", "title": "T1"}, {"id": "t2", "title": "T2"}]},
                ],
                "connections": [{"from": "s1", "to": "t1", "label": "hand-off", "badge": 3},
                                {"from": "s2", "to": "t2", "label": "straight down"},
                                {"from": "s2", "to": "t1", "label": "diagonal hop"},
                                {"from": "s2", "to": "s1", "kind": "loop", "label": "rework"}],
            },
            "panorama": {
                "layout": "panorama", "title": {"prefix": "Pano", "highlight": "Rama"}, "canvas": {"frames": 4},
                "inputs": [{"title": "I", "icon": "file"}],
                "steps": [{"title": "S", "icon": "gear"}],
                "outputs": [{"title": "O", "icon": "chart"}],
                "left_panel": {"title": "L", "cards": [
                    {"title": "C1", "body": "has a body", "icon": "file"},
                    {"title": "C2", "icon": "gear"},
                ]},
            },
            "bpmn": {
                "layout": "bpmn", "title": {"prefix": "BPMN", "highlight": "Proc"}, "canvas": {"frames": 4},
                "elements": [
                    {"id": "s", "kind": "start", "label": "start"},
                    {"id": "g", "kind": "gateway_parallel", "label": "and"},
                    {"id": "t", "kind": "task", "label": "work"},
                    {"id": "e", "kind": "end", "label": "end"},
                ],
                "flows": [
                    {"from": "s", "to": "g"}, {"from": "g", "to": "t"}, {"from": "t", "to": "e"},
                ],
            },
            "communication": {
                "layout": "communication", "title": {"prefix": "Comm", "highlight": "Diag"}, "canvas": {"frames": 4},
                "objects": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "links": [
                    {"from": "a", "to": "b", "messages": [
                        {"num": "1", "label": "call()", "dir": "forward"},
                    ]},
                    {"from": "b", "to": "a"},
                ],
            },
            "c4": {
                "layout": "c4", "title": {"prefix": "C4", "highlight": "Model"}, "canvas": {"frames": 4},
                "boundaries": [{"id": "b1", "label": "Edge"}],
                "elements": [
                    {"id": "u", "kind": "person", "label": "User", "boundary": "b1"},
                    {"id": "s", "kind": "system", "label": "Sys", "desc": "description text"},
                ],
                "relations": [{"from": "u", "to": "s", "label": "uses"}],
            },
            "package": {
                "layout": "package", "title": {"prefix": "Pkg", "highlight": "Diag"}, "canvas": {"frames": 4},
                "packages": [
                    {"id": "p1", "label": "core", "stereotype": "framework"},
                    {"id": "p2", "label": "ui", "parent": "p1"},
                ],
                "relations": [{"from": "p2", "to": "p1", "kind": "import"}],
            },
            "composite": {
                "layout": "composite", "title": {"prefix": "Comp", "highlight": "Osite"}, "canvas": {"frames": 4},
                "parts": [{"id": "p1", "label": "P1"}, {"id": "p2", "label": "P2"}],
                "ports": [
                    {"id": "po1", "part": "p1", "side": "top", "label": "port-top"},
                    {"id": "po2", "part": "p1", "side": "bottom", "label": "port-bottom"},
                ],
                "connectors": [{"from": "p1", "to": "p2"}],
            },
        }
        for layout, spec in variants.items():
            with self.subTest(layout=layout):
                tmp = Path(tempfile.mkdtemp(prefix="pillow_var_"))
                result = self.renderer.write_outputs(spec, tmp, "t", icon_engine="pillow",
                                                     formats=("png",))
                self.assertIn("png", result, f"{layout}: pillow png missing")


if __name__ == "__main__":
    unittest.main()
