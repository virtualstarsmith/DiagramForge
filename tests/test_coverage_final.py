"""Final coverage push: prepare_fonts main() branches, graph group
containers, and mermaid_import's per-layout summary dispatch.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrepareFontsMainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pf = load_module("prepare_fonts")

    def test_main_missing_excalifont_warns_and_exits_on_missing_var(self):
        # No Excalifont-Regular.woff2 and no variable font -> warn + exit(1)
        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td)
            with patch.object(self.pf, "FONT_DIR", fake_dir), \
                 patch.object(sys, "argv", ["prepare_fonts.py"]):
                with self.assertRaises(SystemExit) as ctx:
                    self.pf.main()
                self.assertEqual(ctx.exception.code, 1)

    def test_main_missing_excalifont_uses_provided_var(self):
        # Excalifont missing + variable font provided -> must proceed past the
        # Excalifont step; TTFont is mocked so no real font IO happens.
        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td)
            var = Path(td) / "NotoSansSC-var.ttf"
            var.write_bytes(b"fake")
            fake_font = MagicMock()
            fake_font.save = lambda p: Path(p).write_bytes(b"x")
            fake_font.getBestCmap.return_value = {65: "A"}
            with patch.object(self.pf, "FONT_DIR", fake_dir), \
                 patch.object(self.pf, "TTFont", return_value=fake_font), \
                 patch.object(self.pf, "instantiateVariableFont"), \
                 patch.object(self.pf, "save_both_flavors", lambda *a, **k: None), \
                 patch.object(sys, "argv", ["prepare_fonts.py", str(var)]):
                # should complete without SystemExit
                self.pf.main()
                self.assertTrue((fake_dir / "notosanssc-coverage.json").is_file())


    def test_save_both_flavors(self):
        # Direct test of save_both_flavors with the bundled Excalifont.
        from fontTools.ttLib import TTFont
        src = ROOT / "assets" / "fonts" / "Excalifont-Regular.ttf"
        if not src.is_file():
            self.skipTest("Excalifont-Regular.ttf missing")
        font = TTFont(str(src))
        with tempfile.TemporaryDirectory() as td:
            with patch.object(self.pf, "FONT_DIR", Path(td)):
                self.pf.save_both_flavors(font, "test_font")
            self.assertTrue((Path(td) / "test_font.ttf").is_file())
            self.assertTrue((Path(td) / "test_font.woff2").is_file())


class GraphGroupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = load_module("graph_model")

    def test_groups_render_container_boxes(self):
        spec = {
            "layout": "graph", "layout_engine": "legacy",
            "groups": [
                {"id": "backend", "label": "Backend"},
                {"id": "empty", "label": "Empty"},  # no members -> skipped
                "not-a-dict",  # invalid -> skipped
            ],
            "nodes": [
                {"id": "a", "label": "A", "parent": "backend"},
                {"id": "b", "label": "B", "parent": "backend"},
                {"id": "c", "label": "C"},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }
        plan = self.gm.plan_graph(spec)
        groups = plan["graph_groups"]
        # only the group with members survives
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["id"], "backend")
        x, y, w, h = groups[0]["box"]
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


class MermaidSummaryTest(unittest.TestCase):
    """The per-layout summary branch in mermaid_import.main()."""

    def _run(self, script, *argv):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / script)] + list(argv),
            capture_output=True, text=True, timeout=60,
        )

    def _import(self, mmd_text):
        with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False, encoding="utf-8") as f:
            f.write(mmd_text); p = f.name
        out = Path(tempfile.mkdtemp()) / "spec.json"
        try:
            proc = self._run("mermaid_import.py", p, "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_summary_graph(self):
        r = self._import("flowchart LR\na[A] --> b[B]\n")
        self.assertIn("nodes", r)

    def test_summary_sequence(self):
        r = self._import("sequenceDiagram\na->>b: hi\n")
        self.assertIn("participants", r)

    def test_summary_er(self):
        r = self._import("erDiagram\nUSER ||--o{ ORDER : places\n")
        self.assertIn("entities", r)

    def test_summary_class(self):
        r = self._import("classDiagram\nclass A\nA --> B\n")
        self.assertIn("classes", r)

    def test_summary_state(self):
        r = self._import("stateDiagram-v2\n[*] --> s1\ns1 --> [*]\n")
        self.assertIn("states", r)

    def test_summary_gantt(self):
        r = self._import("gantt\ntitle T\ndateFormat YYYY-MM-DD\nsection S\nt1: 2024-01-01, 3d\n")
        self.assertIn("sections", r)

    def test_summary_mindmap(self):
        r = self._import("mindmap\nroot((AI))\n  Data\n  Model\n")
        self.assertIn("topics", r)

    def test_summary_timeline(self):
        r = self._import("timeline\ntitle T\n2020 : Event\n")
        self.assertIn("events", r)

    def test_summary_c4(self):
        r = self._import("C4Context\ntitle T\nPerson(u, User)\nSystem(s, Sys)\nRel(u, s, uses)\n")
        self.assertIn("elements", r)


if __name__ == "__main__":
    unittest.main()
