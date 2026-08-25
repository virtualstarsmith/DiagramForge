"""Branch coverage for mermaid_import: malformed lines, note-generating
fallbacks, empty-diagram SystemExits, and the CLI note printing path."""
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mi = load_module("mermaid_import")


class FlowchartBranchTest(unittest.TestCase):
    def test_shapes_skips_and_edge_labels(self):
        mmd = """flowchart LR
        a{Decision} --> b[(Store)]
        b --> c
        click a callback
        style a fill:#fff
        linkStyle 0 stroke:#f00
        """
        spec, notes = mi.to_spec(mmd)
        kinds = {n["id"]: n.get("kind") for n in spec["nodes"]}
        self.assertEqual(kinds.get("a"), "decision")
        self.assertEqual(len(spec["edges"]), 2)

    def test_diagram_kind_fallback(self):
        self.assertEqual(mi._diagram_kind("gibberish"), "flowchart")
        self.assertFalse(mi._is_sequence_diagram("flowchart LR\na-->b"))


class SequenceBranchTest(unittest.TestCase):
    def test_actor_label_and_message_edges(self):
        mmd = """sequenceDiagram
        actor u as User
        participant p as Proc
        u->>p: call
        p--x u: lost reply
        activate p
        p->>p: self work
        deactivate p
        activate ghost
        deactivate p
        autonumber
        rect rgb(0,0,0)
        end
        note over u: stray note
        alt works
        u->>p: again
        else
        p-->>u: back
        end
        else
        end
        opt leftover
        u->>p: dangling
        """
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("lost-message" in n for n in notes))
        self.assertTrue(any("autonumber" in n for n in notes))
        self.assertTrue(any("else without" in n for n in notes))
        self.assertTrue(any("no earlier message" in n for n in notes))
        self.assertTrue(any("unclosed" in n for n in notes))
        actors = [p for p in spec["participants"] if p.get("kind") == "actor"]
        self.assertEqual(actors[0]["id"], "u")

    def test_empty_diagram_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("sequenceDiagram\nnote over a: only notes\n")


class ErBranchTest(unittest.TestCase):
    def test_attribute_skip_and_entity_synthesis(self):
        mmd = """erDiagram
        USER ||--o{ ORDER : places
        USER {
            int id PK
            string name
        }
        bogus line here
        ORDER {
            weird line
        }
        """
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("skipped" in n for n in notes))
        ids = {e["id"] for e in spec["entities"]}
        self.assertIn("USER", ids)

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("erDiagram\n%% nothing\n")


class ClassBranchTest(unittest.TestCase):
    def test_member_parsing_and_cardinality(self):
        self.assertIsNone(mi._class_member(""))
        m = mi._class_member("-name")
        self.assertEqual(m["visibility"], "-")
        m2 = mi._class_member("plain")
        self.assertEqual(m2["name"], "plain")
        m3 = mi._class_member("+doIt() void")
        self.assertEqual(m3["type"], "void")

    def test_class_diagram_branches(self):
        mmd = """classDiagram
        class Animal {
            +String name
            +speak() void
        }
        Animal <|-- Dog
        Car *-- Wheel
        Shop o-- "1..*" Item
        bogus %% line
        """
        spec, notes = mi.to_spec(mmd)
        kinds = {r["kind"] for r in spec["relations"]}
        self.assertIn("inheritance", kinds)
        self.assertTrue(any("skipped" in n for n in notes))

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("classDiagram\n%% nothing\n")


class StateBranchTest(unittest.TestCase):
    def test_composite_alias_and_skips(self):
        mmd = """stateDiagram-v2
        state "Running" as run
        state Composite {
            [*] --> inner
        }
        direction LR
        note left of run : noted
        scale 2
        bogus line
        [*] --> run
        run --> [*]
        """
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("composite state flattened" in n for n in notes))
        self.assertTrue(any("skipped line" in n for n in notes))
        labels = {s["id"]: s.get("label") for s in spec["states"]}
        self.assertEqual(labels.get("run"), "Running")

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("stateDiagram-v2\n%% nothing\n")


class GanttBranchTest(unittest.TestCase):
    def test_after_unknown_and_missing_start(self):
        mmd = """gantt
        title Plan
        dateFormat YYYY-MM-DD
        section Build
        task1 : 2026-01-01, 3d
        task2 : after ghost, 2d
        task3 : active
        bogus line
        """
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("unknown 'after' reference" in n for n in notes))
        self.assertTrue(any("no start date" in n for n in notes))
        self.assertTrue(any("skipped line" in n for n in notes))

    def test_task_without_section_creates_default(self):
        mmd = """gantt
        dateFormat YYYY-MM-DD
        lonely : 2026-01-01, 2d
        """
        spec, _ = mi.to_spec(mmd)
        self.assertEqual(len(spec["sections"]), 1)

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("gantt\ntitle Nothing\n")


class MindmapBranchTest(unittest.TestCase):
    def test_label_shapes_and_detached(self):
        self.assertEqual(mi._mindmap_label("[Square]"), "Square")
        self.assertEqual(mi._mindmap_label("((Round))"), "Round")
        self.assertEqual(mi._mindmap_label("node1[Label Text]"), "Label Text")
        self.assertEqual(mi._mindmap_label("  "), "")
        mmd = """mindmap
        root((Root))
            A
                A1
        B
        """
        spec, notes = mi.to_spec(mmd)
        # B at indent 0 after the root -> detached branch attached to root
        labels = [c["label"] for c in spec["root"]["children"]]
        self.assertIn("A", labels)

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("mindmap\n%% nothing\n")


class TimelineBranchTest(unittest.TestCase):
    def test_skip_and_overflow(self):
        mmd = """timeline
        title Roadmap
        bogus line
        """ + "\n".join(f"        Q{i} : Event{i}" for i in range(14))
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("skipped line" in n for n in notes))
        self.assertTrue(any("first 12" in n for n in notes))

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("timeline\ntitle Empty\n")


class C4BranchTest(unittest.TestCase):
    def test_boundaries_rels_and_skips(self):
        mmd = """C4Context
        title System Context
        Person(user, "User", "A person")
        System_Boundary(b1, "Core") {
            System(app, "App", "Python")
        }
        Rel(user, app, "Uses", "HTTPS")
        Lay_Distance(user, app, 1)
        bogus line
        """
        spec, notes = mi.to_spec(mmd)
        self.assertTrue(any("skipped line" in n for n in notes))
        bounds = [b["id"] for b in spec.get("boundaries", [])]
        self.assertIn("b1", bounds)

    def test_empty_exits(self):
        with self.assertRaises(SystemExit):
            mi.to_spec("C4Context\ntitle Nothing\n")


class MainBranchTest(unittest.TestCase):
    def test_main_prints_notes_to_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.mmd"
            src.write_text("sequenceDiagram\na->>b: hi\nautonumber\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["mermaid_import.py", str(src)]), \
                 redirect_stdout(out), redirect_stderr(err):
                code = mi.main()
            self.assertEqual(code, 0)
            self.assertIn("note:", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class ConfirmedTriggerTest(unittest.TestCase):
    """Triggers verified against the parser's actual behavior."""

    def test_flowchart_redeclare_and_kind_upgrade(self):
        mmd = "\n\nflowchart LR\na --> b\na[Relabeled]\nx\nx{Tri}\n"
        spec, _ = mi.to_spec(mmd)
        nodes = {n["id"]: n for n in spec["nodes"]}
        self.assertEqual(nodes["a"]["label"], "Relabeled")
        self.assertEqual(nodes["x"]["kind"], "decision")

    def test_edge_attrs_unmatched_token_defaults(self):
        self.assertEqual(mi._edge_attrs("--"), {"style": "solid", "label": ""})

    def test_fan_list_inherits_edge_label(self):
        spec, _ = mi.to_spec("flowchart LR\na -- lbl --> b & c\n")
        labels = [e.get("label") for e in spec["edges"]]
        self.assertEqual(labels, ["lbl", "lbl"])

    def test_unconsumed_line_notes(self):
        notes = mi.parse_mermaid("flowchart LR\na --> b\n|||\n:::\n")
        self.assertTrue(any("skipped line: |||" in n for n in notes))
        self.assertTrue(any("skipped line: :::" in n for n in notes))

    def test_diagram_kind_all_blank_fallback(self):
        self.assertEqual(mi._diagram_kind("%% only a comment\n\n"), "flowchart")

    def test_sequence_redeclare_label_and_actor_upgrade(self):
        spec, _ = mi.to_spec(
            "sequenceDiagram\na->>b: hi\nparticipant a as Alice\nactor c\na->>c: yo\n")
        parts = {p["id"]: p for p in spec["participants"]}
        self.assertEqual(parts["a"]["label"], "Alice")
        self.assertEqual(parts["c"]["kind"], "actor")

    def test_fragment_note_snapping(self):
        # leading note inside the fragment -> snap start forward
        spec, _ = mi.to_spec(
            "sequenceDiagram\na->>b: m0\nalt g\nnote over a: n1\na->>b: m1\nend\n")
        self.assertEqual(spec["fragments"][0]["range"], [2, 2])
        # note-only fragment is dropped
        _, notes = mi.to_spec(
            "sequenceDiagram\na->>b: hi\nalt only notes\nnote over a: x\nend\n")
        self.assertTrue(any("empty combined fragment dropped" in n for n in notes))
        # trailing note -> snap end back; divider landing on a note -> snap forward
        spec, _ = mi.to_spec(
            "sequenceDiagram\na->>b: first\nalt g\na->>b: mid\nelse\n"
            "note over a: dnote\na->>b: last\nnote over a: tail\nend\n")
        frag = spec["fragments"][0]
        self.assertEqual(frag["range"], [1, 3])

    def test_er_bad_attribute_and_new_entity_block(self):
        spec, notes = mi.to_spec("erDiagram\nA ||--o{ B : x\nC {\n int id\n !!!\n}\n")
        self.assertTrue(any("skipped attribute line" in n for n in notes))
        self.assertIn("C", {e["id"] for e in spec["entities"]})

    def test_class_marker_at_a_cardinality_and_skips(self):
        spec, notes = mi.to_spec(
            'classDiagram\nAnimal <|-- Dog\nCompany "1" *-- "many" Employee\n'
            'direction TB\nnote for Animal "hi"\n')
        rel = next(r for r in spec["relations"] if r["kind"] == "composition")
        self.assertEqual(rel.get("from_card"), "1")
        self.assertTrue(any("skipped line: direction TB" in n for n in notes))

    def test_state_relabel_after_use(self):
        spec, _ = mi.to_spec('stateDiagram-v2\n[*] --> s1\nstate "Active" as s1\ns1 --> [*]\n')
        states = {s["id"]: s for s in spec["states"]}
        self.assertEqual(states["s1"]["label"], "Active")

    def test_mindmap_empty_label_skipped(self):
        self.assertEqual(mi._mindmap_label("[( )]"), "")
        spec, _ = mi.to_spec("mindmap\nroot((R))\n  [( )]\n  child\n")
        self.assertEqual(len(spec["root"]["children"]), 1)


class SequenceLateActorAndGarbageTest(unittest.TestCase):
    def test_actor_redeclaration_upgrades_kind(self):
        spec, notes = mi.to_spec("sequenceDiagram\na->>c: yo\nactor c\n!!! garbage\n")
        parts = {p["id"]: p for p in spec["participants"]}
        self.assertEqual(parts["c"]["kind"], "actor")
        self.assertTrue(any("skipped line" in n for n in notes))
