"""Import dial tests: the degrade ladder, audience wording, fidelity ledger,
and their wiring into mermaid_import (dials shared with drawio_import)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mermaid_import.py"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import_refine = load_module("import_refine")
mermaid_import = load_module("mermaid_import")


def chain_mermaid(count):
    lines = ["flowchart LR"]
    lines += [f"n{i}[Step {i}]-->n{i+1}[Step {i+1}]" for i in range(count - 1)]
    return "\n".join(lines)


class AudienceDialTest(unittest.TestCase):
    def test_engineer_keeps_everything(self):
        new, changed = import_refine._reword_label("Auth Service JWT :8443", "engineer")
        self.assertFalse(changed)

    def test_mixed_strips_ports_and_schemes(self):
        new, changed = import_refine._reword_label("https://api.example.com:8443", "mixed")
        self.assertEqual("api.example.com", new)

    def test_executive_strips_jargon_and_caps_words(self):
        new, changed = import_refine._reword_label("Auth Service verify JWT RS256 token", "executive")
        self.assertNotIn("JWT", new)
        self.assertLessEqual(len(new.split()), 3)

    def test_executive_caps_cjk_by_chars(self):
        new, changed = import_refine._reword_label("用户身份认证授权中心服务模块", "executive")
        self.assertLessEqual(len(new), 12)


class DetailLadderTest(unittest.TestCase):
    def graph(self, n_nodes):
        nodes = [{"id": f"n{i}", "label": f"Step {i}"} for i in range(n_nodes)]
        edges = [{"from": f"n{i}", "to": f"n{i+1}", "label": ""} for i in range(n_nodes - 1)]
        return {"layout": "graph", "nodes": nodes, "edges": edges}

    def run_dial(self, spec, detail):
        return import_refine.apply_dials(spec, detail=detail, audience="engineer")

    def test_faithful_drops_orphans_but_keeps_everything_else(self):
        spec = self.graph(20)
        spec["nodes"].append({"id": "loose", "label": "sticky note"})
        spec, ledger = self.run_dial(spec, "faithful")
        self.assertEqual(20, len(spec["nodes"]))
        self.assertTrue(any("sticky note" in d for d in ledger["dropped"]))

    def test_balanced_collapses_chains_to_budget(self):
        spec, ledger = self.run_dial(self.graph(20), "balanced")
        self.assertEqual(12, len(spec["nodes"]))
        self.assertEqual(8, len(ledger["collapsed"]))
        # Collapsed middle labels survive as edge labels.
        labels = json.dumps(spec, ensure_ascii=False)
        self.assertIn("Step", labels)

    def test_simplified_goes_further(self):
        spec, ledger = self.run_dial(self.graph(20), "simplified")
        self.assertEqual(7, len(spec["nodes"]))

    def test_duplicate_labels_merge(self):
        # Over the budget by one; the duplicate merge alone must resolve it.
        spec = self.graph(12)
        spec["nodes"].append({"id": "dup", "label": "step 5"})
        spec["edges"].append({"from": "dup", "to": "n0", "label": ""})
        spec, ledger = self.run_dial(spec, "balanced")
        self.assertEqual(12, len(spec["nodes"]))
        self.assertEqual(1, len(ledger["merged"]))
        self.assertEqual([], ledger["collapsed"])

    def test_infra_leaves_drop_last(self):
        # A star of plain leaves cannot collapse; the one infra leaf goes.
        nodes = [{"id": "hub", "label": "Hub"}]
        nodes += [{"id": f"s{i}", "label": f"Satellite {i}"} for i in range(11)]
        nodes.append({"id": "db", "label": "Postgres"})
        edges = [{"from": "hub", "to": f"s{i}", "label": ""} for i in range(11)]
        edges.append({"from": "hub", "to": "db", "label": ""})
        spec, ledger = self.run_dial({"layout": "graph", "nodes": nodes, "edges": edges}, "balanced")
        self.assertLessEqual(len(spec["nodes"]), 12)
        self.assertTrue(any("Postgres" in d for d in ledger["dropped"]))

    def test_over_budget_flag_when_nothing_left_to_cut(self):
        # A star of distinct labels with >1 connections each can't collapse.
        nodes = [{"id": "hub", "label": "Hub"}] + [{"id": f"s{i}", "label": f"Satellite {i}"} for i in range(15)]
        edges = []
        for i in range(15):
            edges.append({"from": "hub", "to": f"s{i}", "label": ""})
            edges.append({"from": f"s{i}", "to": "hub", "label": f"back {i}"})
        spec, ledger = self.run_dial({"layout": "graph", "nodes": nodes, "edges": edges}, "simplified")
        self.assertTrue(ledger["over_budget"])


class MermaidDialsIntegrationTest(unittest.TestCase):
    def test_to_spec_detail_and_audience(self):
        spec, notes = mermaid_import.to_spec(chain_mermaid(20), detail="balanced", audience="executive")
        self.assertLessEqual(len(spec["nodes"]), 12)
        self.assertTrue(any(n.startswith("Detail: balanced") for n in notes))
        self.assertTrue(any(n.startswith("Collapsed:") for n in notes))

    def test_defaults_are_backward_compatible(self):
        spec, notes = mermaid_import.to_spec(chain_mermaid(20))
        self.assertEqual(20, len(spec["nodes"]))
        self.assertFalse(any(n.startswith("Detail:") for n in notes))

    def test_cli_size_sets_canvas_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "c.mmd"
            src.write_text(chain_mermaid(4), encoding="utf-8")
            out = Path(tmp) / "spec.json"
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), str(src), "--out", str(out), "--size", "square"],
                capture_output=True, text=True,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            spec = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual("square", spec["canvas"]["preset"])


if __name__ == "__main__":
    unittest.main()
