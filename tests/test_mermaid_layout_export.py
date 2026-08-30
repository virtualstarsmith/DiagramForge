"""tests for typed-layout Mermaid exports (sequence / er / class / state)."""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import spec_graph

EXAMPLES = REPO / "assets" / "examples"


def _spec(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class SequenceExportTest(unittest.TestCase):
    def test_native_sequence_diagram_with_fragments(self):
        out = spec_graph.export_mermaid(_spec("sequence-spec.json"))
        self.assertTrue(out.startswith("sequenceDiagram"))
        self.assertIn("actor user as 用户", out)
        self.assertIn("alt 库存充足", out)
        self.assertIn("else 库存不足，走补货流程", out)
        self.assertIn("loop 重试 ≤ 3 次", out)
        self.assertIn("Note over order, stock", out)
        # ends balance: every alt/loop opens one `end`
        opens = sum(1 for line in out.splitlines() if line.strip() in ("alt 库存充足", "loop 重试 ≤ 3 次"))
        ends = sum(1 for line in out.splitlines() if line.strip() == "end")
        self.assertEqual(opens, ends)
        self.assertIn("order -)mq: 订单已创建事件", out)  # async arrow
        self.assertIn("stock -->>order", out)  # dashed return

    def test_fragments_close_even_at_trailing_messages(self):
        spec = {
            "layout": "sequence",
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [
                {"from": "a", "to": "b", "label": "m1", "kind": "sync"},
                {"from": "a", "to": "b", "label": "m2", "kind": "sync"},
            ],
            "fragments": [{"kind": "opt", "label": "only", "range": [2, 2]}],
        }
        out = spec_graph.export_mermaid(spec)
        self.assertIn("opt only", out)
        self.assertTrue(out.strip().endswith("end"), "trailing fragment must close")


class ErExportTest(unittest.TestCase):
    def test_entities_attributes_and_cardinality(self):
        out = spec_graph.export_mermaid(_spec("er-spec.json"))
        self.assertTrue(out.startswith("erDiagram"))
        self.assertIn("bigint id PK", out)
        self.assertIn("bigint user_id FK", out)
        self.assertIn("user ||--o{ order : 下单", out)
        self.assertIn("item }o--|| sku : 对应", out)
        self.assertIn("order }o--o{ addr : 投递", out)


class ClassExportTest(unittest.TestCase):
    def test_members_stereotypes_and_arrows(self):
        out = spec_graph.export_mermaid(_spec("class-spec.json"))
        self.assertTrue(out.startswith("classDiagram"))
        self.assertIn("<<interface>>", out)
        self.assertIn("+create() void", out)  # space syntax, not colon
        self.assertIn("-Long id", out)
        self.assertIn("*--", out)   # composition
        self.assertIn("..|>", out)  # realization
        self.assertIn("--|>", out)  # inheritance
        self.assertIn('"1..*"', out)  # cardinality markers survive

    def test_hostile_labels_are_flattened(self):
        spec = {
            "layout": "class",
            "classes": [{"id": "a", "label": "A", "attributes": [{"name": "x;-->\n", "type": "T", "visibility": "-"}]}],
            "relations": [{"from": "a", "to": "a", "kind": "association", "label": 'say "hi";\nnext'}],
        }
        out = spec_graph.export_mermaid(spec)
        self.assertNotIn("\n-->", out)
        self.assertNotIn('";', out.replace(";\n", "\n"))
        self.assertIn("say 'hi',", out)


class StateExportTest(unittest.TestCase):
    def test_initial_final_and_labels(self):
        out = spec_graph.export_mermaid(_spec("state-spec.json"))
        self.assertTrue(out.startswith("stateDiagram-v2"))
        self.assertIn("[*] --> created", out)
        self.assertIn("closed --> [*]", out)
        self.assertIn("created --> paid: 支付成功 [库存充足] / 核销", out)

    def test_bodies_are_noted_not_mangled(self):
        out = spec_graph.export_mermaid(_spec("state-spec.json"))
        self.assertNotIn('state "entry', out)
        self.assertIn("%% notes: state entry/do bodies are not representable", out)


class DispatchTest(unittest.TestCase):
    def test_dispatch_by_layout_and_dot_guard(self):
        for name, marker in (("sequence-spec.json", "sequenceDiagram"), ("er-spec.json", "erDiagram"),
                             ("class-spec.json", "classDiagram"), ("state-spec.json", "stateDiagram-v2")):
            out = spec_graph.export_mermaid(_spec(name))
            self.assertTrue(out.startswith(marker), f"{name}: expected {marker}")
        # graph layout keeps the flowchart form
        out = spec_graph.export_mermaid(_spec("graph-workflow-spec.json"))
        self.assertRegex(out, r"^graph (TD|LR)")
        # dot export refuses typed layouts with a clear message
        old_argv = sys.argv
        sys.argv = ["spec_graph.py", "export", "--spec", str(EXAMPLES / "sequence-spec.json"), "--format", "dot"]
        try:
            with self.assertRaises(SystemExit):
                spec_graph.main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
