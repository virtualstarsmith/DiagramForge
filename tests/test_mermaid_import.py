import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mermaid_import = load_module("mermaid_import")


class ParseTest(unittest.TestCase):
    def parse(self, text):
        direction, nodes, order, edges, notes, _groups, _parents, _roles = mermaid_import.parse_mermaid(text)
        return direction, nodes, edges

    def test_direction_mapping(self):
        self.assertEqual(self.parse("graph TD\na --> b")[0], "down")
        self.assertEqual(self.parse("flowchart LR\na --> b")[0], "right")
        self.assertEqual(self.parse("graph BT\na --> b")[0], "down")

    def test_node_shapes(self):
        _, nodes, _ = self.parse(
            "flowchart LR\n"
            "a[card] --> b{choice}\n"
            "b --> c([stadium])\n"
            "c --> d[(database)]\n"
            "d --> e((circle))\n"
        )
        self.assertEqual(nodes["a"]["kind"], "card")
        self.assertEqual(nodes["b"]["kind"], "decision")
        self.assertEqual(nodes["c"]["kind"], "terminal")
        self.assertEqual(nodes["d"]["kind"], "terminal")
        self.assertEqual(nodes["d"]["label"], "database")
        self.assertEqual(nodes["e"]["kind"], "terminal")

    def test_quoted_and_bare_labels(self):
        _, nodes, edges = self.parse('graph LR\na -- "yes, ship it" --> b\nb -. retry .-> a\n')
        labeled = next(e for e in edges if e["to"] == "b")
        self.assertEqual(labeled["label"], "yes, ship it")
        dotted = next(e for e in edges if e["to"] == "a")
        self.assertEqual(dotted["style"], "dotted")
        self.assertEqual(dotted["label"], "retry")

    def test_chains_and_fans(self):
        _, _, edges = self.parse("graph LR\na --> b --> c\na --> d & e\n")
        pairs = {(e["from"], e["to"]) for e in edges}
        self.assertEqual(pairs, {("a", "b"), ("b", "c"), ("a", "d"), ("a", "e")})

    def test_comments_semicolons_and_subgraph_notes(self):
        direction, nodes, order, edges, notes, _groups, _parents, _roles = mermaid_import.parse_mermaid(
            "graph LR %% comment\nsubgraph inner\na --> b;\nend\n"
        )
        self.assertEqual(direction, "right")
        self.assertIn(("a", "b"), {(e["from"], e["to"]) for e in edges})
        self.assertTrue(any("subgraph" in n for n in notes))

    def test_bare_node_ids(self):
        _, nodes, edges = self.parse("graph LR\nalpha --> beta\n")
        self.assertEqual(nodes["alpha"]["label"], "alpha")
        self.assertEqual(edges[0]["from"], "alpha")


class SpecTest(unittest.TestCase):
    def test_to_spec_shape(self):
        spec, _ = mermaid_import.to_spec("flowchart LR\na[x] --> b{y?}\n", title="T", style="report")
        self.assertEqual(spec["layout"], "graph")
        self.assertEqual(spec["style"], "report")
        self.assertEqual(spec["direction"], "right")
        self.assertEqual(spec["nodes"][1]["kind"], "decision")
        self.assertEqual(spec["title"]["prefix"], "T")

    def test_empty_document_fails(self):
        with self.assertRaises(SystemExit):
            mermaid_import.to_spec("just some text")

    def test_imported_spec_passes_renderer_validation(self):
        sys_path_added = str(ROOT / "scripts")
        import sys
        if sys_path_added not in sys.path:
            sys.path.insert(0, sys_path_added)
        renderer = load_module("render_animated_diagram")
        spec, _ = mermaid_import.to_spec(
            "flowchart LR\ningest[Ingest] --> gate{Pass?}\ngate -. retry .-> ingest\n"
        )
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)


class SequenceImportTest(unittest.TestCase):
    def test_basic_message_kinds(self):
        spec, _ = mermaid_import.to_spec(
            "sequenceDiagram\n"
            "participant A\n"
            "participant B\n"
            "A->>B: call\n"
            "B-->>A: reply\n"
            "B->B: work\n"
        )
        self.assertEqual(spec["layout"], "sequence")
        kinds = [m["kind"] for m in spec["messages"]]
        self.assertEqual(kinds, ["sync", "return", "sync"])
        self.assertEqual(spec["messages"][0]["label"], "call")

    def test_actor_declarations_and_as_labels(self):
        spec, _ = mermaid_import.to_spec(
            "sequenceDiagram\n"
            "actor U as 用户\n"
            "participant S as 服务\n"
            "U->>S: hi\n"
        )
        by_id = {p["id"]: p for p in spec["participants"]}
        self.assertEqual(by_id["U"]["kind"], "actor")
        self.assertEqual(by_id["U"]["label"], "用户")
        self.assertNotIn("kind", by_id["S"])

    def test_alt_else_and_loop_fragments(self):
        spec, _ = mermaid_import.to_spec(
            "sequenceDiagram\n"
            "participant A\nparticipant B\n"
            "A->>B: try\n"
            "alt ok\n"
            "B-->>A: yes\n"
            "else no\n"
            "B-->>A: no\n"
            "end\n"
            "loop retry\n"
            "A->>A: check\n"
            "end\n"
        )
        alt, loop = spec["fragments"]
        self.assertEqual(alt["kind"], "alt")
        self.assertEqual(alt["range"], [1, 2])
        self.assertEqual(alt["dividers"], [{"at": 2, "label": "no"}])
        self.assertEqual(loop["kind"], "loop")
        self.assertEqual(loop["range"], [3, 3])

    def test_notes_and_activate(self):
        spec, notes = mermaid_import.to_spec(
            "sequenceDiagram\n"
            "participant A\nparticipant B\n"
            "A->>B: call\n"
            "activate B\n"
            "Note over A,B: shared\n"
            "B-->>A: done\n"
            "deactivate B\n"
        )
        self.assertTrue(spec["messages"][0].get("activate"))
        note = spec["messages"][1]
        self.assertEqual(note["kind"], "note")
        self.assertEqual(note["target"], ["A", "B"])
        self.assertTrue(any("autonumber" not in n for n in notes))

    def test_imported_sequence_passes_renderer_validation(self):
        sys_path_added = str(ROOT / "scripts")
        import sys
        if sys_path_added not in sys.path:
            sys.path.insert(0, sys_path_added)
        renderer = load_module("render_animated_diagram")
        spec, _ = mermaid_import.to_spec(
            "sequenceDiagram\n"
            "actor U as 用户\nparticipant G as 网关\nparticipant S as 服务\n"
            "U->>G: 提交\nG->>S: 处理\nalt 成功\nS-->>G: 好\nelse 失败\nS-->>G: 坏\nend\nG-->>U: 展示\n"
        )
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["errors"], [])


class ErImportTest(unittest.TestCase):
    def test_relations_and_cardinality(self):
        spec, notes = mermaid_import.to_spec(
            "erDiagram\n"
            'USER ||--o{ ORDER : "下单"\n'
            "ORDER ||--|{ ORDER_ITEM : 包含\n"
        )
        self.assertEqual(spec["layout"], "er")
        self.assertEqual(len(spec["relations"]), 2)
        first = spec["relations"][0]
        self.assertEqual((first["from_card"], first["to_card"]), ("1", "0..*"))
        self.assertEqual(first["label"], "下单")
        self.assertEqual(notes, [])

    def test_attribute_blocks(self):
        spec, _ = mermaid_import.to_spec(
            "erDiagram\n"
            "USER ||--o{ ORDER : has\n"
            "USER {\n"
            "    bigint id PK\n"
            "    varchar name\n"
            "}\n"
        )
        user = next(e for e in spec["entities"] if e["id"] == "USER")
        self.assertEqual(user["attributes"][0], {"name": "id", "type": "bigint", "key": "pk"})
        self.assertNotIn("key", user["attributes"][1])


class ClassImportTest(unittest.TestCase):
    def test_relation_kinds_and_direction(self):
        spec, _ = mermaid_import.to_spec(
            "classDiagram\n"
            "Order <|-- VipOrder\n"
            "Order *-- OrderItem : 包含\n"
            "IRepo <|.. MysqlRepo\n"
            "Order ..> Logger\n"
        )
        self.assertEqual(spec["layout"], "class")
        kinds = {(r["from"], r["to"]): r["kind"] for r in spec["relations"]}
        self.assertEqual(kinds[("VipOrder", "Order")], "inheritance")
        self.assertEqual(kinds[("Order", "OrderItem")], "composition")
        self.assertEqual(kinds[("MysqlRepo", "IRepo")], "realization")
        self.assertEqual(kinds[("Order", "Logger")], "dependency")

    def test_class_blocks_members_and_stereotypes(self):
        spec, _ = mermaid_import.to_spec(
            "classDiagram\n"
            "class Order {\n"
            "    -Long id\n"
            "    +create() void\n"
            "}\n"
            "class IRepo {\n"
            "    <<interface>>\n"
            "    +save(o) void\n"
            "}\n"
            "Order --> IRepo\n"
        )
        by_id = {c["id"]: c for c in spec["classes"]}
        self.assertEqual(by_id["IRepo"]["kind"], "interface")
        self.assertEqual(by_id["Order"]["attributes"][0]["visibility"], "-")
        self.assertEqual(by_id["Order"]["attributes"][0]["type"], "Long")
        self.assertEqual(by_id["Order"]["methods"][0]["name"], "create()")
        self.assertEqual(by_id["Order"]["methods"][0]["type"], "void")

    def test_imported_specs_pass_renderer_validation(self):
        import sys
        sys_path_added = str(ROOT / "scripts")
        if sys_path_added not in sys.path:
            sys.path.insert(0, sys_path_added)
        renderer = load_module("render_animated_diagram")
        er_spec, _ = mermaid_import.to_spec(
            'erDiagram\nUSER ||--o{ ORDER : has\nUSER {\n bigint id PK\n}\n'
        )
        self.assertTrue(renderer.validate_spec(er_spec)["ok"])
        class_spec, _ = mermaid_import.to_spec(
            "classDiagram\nclass A { +int x }\nA <|-- B\n"
        )
        result = renderer.validate_spec(class_spec)
        self.assertTrue(result["ok"], result)
class StateImportTest(unittest.TestCase):
    def test_transitions_and_initial_final(self):
        spec, notes = mermaid_import.to_spec(
            "stateDiagram-v2\n"
            "[*] --> Idle\n"
            "Idle --> Running : start\n"
            "Running --> [*]\n"
        )
        self.assertEqual(spec["layout"], "state")
        kinds = {s["id"]: s.get("kind") for s in spec["states"]}
        self.assertEqual(kinds["_initial"], "initial")
        self.assertEqual(kinds["_final"], "final")
        labels = [t.get("label") for t in spec["transitions"]]
        self.assertIn("start", labels)
        self.assertEqual(notes, [])

    def test_description_becomes_body(self):
        spec, _ = mermaid_import.to_spec(
            "stateDiagram-v2\n"
            "[*] --> A\n"
            "A : entry / init\n"
            "A --> B\n"
        )
        a = next(s for s in spec["states"] if s["id"] == "A")
        self.assertEqual(a["body"], "entry / init")

    def test_imported_state_passes_renderer_validation(self):
        import sys
        sys_path_added = str(ROOT / "scripts")
        if sys_path_added not in sys.path:
            sys.path.insert(0, sys_path_added)
        renderer = load_module("render_animated_diagram")
        spec, _ = mermaid_import.to_spec(
            "stateDiagram-v2\n[*] --> A\nA --> B : go\nB --> A : back\nB --> [*]\n"
        )
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)


class _RendererCheckMixin:
    def assert_renderer_ok(self, spec):
        import sys
        sys_path_added = str(ROOT / "scripts")
        if sys_path_added not in sys.path:
            sys.path.insert(0, sys_path_added)
        renderer = load_module("render_animated_diagram")
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)


class GanttImportTest(_RendererCheckMixin, unittest.TestCase):
    def test_sections_tasks_and_kinds(self):
        spec, notes = mermaid_import.to_spec(
            "gantt\n"
            "    dateFormat YYYY-MM-DD\n"
            "    section 设计\n"
            "    评审 :done, d1, 2026-08-01, 2026-08-04\n"
            "    原型 :active, after d1, 4d\n"
            "    section 开发\n"
            "    后端 :crit, 2026-08-10, 2026-08-25\n"
            "    上线 :milestone, 2026-08-28, 0d\n"
        )
        self.assertEqual(spec["layout"], "gantt")
        self.assertEqual(len(spec["sections"]), 2)
        design, dev = spec["sections"]
        self.assertEqual(design["tasks"][0]["kind"], "done")
        # "after d1" chains to the referenced task's end date.
        self.assertEqual(design["tasks"][1]["start"], "2026-08-04")
        self.assertEqual(design["tasks"][1]["end"], "2026-08-08")
        self.assertEqual(dev["tasks"][1]["kind"], "milestone")
        self.assertNotIn("end", dev["tasks"][1])

    def test_imported_gantt_passes_renderer_validation(self):
        spec, _ = mermaid_import.to_spec(
            "gantt\nsection S\na : 2026-08-01, 2026-08-03\nb :done, 2026-08-02, 2d\n")
        self.assert_renderer_ok(spec)


class MindmapImportTest(_RendererCheckMixin, unittest.TestCase):
    def test_indentation_tree(self):
        spec, notes = mermaid_import.to_spec(
            "mindmap\n"
            "  root((系统分析师))\n"
            "    需求工程\n"
            "      访谈\n"
            "      用例建模\n"
            "    结构化分析\n"
        )
        self.assertEqual(spec["layout"], "mindmap")
        root = spec["root"]
        self.assertEqual(root["label"], "系统分析师")
        self.assertEqual([c["label"] for c in root["children"]], ["需求工程", "结构化分析"])
        leaves = root["children"][0]["children"]
        self.assertEqual([l["label"] for l in leaves], ["访谈", "用例建模"])

    def test_imported_mindmap_passes_renderer_validation(self):
        spec, _ = mermaid_import.to_spec("mindmap\n  root((R))\n    A\n      a1\n    B\n")
        self.assert_renderer_ok(spec)


class TimelineImportTest(_RendererCheckMixin, unittest.TestCase):
    def test_period_events_split(self):
        spec, notes = mermaid_import.to_spec(
            "timeline\n"
            "    title 产品路线\n"
            "    2025 Q1 : 立项 : 组队\n"
            "    2025 Q2 : MVP\n"
        )
        self.assertEqual(spec["layout"], "timeline")
        self.assertEqual(len(spec["events"]), 3)
        self.assertEqual(spec["events"][0]["time"], "2025 Q1")
        self.assertEqual(spec["events"][1]["label"], "组队")

    def test_imported_timeline_passes_renderer_validation(self):
        spec, _ = mermaid_import.to_spec("timeline\nQ1 : a\nQ2 : b\n")
        self.assert_renderer_ok(spec)


class C4ImportTest(_RendererCheckMixin, unittest.TestCase):
    def test_elements_boundaries_relations(self):
        spec, notes = mermaid_import.to_spec(
            "C4Container\n"
            "    Person(user, \"买家\")\n"
            "    System_Boundary(b1, \"电商系统\") {\n"
            "        Container(web, \"商城 Web\", \"React\")\n"
            "        ContainerDb(db, \"订单库\", \"PostgreSQL\")\n"
            "    }\n"
            "    System_Ext(pay, \"支付平台\")\n"
            "    Rel(user, web, \"使用\")\n"
            "    Rel(web, db, \"读写\", \"JDBC\")\n"
        )
        self.assertEqual(spec["layout"], "c4")
        by_id = {e["id"]: e for e in spec["elements"]}
        self.assertEqual(by_id["user"]["kind"], "person")
        self.assertEqual(by_id["web"]["kind"], "container")
        self.assertEqual(by_id["web"]["boundary"], "b1")
        self.assertEqual(by_id["db"]["kind"], "database")
        self.assertEqual(by_id["pay"]["kind"], "ext_system")
        self.assertNotIn("boundary", by_id["pay"])
        self.assertEqual(spec["boundaries"][0]["label"], "电商系统")
        self.assertEqual(spec["relations"][1]["technology"], "JDBC")

    def test_imported_c4_passes_renderer_validation(self):
        spec, _ = mermaid_import.to_spec(
            "C4Context\nPerson(u, \"U\")\nSystem(s, \"S\")\nRel(u, s, \"uses\")\n")
        self.assert_renderer_ok(spec)


if __name__ == "__main__":
    unittest.main()
