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


renderer = load_module("render_animated_diagram")


def valid_spec():
    return {
        "layout": "sequence",
        "participants": [
            {"id": "u", "label": "用户", "kind": "actor"},
            {"id": "gw", "label": "网关"},
            {"id": "svc", "label": "服务"},
            {"id": "mq", "label": "队列"},
        ],
        "messages": [
            {"from": "u", "to": "gw", "label": "提交", "kind": "sync"},
            {"from": "gw", "to": "svc", "label": "处理", "kind": "sync"},
            {"from": "svc", "to": "gw", "label": "好", "kind": "return"},
            {"from": "svc", "to": "gw", "label": "坏", "kind": "return"},
            {"from": "gw", "to": "u", "label": "展示", "kind": "return"},
            {"from": "gw", "to": "mq", "label": "事件", "kind": "async"},
        ],
        "fragments": [
            {"kind": "alt", "label": "成功", "range": [2, 3], "dividers": [{"at": 3, "label": "失败"}]},
        ],
    }


class SequenceValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_valid_spec_with_alt_branches_is_clean(self):
        result = renderer.validate_spec(valid_spec())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["warnings"], [])

    def test_missing_sections(self):
        result = renderer.validate_spec({"layout": "sequence"})
        self.assertFalse(result["ok"])
        self.assertIn("$.participants", self.paths(result))
        self.assertIn("$.messages", self.paths(result))

    def test_unknown_participant_reference(self):
        spec = valid_spec()
        spec["messages"][0]["to"] = "ghost"
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.messages[0].to", self.paths(result))

    def test_duplicate_participant_id(self):
        spec = valid_spec()
        spec["participants"][1]["id"] = "u"
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.participants[1].id", self.paths(result))

    def test_unknown_message_kind(self):
        spec = valid_spec()
        spec["messages"][0]["kind"] = "magic"
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.messages[0].kind", self.paths(result))

    def test_note_requires_known_target(self):
        spec = valid_spec()
        spec["messages"].append({"kind": "note", "target": "ghost", "text": "x"})
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn(f"$.messages[{len(spec['messages']) - 1}].target", self.paths(result))

    def test_fragment_range_out_of_bounds(self):
        spec = valid_spec()
        spec["fragments"] = [{"kind": "loop", "label": "x", "range": [0, 99]}]
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.fragments[0].range", self.paths(result))

    def test_fragment_endpoint_on_note(self):
        spec = valid_spec()
        spec["messages"].insert(1, {"kind": "note", "target": "gw", "text": "n"})
        spec["fragments"] = [{"kind": "opt", "label": "x", "range": [1, 2]}]
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.fragments[0].range", self.paths(result))

    def test_cross_nesting_fragments_rejected(self):
        spec = valid_spec()
        spec["fragments"] = [
            {"kind": "alt", "label": "a", "range": [0, 3], "dividers": [{"at": 2, "label": "e"}]},
            {"kind": "loop", "label": "b", "range": [2, 4]},
        ]
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.fragments[1].range", self.paths(result))

    def test_full_nesting_allowed(self):
        spec = valid_spec()
        spec["fragments"] = [
            {"kind": "alt", "label": "a", "range": [0, 4], "dividers": [{"at": 4, "label": "e"}]},
            {"kind": "loop", "label": "b", "range": [1, 3]},
        ]
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)

    def test_unpaired_sync_warns_but_renders(self):
        spec = valid_spec()
        spec["messages"] = [{"from": "u", "to": "gw", "label": "石沉大海", "kind": "sync"}]
        spec["fragments"] = []
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("never gets a matching return" in w["message"] for w in result["warnings"]))

    def test_alt_without_divider_warns(self):
        spec = valid_spec()
        spec["fragments"] = [{"kind": "alt", "label": "a", "range": [1, 2]}]
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("no else divider" in w["message"] for w in result["warnings"]))

    def test_canvas_size_warning(self):
        spec = valid_spec()
        spec["canvas"] = {"width": 800}
        result = renderer.validate_spec(spec)
        self.assertTrue(any(w["path"] == "$.canvas" for w in result["warnings"]))
class BoxDiagramValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_er_valid_and_unknown_ref(self):
        good = {"layout": "er",
                "entities": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "relations": [{"from": "a", "to": "b", "cardinality": "1:N"}]}
        self.assertTrue(renderer.validate_spec(good)["ok"])
        bad = {"layout": "er",
               "entities": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
               "relations": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(bad)
        self.assertFalse(result["ok"])
        self.assertIn("$.relations[0].to", self.paths(result))

    def test_er_bad_cardinality(self):
        spec = {"layout": "er",
                "entities": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "relations": [{"from": "a", "to": "b", "cardinality": "many"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.relations[0].cardinality", self.paths(result))

    def test_usecase_include_between_actors_warns(self):
        spec = {"layout": "usecase",
                "actors": [{"id": "u", "label": "U"}],
                "usecases": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "links": [{"from": "u", "to": "a", "kind": "include"}]}
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"])
        self.assertTrue(any("only applies between use cases" in w["message"] for w in result["warnings"]))

    def test_usecase_unknown_link_end(self):
        spec = {"layout": "usecase",
                "actors": [{"id": "u", "label": "U"}],
                "usecases": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "links": [{"from": "u", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.links[0].to", self.paths(result))

    def test_class_relation_kind_enum(self):
        spec = {"layout": "class",
                "classes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "relations": [{"from": "a", "to": "b", "kind": "magic"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.relations[0].kind", self.paths(result))

    def test_class_kind_enum(self):
        spec = {"layout": "class",
                "classes": [{"id": "a", "label": "A", "kind": "widget"}, {"id": "b", "label": "B"}],
                "relations": []}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.classes[0].kind", self.paths(result))
class BehaviorDiagramValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_activity_two_initials_rejected(self):
        spec = {"layout": "activity",
                "nodes": [{"id": "s1", "kind": "initial"}, {"id": "s2", "kind": "initial"},
                          {"id": "a", "label": "A", "kind": "action"}],
                "edges": [{"from": "s1", "to": "a"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.nodes", self.paths(result))

    def test_activity_unknown_edge_end(self):
        spec = {"layout": "activity",
                "nodes": [{"id": "s", "kind": "initial"}, {"id": "a", "label": "A", "kind": "action"}],
                "edges": [{"from": "s", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.edges[0].to", self.paths(result))

    def test_state_unknown_transition_end(self):
        spec = {"layout": "state",
                "states": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "transitions": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.transitions[0].to", self.paths(result))

    def test_state_kind_enum(self):
        spec = {"layout": "state",
                "states": [{"id": "a", "label": "A", "kind": "magic"}, {"id": "b", "label": "B"}],
                "transitions": []}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.states[0].kind", self.paths(result))

    def test_dfd_kind_enum_and_flow_refs(self):
        spec = {"layout": "dfd",
                "nodes": [{"id": "a", "label": "A", "kind": "widget"}, {"id": "b", "label": "B"}],
                "flows": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.nodes[0].kind", self.paths(result))
        self.assertIn("$.flows[0].to", self.paths(result))

    def test_valid_activity_state_dfd(self):
        act = {"layout": "activity",
               "nodes": [{"id": "s", "kind": "initial"}, {"id": "a", "label": "A", "kind": "action"},
                         {"id": "f", "kind": "final"}],
               "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "f"}]}
        self.assertTrue(renderer.validate_spec(act)["ok"])
        st = {"layout": "state",
              "states": [{"id": "i", "kind": "initial"}, {"id": "a", "label": "A", "body": "entry / x"}],
              "transitions": [{"from": "i", "to": "a"}]}
        self.assertTrue(renderer.validate_spec(st)["ok"])
        dfd = {"layout": "dfd",
               "nodes": [{"id": "e", "label": "E", "kind": "external"},
                         {"id": "p", "label": "P", "kind": "process"}],
               "flows": [{"from": "e", "to": "p", "label": "req"}]}
        self.assertTrue(renderer.validate_spec(dfd)["ok"])


class StructureDiagramValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_deployment_kind_enum_and_conn_refs(self):
        spec = {"layout": "deployment",
                "nodes": [{"id": "a", "label": "A", "kind": "widget"}, {"id": "b", "label": "B"}],
                "connections": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.nodes[0].kind", self.paths(result))
        self.assertIn("$.connections[0].to", self.paths(result))

    def test_component_interface_owner_required(self):
        spec = {"layout": "component",
                "components": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "interfaces": [{"id": "i", "label": "I", "kind": "provided", "component": "ghost"}],
                "relations": []}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.interfaces[0].component", self.paths(result))

    def test_package_relation_kind_enum(self):
        spec = {"layout": "package",
                "packages": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "relations": [{"from": "a", "to": "b", "kind": "magic"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.relations[0].kind", self.paths(result))

    def test_object_link_refs(self):
        spec = {"layout": "object",
                "objects": [{"id": "a", "name": "x", "class": "C"}, {"id": "b", "name": "y"}],
                "links": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.links[0].to", self.paths(result))

    def test_composite_port_part_required(self):
        spec = {"layout": "composite",
                "parts": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "ports": [{"id": "p", "part": "ghost"}],
                "connectors": []}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.ports[0].part", self.paths(result))

    def test_profile_extension_refs(self):
        spec = {"layout": "profile",
                "stereotypes": [{"id": "s", "label": "S"}],
                "metaclasses": [{"id": "m", "label": "M"}],
                "extensions": [{"from": "s", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.extensions[0].to", self.paths(result))

    def test_valid_structure_specs(self):
        cases = [
            {"layout": "deployment",
             "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "kind": "device"}],
             "connections": [{"from": "a", "to": "b"}]},
            {"layout": "component",
             "components": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
             "interfaces": [{"id": "i", "label": "I", "kind": "provided", "component": "b"}],
             "relations": [{"from": "a", "to": "i", "kind": "assembly"}]},
            {"layout": "package",
             "packages": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "parent": "a"}],
             "relations": [{"from": "a", "to": "b", "kind": "import"}]},
            {"layout": "object",
             "objects": [{"id": "a", "name": "x", "class": "C"}, {"id": "b", "name": "y"}],
             "links": [{"from": "a", "to": "b"}]},
            {"layout": "composite",
             "parts": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
             "ports": [{"id": "p", "part": "a", "side": "right"}],
             "connectors": [{"from": "p", "to": "b"}]},
            {"layout": "profile",
             "stereotypes": [{"id": "s", "label": "S"}],
             "metaclasses": [{"id": "m", "label": "M"}],
             "extensions": [{"from": "s", "to": "m"}]},
        ]
        for spec in cases:
            self.assertTrue(renderer.validate_spec(spec)["ok"], spec["layout"])


class Behavior2ValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_communication_link_refs(self):
        spec = {"layout": "communication",
                "objects": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "links": [{"from": "a", "to": "ghost", "messages": ["m()"]}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.links[0].to", self.paths(result))

    def test_timing_message_refs(self):
        spec = {"layout": "timing",
                "lifelines": [{"id": "a", "label": "A", "states": ["x", "y"],
                               "events": [{"t": 0, "state": "x"}]}],
                "messages": [{"from": "a", "to": "ghost", "t": 1}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.messages[0].to", self.paths(result))

    def test_interaction_kind_enum_and_two_initials(self):
        spec = {"layout": "interaction",
                "nodes": [{"id": "s1", "kind": "initial"}, {"id": "s2", "kind": "initial"},
                          {"id": "a", "label": "A", "kind": "widget"}],
                "edges": []}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.nodes[2].kind", self.paths(result))
        self.assertIn("$.nodes", self.paths(result))

    def test_valid_behavior2_specs(self):
        cases = [
            {"layout": "communication",
             "objects": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
             "links": [{"from": "a", "to": "b", "messages": [{"label": "m()"}]}]},
            {"layout": "timing",
             "lifelines": [{"id": "a", "label": "A", "states": ["x", "y"],
                            "events": [{"t": 0, "state": "x"}, {"t": 2, "state": "y"}]}]},
            {"layout": "interaction",
             "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
             "edges": [{"from": "a", "to": "b"}]},
        ]
        for spec in cases:
            self.assertTrue(renderer.validate_spec(spec)["ok"], spec["layout"])


class OfficeDiagramValidateTest(unittest.TestCase):
    def paths(self, result):
        return [e["path"] for e in result["errors"]]

    def test_c4_kind_enum_and_boundary_refs(self):
        spec = {"layout": "c4",
                "elements": [{"id": "a", "label": "A", "kind": "widget", "boundary": "ghost"},
                             {"id": "b", "label": "B"}],
                "relations": [{"from": "a", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.elements[0].kind", self.paths(result))
        self.assertIn("$.elements[0].boundary", self.paths(result))
        self.assertIn("$.relations[0].to", self.paths(result))

    def test_gantt_task_requires_start(self):
        spec = {"layout": "gantt",
                "sections": [{"label": "S", "tasks": [{"label": "a", "kind": "magic"}]}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.sections[0].tasks[0].kind", self.paths(result))
        self.assertIn("$.sections[0].tasks[0].start", self.paths(result))

    def test_bpmn_element_kind_and_lane_refs(self):
        spec = {"layout": "bpmn",
                "pools": [{"label": "P", "lanes": [{"id": "l1", "label": "A"}]}],
                "elements": [{"id": "s", "kind": "widget", "lane": "ghost"},
                             {"id": "e", "kind": "end"}],
                "flows": [{"from": "s", "to": "ghost"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.elements[0].kind", self.paths(result))
        self.assertIn("$.elements[0].lane", self.paths(result))
        self.assertIn("$.flows[0].to", self.paths(result))

    def test_orgchart_parent_ref_and_root_required(self):
        spec = {"layout": "orgchart",
                "nodes": [{"id": "a", "label": "A", "parent": "ghost"},
                          {"id": "b", "label": "B"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.nodes[0].parent", self.paths(result))

    def test_mindmap_requires_root(self):
        result = renderer.validate_spec({"layout": "mindmap"})
        self.assertFalse(result["ok"])
        self.assertIn("$.root", self.paths(result))

    def test_timeline_side_enum(self):
        spec = {"layout": "timeline",
                "events": [{"label": "A", "side": "left"}, {"label": "B"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.events[0].side", self.paths(result))

    def test_fishbone_needs_two_categories(self):
        spec = {"layout": "fishbone", "problem": "P",
                "categories": [{"label": "only"}]}
        result = renderer.validate_spec(spec)
        self.assertFalse(result["ok"])
        self.assertIn("$.categories", self.paths(result))

    def test_valid_office_specs(self):
        cases = [
            {"layout": "c4",
             "elements": [{"id": "u", "label": "U", "kind": "person"},
                          {"id": "s", "label": "S", "kind": "system"}],
             "relations": [{"from": "u", "to": "s"}]},
            {"layout": "gantt",
             "sections": [{"label": "S", "tasks": [
                 {"label": "a", "start": "2026-08-01", "end": "2026-08-03"}]}]},
            {"layout": "bpmn",
             "elements": [{"id": "s", "kind": "start"}, {"id": "e", "kind": "end"}],
             "flows": [{"from": "s", "to": "e"}]},
            {"layout": "orgchart",
             "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "parent": "a"}]},
            {"layout": "mindmap",
             "root": {"label": "R", "children": [{"label": "A"}, {"label": "B"}]}},
            {"layout": "timeline", "events": [{"label": "A"}, {"label": "B"}]},
            {"layout": "fishbone", "problem": "P",
             "categories": [{"label": "a"}, {"label": "b"}]},
        ]
        for spec in cases:
            self.assertTrue(renderer.validate_spec(spec)["ok"], spec["layout"])


if __name__ == "__main__":
    unittest.main()
