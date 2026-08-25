"""Subprocess coverage for the spec_graph and mermaid_import CLIs.

Covers the argparse/main() bodies and the five spec_graph subcommands by
running them as real child processes (traced into coverage via the
sitecustomize hook in tests/conftest.py).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "assets" / "examples" / "graph-workflow-spec.json"


def _run(script, *argv, timeout=60):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / script)] + list(argv),
        capture_output=True, text=True, timeout=timeout,
    )


class SpecGraphCliTest(unittest.TestCase):
    def test_lint(self):
        proc = _run("spec_graph.py", "lint", "--spec", str(SPEC))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertIn("layout", report)

    def test_neighbors(self):
        node = json.loads(SPEC.read_text(encoding="utf-8"))["nodes"][0]["id"]
        proc = _run("spec_graph.py", "neighbors", "--spec", str(SPEC), "--node", node)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_around_to_file(self):
        node = json.loads(SPEC.read_text(encoding="utf-8"))["nodes"][0]["id"]
        out = Path(tempfile.mkdtemp()) / "sub.json"
        proc = _run("spec_graph.py", "around", "--spec", str(SPEC), "--node", node, "--hops", "1", "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.is_file())

    def test_around_stdout(self):
        node = json.loads(SPEC.read_text(encoding="utf-8"))["nodes"][0]["id"]
        proc = _run("spec_graph.py", "around", "--spec", str(SPEC), "--node", node)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_diff(self):
        other = json.loads(SPEC.read_text(encoding="utf-8"))
        other["nodes"].append({"id": "extra", "label": "Extra"})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(other, f); p = f.name
        try:
            proc = _run("spec_graph.py", "diff", "--spec", str(SPEC), "--other", p)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_export_mermaid(self):
        proc = _run("spec_graph.py", "export", "--spec", str(SPEC), "--format", "mermaid")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("graph", proc.stdout.lower())

    def test_export_dot(self):
        proc = _run("spec_graph.py", "export", "--spec", str(SPEC), "--format", "dot")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("digraph", proc.stdout)

    def test_no_command_fails(self):
        proc = _run("spec_graph.py")
        self.assertNotEqual(proc.returncode, 0)


class MermaidImportCliTest(unittest.TestCase):
    def _write_mmd(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False, encoding="utf-8") as f:
            f.write(text); return f.name

    def test_import_flowchart_to_stdout(self):
        mmd = self._write_mmd("flowchart LR\na[A] --> b[B]\n")
        try:
            proc = _run("mermaid_import.py", mmd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("graph", proc.stdout)
        finally:
            Path(mmd).unlink(missing_ok=True)

    def test_import_sequence_to_file(self):
        mmd = self._write_mmd("sequenceDiagram\na->>b: hi\n")
        out = Path(tempfile.mkdtemp()) / "spec.json"
        try:
            proc = _run("mermaid_import.py", mmd, "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out.is_file())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["layout"], "sequence")
        finally:
            Path(mmd).unlink(missing_ok=True)

    def test_import_invalid_fails(self):
        mmd = self._write_mmd("not a mermaid diagram at all")
        try:
            proc = _run("mermaid_import.py", mmd)
            self.assertNotEqual(proc.returncode, 0)
        finally:
            Path(mmd).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
