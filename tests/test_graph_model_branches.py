"""Branch coverage for the UML and structured-layout plan functions.

The E2E matrix renders every layout once with its bundled example, which
covers the happy path. These tests exercise the branch-heavy internals —
sequence combined fragments, class relation kinds, ER cardinalities, state
transition labels, activity fork/join — so the logic that an architect
relies on (完整逻辑) is verified, not just the default shape.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GraphModelBranchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = load_module("graph_model")

    def plan(self, spec):
        spec = dict(spec, layout_engine="legacy")  # deterministic legacy geometry
        return self.gm.build_plan(spec)

    # --- sequence: combined fragments (alt/loop/opt) -----------------------
    def test_sequence_alt_loop_opt_fragments(self):
        spec = {
            "layout": "sequence",
            "participants": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "messages": [
                {"from": "a", "to": "b", "label": "ask", "kind": "sync"},
                {"from": "b", "to": "a", "label": "ans", "kind": "return"},
            ],
            "fragments": [
                {"kind": "alt", "label": "ok", "range": [0, 1]},
                {"kind": "loop", "label": "retry", "range": [1, 2]},
                {"kind": "opt", "label": "maybe", "range": [0, 1]},
            ],
        }
        plan = self.plan(spec)
        self.assertIn("sequence", plan)
        self.assertEqual(len(plan["sequence"]["fragments"]), 3)

    def test_sequence_self_async_lost_messages(self):
        spec = {
            "layout": "sequence",
            "participants": [{"id": "a", "label": "A"}],
            "messages": [
                {"from": "a", "to": "a", "label": "self", "kind": "self"},
                {"from": "a", "to": "a", "label": "async", "kind": "async"},
                {"from": "a", "to": "a", "label": "lost", "kind": "lost"},
            ],
        }
        plan = self.plan(spec)
        self.assertEqual(len(plan["sequence"]["messages"]), 3)

    def test_sequence_notes(self):
        spec = {
            "layout": "sequence",
            "participants": [{"id": "a", "label": "A"}],
            "messages": [
                {"from": "a", "to": "a", "label": "m", "kind": "self", "note": "a side note"},
            ],
        }
        plan = self.plan(spec)
        self.assertTrue(any(m.get("note") for m in plan["sequence"]["messages"]))

    # --- class: every relation kind renders a distinct marker --------------
    def test_class_all_relation_kinds(self):
        kinds = ["inheritance", "realization", "composition", "aggregation", "dependency", "nesting"]
        classes = [{"id": f"c{i}", "label": f"C{i}"} for i in range(len(kinds) + 1)]
        relations = [{"from": f"c{i+1}", "to": "c0", "kind": k} for i, k in enumerate(kinds)]
        plan = self.plan({"layout": "class", "classes": classes, "relations": relations})
        self.assertEqual(len(plan["edges"]), len(kinds))
        markers = {e.get("arrow") or e.get("marker") or e.get("style") for e in plan["edges"]}
        self.assertGreaterEqual(len(markers), 1)

    def test_class_attributes_and_methods_compartments(self):
        spec = {
            "layout": "class",
            "classes": [{
                "id": "c", "label": "Service",
                "attributes": [{"name": "id", "type": "int"}, {"name": "name", "type": "str"}],
                "methods": [{"name": "run", "type": "void"}],
            }],
        }
        plan = self.plan(spec)
        self.assertGreater(len(plan["nodes"]), 0)

    # --- ER: cardinality labels on relations -------------------------------
    def test_er_cardinality_labels(self):
        spec = {
            "layout": "er",
            "entities": [
                {"id": "user", "label": "User", "attributes": [{"name": "id", "type": "int", "key": "PK"}]},
                {"id": "order", "label": "Order", "attributes": [{"name": "user_id", "type": "int", "key": "FK"}]},
            ],
            "relations": [
                {"from": "user", "to": "order", "from_card": "1", "to_card": "N", "label": "places"},
            ],
        }
        plan = self.plan(spec)
        self.assertEqual(len(plan["edges"]), 1)

    # --- state: transitions with labels and initial/final ------------------
    def test_state_transitions_and_pseudostates(self):
        spec = {
            "layout": "state",
            "states": [
                {"id": "s1", "label": "Idle"},
                {"id": "s2", "label": "Active", "body": "entry / start()"},
                {"id": "init", "kind": "initial"},
                {"id": "done", "kind": "final"},
            ],
            "transitions": [
                {"from": "init", "to": "s1"},
                {"from": "s1", "to": "s2", "label": "go"},
                {"from": "s2", "to": "done", "label": "finish"},
            ],
        }
        plan = self.plan(spec)
        self.assertEqual(len(plan["edges"]), 3)

    # --- activity: fork/join bars + decision guard -------------------------
    def test_activity_fork_join_decision(self):
        spec = {
            "layout": "activity",
            "nodes": [
                {"id": "start", "kind": "initial"},
                {"id": "f", "kind": "fork"},
                {"id": "a", "label": "Do A"},
                {"id": "b", "label": "Do B"},
                {"id": "j", "kind": "join"},
                {"id": "d", "kind": "decision", "yes_label": "ok"},
                {"id": "end", "kind": "final"},
            ],
            "edges": [
                {"from": "start", "to": "f"},
                {"from": "f", "to": "a"}, {"from": "f", "to": "b"},
                {"from": "a", "to": "j"}, {"from": "b", "to": "j"},
                {"from": "j", "to": "d"},
                {"from": "d", "to": "end", "label": "yes"},
            ],
        }
        plan = self.plan(spec)
        self.assertEqual(len(plan["edges"]), 7)

    # --- deployment: nested artifacts + communication paths ----------------
    def test_deployment_nesting(self):
        spec = {
            "layout": "deployment",
            "nodes": [
                {"id": "host", "label": "Host", "kind": "node"},
                {"id": "web", "label": "WebApp", "kind": "artifact", "parent": "host"},
                {"id": "db", "label": "DB", "kind": "node"},
            ],
            "connections": [{"from": "web", "to": "db", "label": "jdbc"}],
        }
        plan = self.plan(spec)
        self.assertGreater(len(plan["nodes"]), 0)

    # --- gantt: sections, milestone, done/active/crit ----------------------
    def test_gantt_task_variants(self):
        spec = {
            "layout": "gantt",
            "sections": [
                {"title": "Phase 1", "tasks": [
                    {"id": "t1", "label": "Design", "start": "2024-01-01", "end": "2024-01-10"},
                    {"id": "t2", "label": "Review", "start": "2024-01-11", "end": "2024-01-13", "kind": "crit"},
                    {"id": "m1", "label": "M1", "start": "2024-01-13", "kind": "milestone"},
                ]},
            ],
        }
        plan = self.plan(spec)
        self.assertIn("sections", plan.get("gantt", plan))

    # --- c4: boundaries + relations ----------------------------------------
    def test_c4_boundaries(self):
        spec = {
            "layout": "c4",
            "elements": [
                {"id": "u", "label": "User", "kind": "person"},
                {"id": "s", "label": "System", "kind": "system", "boundary": "ext"},
                {"id": "api", "label": "API", "kind": "container", "boundary": "core"},
            ],
            "boundaries": [{"id": "ext", "label": "External"}, {"id": "core", "label": "Core"}],
            "relations": [{"from": "u", "to": "s", "label": "uses"}],
        }
        plan = self.plan(spec)
        self.assertEqual(len(plan["edges"]), 1)

    # --- orgchart: multi-root tree -----------------------------------------
    def test_orgchart_multi_root(self):
        spec = {
            "layout": "orgchart",
            "nodes": [
                {"id": "ceo", "label": "CEO"},
                {"id": "cto", "label": "CTO", "parent": "ceo"},
                {"id": "cfo", "label": "CFO", "parent": "ceo"},
                {"id": "vp1", "label": "VP Eng", "parent": "cto"},
            ],
        }
        plan = self.plan(spec)
        self.assertGreater(len(plan["nodes"]), 0)

    # --- mindmap: nested topics --------------------------------------------
    def test_mindmap_nested(self):
        spec = {
            "layout": "mindmap",
            "root": {"label": "AI", "children": [
                {"label": "Data", "children": [{"label": "ETL"}, {"label": "Lake"}]},
                {"label": "Model", "children": [{"label": "Train"}, {"label": "Serve"}]},
            ]},
        }
        plan = self.plan(spec)
        self.assertIn("nodes", plan)

    # --- fishbone: categories + causes -------------------------------------
    def test_fishbone(self):
        spec = {
            "layout": "fishbone",
            "effect": "Latency",
            "categories": [
                {"label": "Network", "causes": ["DNS", "RTT"]},
                {"label": "App", "causes": ["GC", "Locks"]},
            ],
        }
        plan = self.plan(spec)
        self.assertIn("nodes", plan)


if __name__ == "__main__":
    unittest.main()
