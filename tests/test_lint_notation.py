"""tests for scripts/lint_notation.py — the UML-semantics layer."""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import lint_notation

EXAMPLES = REPO / "assets" / "examples"


def _kinds(spec):
    return [(i["severity"], i["kind"]) for i in lint_notation.lint(spec)["issues"]]


class ClassTests(unittest.TestCase):
    def test_inheritance_cycle_is_an_error(self):
        spec = {"layout": "class",
                "classes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "relations": [
                    {"from": "a", "to": "b", "kind": "inheritance"},
                    {"from": "b", "to": "c", "kind": "inheritance"},
                    {"from": "c", "to": "b", "kind": "inheritance"},
                ]}
        issues = lint_notation.lint(spec)["issues"]
        self.assertIn(("error", "inheritance-cycle"), _kinds(spec))
        cycle = next(i for i in issues if i["kind"] == "inheritance-cycle")
        # the reported path depends on DFS entry order; both cycle members must appear
        self.assertIn("->", cycle["message"])
        self.assertIn("b", cycle["message"])
        self.assertIn("c", cycle["message"])

    def test_diamond_inheritance_is_fine(self):
        spec = {"layout": "class",
                "classes": [{"id": "base"}, {"id": "l"}, {"id": "r"}, {"id": "child"}],
                "relations": [
                    {"from": "l", "to": "base", "kind": "inheritance"},
                    {"from": "r", "to": "base", "kind": "inheritance"},
                    {"from": "child", "to": "l", "kind": "inheritance"},
                    {"from": "child", "to": "r", "kind": "inheritance"},
                ]}
        self.assertEqual([], _kinds(spec))


class StateTests(unittest.TestCase):
    def test_missing_initial_warns(self):
        spec = {"layout": "state", "states": [{"id": "a"}, {"id": "b"}],
                "transitions": [{"from": "a", "to": "b"}]}
        self.assertIn(("warning", "no-initial"), _kinds(spec))

    def test_unreachable_state_warns(self):
        spec = {"layout": "state",
                "states": [{"id": "s", "kind": "initial"}, {"id": "a"}, {"id": "far"}],
                "transitions": [{"from": "s", "to": "a"}]}
        issues = lint_notation.lint(spec)["issues"]
        self.assertIn(("warning", "unreachable-state"), _kinds(spec))
        self.assertIn("far", next(i for i in issues if i["kind"] == "unreachable-state")["message"])

    def test_clean_machine_passes(self):
        spec = {"layout": "state",
                "states": [{"id": "s", "kind": "initial"}, {"id": "a"}, {"id": "end", "kind": "final"}],
                "transitions": [{"from": "s", "to": "a"}, {"from": "a", "to": "end"}]}
        self.assertEqual([], _kinds(spec))


class SequenceTests(unittest.TestCase):
    def test_unknown_participant_is_error(self):
        spec = {"layout": "sequence", "participants": [{"id": "a"}],
                "messages": [{"from": "a", "to": "ghost", "kind": "sync"}]}
        self.assertIn(("error", "unknown-participant"), _kinds(spec))

    def test_return_from_never_activated_warns(self):
        spec = {"layout": "sequence", "participants": [{"id": "a"}, {"id": "b"}],
                "messages": [{"from": "a", "to": "b", "kind": "sync"},
                             {"from": "b", "to": "a", "kind": "return"},
                             {"from": "a", "to": "a", "kind": "return"}]}
        self.assertIn(("warning", "return-without-activation"), _kinds(spec))

    def test_retry_loop_with_multiple_returns_is_clean(self):
        # One sync in, several returns out (retries) — legal, no false alarm.
        spec = {"layout": "sequence", "participants": [{"id": "a"}, {"id": "b"}],
                "messages": [{"from": "a", "to": "b", "kind": "sync"},
                             {"from": "b", "to": "a", "kind": "return"},
                             {"from": "b", "to": "a", "kind": "return"}]}
        self.assertEqual([], _kinds(spec))

    def test_dangling_activation_warns(self):
        spec = {"layout": "sequence", "participants": [{"id": "a"}, {"id": "b"}],
                "messages": [{"from": "a", "to": "b", "kind": "sync", "label": "fire and forget"}]}
        self.assertIn(("warning", "unbalanced-activation"), _kinds(spec))

    def test_activate_false_silences_the_check(self):
        spec = {"layout": "sequence", "participants": [{"id": "a"}, {"id": "b"}],
                "messages": [{"from": "a", "to": "b", "kind": "sync", "activate": False}]}
        self.assertEqual([], _kinds(spec))


class ErAndDfdTests(unittest.TestCase):
    def test_unknown_entity_is_error(self):
        spec = {"layout": "er", "entities": [{"id": "user"}],
                "relations": [{"from": "user", "to": "ghost", "cardinality": "1:N"}]}
        self.assertIn(("error", "unknown-entity"), _kinds(spec))

    def test_flowless_process_warns(self):
        spec = {"layout": "dfd",
                "nodes": [{"id": "ext", "kind": "external"}, {"id": "p", "kind": "process"}],
                "flows": [{"from": "ext", "to": "p"}]}
        # both connected: clean
        self.assertEqual([], _kinds(spec))
        spec["nodes"].append({"id": "lonely", "kind": "process"})
        self.assertIn(("warning", "flowless-process"), _kinds(spec))


class ActivityTests(unittest.TestCase):
    def test_unreachable_and_missing_final(self):
        spec = {"layout": "activity",
                "nodes": [{"id": "s", "kind": "initial"}, {"id": "a"}, {"id": "done", "kind": "final"}],
                "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "done"}]}
        self.assertEqual([], _kinds(spec))
        spec["nodes"].append({"id": "orphan"})
        kinds = _kinds(spec)
        self.assertIn(("warning", "unreachable-node"), kinds)
        self.assertNotIn(("warning", "no-final"), kinds)


class ShippedExamplesTest(unittest.TestCase):
    def test_every_typed_example_lints_clean(self):
        for name in ("state-spec", "class-spec", "sequence-spec", "er-spec",
                     "activity-spec", "dfd-spec"):
            spec = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
            report = lint_notation.lint(spec)
            self.assertEqual([], report["issues"], f"{name}: {report['issues']}")

    def test_flowchart_family_layouts_are_out_of_scope(self):
        spec = json.loads((EXAMPLES / "graph-workflow-spec.json").read_text(encoding="utf-8"))
        report = lint_notation.lint(spec)
        self.assertEqual("graph", report["layout"])
        self.assertEqual([], report["issues"])


if __name__ == "__main__":
    unittest.main()
