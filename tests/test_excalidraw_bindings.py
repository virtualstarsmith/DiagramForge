"""tests for Excalidraw arrow bindings — dragging a node must keep connectors."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import render_animated_diagram as rad

EXAMPLES = REPO / "assets" / "examples"


class BindingTests(unittest.TestCase):
    def _export(self, spec_name, basename):
        spec = json.loads((EXAMPLES / spec_name).read_text(encoding="utf-8"))
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        res = rad.write_outputs(spec, Path(td.name), basename, formats=("excalidraw",))
        return json.loads(Path(res["excalidraw"]).read_text(encoding="utf-8")), res

    def test_graph_arrows_bind_to_nodes(self):
        data, res = self._export("graph-workflow-spec.json", "g")
        elements = data["elements"]
        ids = {el["id"] for el in elements}
        arrows = [el for el in elements if el["type"] == "arrow"]
        self.assertTrue(arrows, "graph must export arrows")
        bound = [a for a in arrows if a["startBinding"] or a["endBinding"]]
        self.assertTrue(bound, "at least one arrow must be bound to a shape")
        for arrow in arrows:
            for key in ("startBinding", "endBinding"):
                binding = arrow.get(key)
                if binding:
                    self.assertIn(binding["elementId"], ids)
                    self.assertIn("focus", binding)
                    self.assertIn("gap", binding)
        # bound shapes list the arrows that attach to them
        for el in elements:
            for be in el.get("boundElements") or []:
                self.assertIn(be["id"], ids)
                self.assertEqual(be["type"], "arrow")
        chk = rad.check_outputs(res, self._spec("graph-workflow-spec.json"))
        self.assertTrue(next(c for c in chk["checks"] if c["name"] == "excalidraw_bindings_resolve")["ok"])

    def _spec(self, name):
        return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))

    def test_dashed_loop_channels_bind_and_masks_never_bind(self):
        data, _res = self._export("graph-workflow-spec.json", "m")
        bg = data["appState"]["viewBackgroundColor"]
        for el in data["elements"]:
            if el["type"] == "arrow":
                for key in ("startBinding", "endBinding"):
                    b = el.get(key)
                    if b:
                        target = next(x for x in data["elements"] if x["id"] == b["elementId"])
                        fill = target.get("backgroundColor")
                        self.assertIsNotNone(fill)
                        self.assertNotEqual(fill, "transparent")
                        self.assertNotEqual(fill, bg)

    def test_floating_arrow_stays_floating(self):
        # An endpoint in empty space must not fabricate a binding.
        rad.apply_style("slate")
        ex = rad.Excal(400, 300)
        _draw = None  # bindings are computed purely from Excal elements
        ex.rect(40, 40, 80, 40, "#ffffff", "#223344", 2)
        ex.line([[200, 200], [300, 260]], "#ffffff", 2, "solid", arrow="open")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.excalidraw"
            ex.write(path)
            data = json.loads(path.read_text(encoding="utf-8"))
        arrow = next(el for el in data["elements"] if el["type"] == "arrow")
        self.assertIsNone(arrow["startBinding"])
        self.assertIsNone(arrow["endBinding"])

    def test_bindings_are_deterministic(self):
        rad.apply_style("slate")
        outs = []
        for _ in range(2):
            ex = rad.Excal(400, 300)
            ex.rect(40, 40, 80, 40, "#ffffff", "#223344", 2)
            ex.rect(240, 40, 80, 40, "#ffffff", "#223344", 2)
            ex.line([[120, 60], [240, 60]], "#ffffff", 2, "solid", arrow="open")
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "x.excalidraw"
                ex.write(path)
                data = json.loads(path.read_text(encoding="utf-8"))
            arrow = next(el for el in data["elements"] if el["type"] == "arrow")
            outs.append((arrow["startBinding"]["elementId"], arrow["endBinding"]["elementId"]))
        self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
