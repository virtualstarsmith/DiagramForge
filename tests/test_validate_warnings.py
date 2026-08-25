"""Kitchen-sink warning/error branch coverage for validate_spec.

Each layout gets one deliberately broken spec that triggers many err/warn
branches at once (non-dict items, missing ids, duplicate ids, unknown kinds,
unknown accents, over-cap collections, dangling references, canvas ownership
warnings). Assertions check a representative sample; the coverage goal is
executing every branch.
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


rad = load_module("render_animated_diagram")
validate = staticmethod(rad.validate_spec)


def check(spec, expect_errors=(), expect_warnings=()):
    result = validate(spec)
    paths = {e["path"] for e in result["errors"]}
    wpaths = {w["path"] for w in result["warnings"]}
    for p in expect_errors:
        assert p in paths, f"expected error {p}; got {sorted(paths)}"
    for p in expect_warnings:
        assert p in wpaths, f"expected warning {p}; got {sorted(wpaths)}"
    return result


class CrossCuttingBranchTest(unittest.TestCase):
    def test_icon_size_and_legend_branches(self):
        # icon_size is validated wherever items carry icons; panorama requires
        # core.cards on top of inputs/steps/outputs.
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A", "icon": "gear", "icon_size": "giant"}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
            "core": {"cards": [{"title": "C1"}, {"title": "C2"}]},
        }
        check(spec, expect_errors=("$.inputs[0].icon_size",))
        # check_legend runs for the graph layout.
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "label": "A"}],
            "legend": "not-a-list",
        }
        check(spec, expect_errors=("$.legend",))
        spec["legend"] = ["not-a-dict", {"color": "banana", "label": "L" * 40}] + [
            {"color": "green", "label": f"L{i}"} for i in range(6)
        ]
        check(spec, expect_warnings=("$.legend[1].color", "$.legend[1].label", "$.legend"))

    def test_check_items_non_dict_empty_and_long(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": ["not-a-dict", {"label": ""}, {"label": "L" * 60}],
            "steps": [{"label": "B"}],
            "outputs": [{"label": "C"}],
        }
        check(spec, expect_errors=("$.inputs[0]",),
              expect_warnings=("$.inputs[1].label", "$.inputs[2].label"))

    def test_panorama_empty_panel_cards_warn(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A"}], "steps": [{"label": "B"}], "outputs": [{"label": "C"}],
            "left_panel": {"title": "L", "cards": []},
        }
        check(spec, expect_warnings=("$.left_panel.cards",))

    def test_title_must_be_object_and_highlight_length(self):
        spec = {"layout": "panorama", "title": "plain string",
                "inputs": [{"label": "A"}], "steps": [{"label": "B"}], "outputs": [{"label": "C"}]}
        check(spec, expect_errors=("$.title",))
        spec["title"] = {"prefix": "X", "highlight": "H" * 20}
        check(spec, expect_warnings=("$.title.highlight",))

    def test_output_icon_file_check(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A"}], "steps": [{"label": "B"}], "outputs": [{"label": "C"}],
            "output": {"icon_file": "definitely/missing/icon-file.png"},
        }
        r = validate(spec)
        paths = {e["path"] for e in result_errors(r)}
        assert "$.output.icon_file" in paths


def result_errors(r):
    return r["errors"]


class SwimlaneBranchTest(unittest.TestCase):
    def test_lane_subtitle_caption_accent_note_and_connections(self):
        spec = {
            "layout": "swimlane", "title": {"prefix": "X", "highlight": "Y"},
            "lanes": [{
                "title": "L", "subtitle": "s" * 61, "caption": "c" * 121, "accent": "banana",
                "steps": [{"title": "A", "note": "n" * 41}],
            }],
            "connections": "not-a-list",
        }
        check(spec, expect_errors=("$.connections",),
              expect_warnings=("$.lanes[0].subtitle", "$.lanes[0].caption",
                               "$.lanes[0].accent", "$.lanes[0].steps[0].note"))


class GraphBranchTest(unittest.TestCase):
    def test_node_and_edge_branches(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [
                "not-a-dict",
                {"label": "no id"},
                {"id": "a", "label": "A", "accent": "banana"},
                {"id": "b", "label": "B", "x": 10},          # x without y
                {"id": "c", "label": "C", "x": 950, "y": 180},  # signature zone
                {"id": "d", "label": "D", "x": 950, "y": 100},  # y < 117 title zone? (y<165)
            ],
            "edges": "not-a-list",
        }
        r = check(spec, expect_errors=("$.edges",),
                  expect_warnings=("$.nodes[1].id", "$.nodes[2].accent", "$.nodes[3]"))

    def test_edge_entry_branches(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [
                "not-a-dict",
                {"to": "b"},                        # missing from
                {"from": "a"},                      # missing to
                {"from": "a", "to": "ghost"},       # unknown endpoint
                {"from": "a", "to": "b", "kind": "wormhole"},
                {"from": "a", "to": "b", "accent": "banana"},
                {"from": "a", "to": "b", "label": "L" * 40},
            ],
        }
        check(spec, expect_errors=("$.edges[0]", "$.edges[1].from", "$.edges[2].to",
                                   "$.edges[3].to", "$.edges[4].kind"),
              expect_warnings=("$.edges[5].accent", "$.edges[6].label"))

    def test_edges_over_cap_warns(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}] * 41,
        }
        check(spec, expect_warnings=("$.edges",))


class SequenceBranchTest(unittest.TestCase):
    def test_participant_and_message_branches(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [
                "not-a-dict",
                {"label": "no id"},
                {"id": "a", "label": "A", "kind": "robot", "accent": "banana"},
                {"id": "a", "label": "A2"},
            ],
            "messages": "not-a-list",
        }
        check(spec, expect_errors=("$.participants[1].id", "$.participants[2].kind",
                                   "$.participants[3].id", "$.messages"),
              expect_warnings=("$.participants[2].accent",))

    def test_message_entry_branches(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [
                "not-a-dict",
                {"from": "a", "to": "b", "kind": "note"},                    # note no text/target
                {"from": "a", "to": "b", "kind": "note", "text": "t", "target": ["a", "b", "a"]},
                {"to": "b", "kind": "sync"},                                 # missing from
                {"from": "ghost", "to": "b", "kind": "sync"},                # unknown participant
                {"from": "a", "to": "b", "kind": "self", "label": "x"},      # self w/ different to
                {"from": "a", "to": "b", "kind": "sync", "label": "L" * 31},
                {"from": "a", "to": "a", "kind": "self", "activate": True},
            ],
        }
        check(spec, expect_errors=("$.messages[0]", "$.messages[1].target", "$.messages[3].from",
                                   "$.messages[4].from"),
              expect_warnings=("$.messages[1].text", "$.messages[2].target",
                               "$.messages[5].to", "$.messages[6].label"))

    def test_messages_over_cap_and_empty(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b"}] * 31,
        }
        check(spec, expect_warnings=("$.messages",))

    def test_fragment_branches(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b", "kind": "sync", "activate": True}] * 6,
            "fragments": "not-a-list",
        }
        check(spec, expect_errors=("$.fragments",))
        spec["fragments"] = [
            "not-a-dict",
            {"kind": "wormhole", "range": [0, 1]},
            {"kind": "alt", "range": "bad"},
            {"kind": "alt", "range": [0, 3], "dividers": "not-a-list"},
            {"kind": "alt", "range": [0, 3], "dividers": [{"at": "x"}, {"at": 0}]},
            {"kind": "loop", "range": [0, 2], "dividers": [{"at": 1}]},
        ] + [{"kind": "alt", "range": [0, 1]} for _ in range(3)]
        check(spec, expect_errors=("$.fragments[0]", "$.fragments[1].kind",
                                   "$.fragments[2].range", "$.fragments[3].dividers",
                                   "$.fragments[4].dividers[0]", "$.fragments[4].dividers[1].at"),
              expect_warnings=("$.fragments[5].dividers", "$.fragments"))

    def test_fragment_nesting_depth(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b", "kind": "sync"}] * 6,
            "fragments": [
                {"kind": "alt", "range": [0, 5]},
                {"kind": "loop", "range": [1, 4]},
                {"kind": "alt", "range": [2, 3]},
                {"kind": "opt", "range": [2, 3]},
            ],
        }
        r = validate(spec)
        assert any("nested deeper" in e["message"] for e in r["errors"]), r["errors"]


class ErBranchTest(unittest.TestCase):
    def test_entity_and_relation_branches(self):
        spec = {
            "layout": "er", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "entities": [
                "not-a-dict",
                {"attributes": []},
                {"id": "e", "attributes": "not-a-list"},
                {"id": "e", "accent": "banana"},
                {"id": "f", "attributes": ["a"] * 9},
                {"id": "g", "attributes": [42, {"name": "k", "key": "sk"}]},
            ],
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.entities[1].id", "$.entities[2].attributes",
                                   "$.entities[3].id", "$.entities[5].attributes[0]",
                                   "$.entities[5].attributes[1].key", "$.relations"),
              expect_warnings=("$.entities[3].accent", "$.entities[4].attributes", "$.canvas"))

    def test_relation_entry_branches(self):
        spec = {
            "layout": "er", "title": {"prefix": "X", "highlight": "Y"},
            "entities": [{"id": "a"}, {"id": "b"}],
            "relations": [
                "not-a-dict",
                {"to": "b"},
                {"from": "a", "to": "ghost"},
                {"from": "a", "to": "b", "cardinality": "X:Y"},
            ],
        }
        check(spec, expect_errors=("$.relations[0]", "$.relations[1].from",
                                   "$.relations[2].to", "$.relations[3].cardinality"))
        spec["relations"] = [{"from": "a", "to": "b"}] * 17
        check(spec, expect_warnings=("$.relations",))


class UsecaseBranchTest(unittest.TestCase):
    def test_actor_usecase_link_branches(self):
        spec = {
            "layout": "usecase", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"height": 700},
            "actors": [{"id": "u", "side": "middle"}],
            "usecases": [{"id": "c"}],
            "links": "not-a-list",
        }
        check(spec, expect_errors=("$.actors[0].side", "$.links"),
              expect_warnings=("$.canvas",))

    def test_link_entry_branches(self):
        spec = {
            "layout": "usecase", "title": {"prefix": "X", "highlight": "Y"},
            "actors": [{"id": "u"}],
            "usecases": [{"id": "c"}],
            "links": [
                "not-a-dict",
                {"to": "c"},
                {"from": "u", "to": "ghost"},
                {"from": "u", "to": "c", "kind": "inherits"},
                {"from": "u", "to": "c", "kind": "include"},
            ],
        }
        check(spec, expect_errors=("$.links[0]", "$.links[1].from", "$.links[2].to",
                                   "$.links[3].kind"),
              expect_warnings=("$.links[4].kind",))
        spec["links"] = [{"from": "u", "to": "c"}] * 25
        check(spec, expect_warnings=("$.links",))


class ClassBranchTest(unittest.TestCase):
    def test_class_member_relation_branches(self):
        spec = {
            "layout": "class", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "classes": [
                "not-a-dict",
                {},
                {"id": "c", "attributes": "not-a-list"},
                {"id": "c", "accent": "banana"},
                {"id": "d", "methods": ["m"] * 13},
            ],
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.classes[1].id", "$.classes[2].attributes",
                                   "$.classes[3].id", "$.relations"),
              expect_warnings=("$.classes[3].accent", "$.classes[4].methods", "$.canvas"))

    def test_relation_entry_branches(self):
        spec = {
            "layout": "class", "title": {"prefix": "X", "highlight": "Y"},
            "classes": [{"id": "a"}, {"id": "b"}],
            "relations": [
                "not-a-dict",
                {"to": "b"},
                {"from": "a", "to": "ghost"},
                {"from": "a", "to": "b", "kind": "marries"},
            ],
        }
        check(spec, expect_errors=("$.relations[0]", "$.relations[1].from",
                                   "$.relations[2].to", "$.relations[3].kind"))
        spec["relations"] = [{"from": "a", "to": "b"}] * 17
        check(spec, expect_warnings=("$.relations",))


class ActivityBranchTest(unittest.TestCase):
    def test_activity_branches(self):
        spec = {
            "layout": "activity", "title": {"prefix": "X", "highlight": "Y"},
            "direction": "sideways",
            "canvas": {"width": 900},
            "nodes": [
                "not-a-dict",
                {"kind": "teleport"},
                {"id": "a", "kind": "action"},
                {"id": "a"},
                {"id": "i", "kind": "initial", "label": "ignored"},
            ],
            "edges": "not-a-list",
        }
        check(spec, expect_errors=("$.direction", "$.nodes[1].kind", "$.nodes[3].id", "$.edges"),
              expect_warnings=("$.nodes[2].label", "$.nodes[4].label", "$.canvas"))

    def test_activity_edge_entries_and_caps(self):
        spec = {
            "layout": "activity", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "kind": "action", "label": "A"}] * 25,
            "edges": ["x", {"to": "a"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "a"}] * 40,
        }
        check(spec, expect_errors=("$.edges[0]", "$.edges[1].from", "$.edges[2].to"),
              expect_warnings=("$.nodes", "$.edges"))


class StateBranchTest(unittest.TestCase):
    def test_state_branches(self):
        spec = {
            "layout": "state", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "states": [
                "not-a-dict",
                {"label": "no id, long label here"},
                {"id": "s", "kind": "state"},
                {"id": "s"},
                {"id": "i1", "kind": "initial", "label": "ignored"},
                {"id": "i2", "kind": "initial"},
                {"id": "t", "accent": "banana"},
            ],
            "transitions": "not-a-list",
        }
        check(spec, expect_errors=("$.states[1].id", "$.states[3].id", "$.transitions"),
              expect_warnings=("$.states[1].label", "$.states[2].label", "$.states[4]",
                               "$.states[6].accent", "$.canvas"))

    def test_transition_entries_and_caps(self):
        spec = {
            "layout": "state", "title": {"prefix": "X", "highlight": "Y"},
            "states": [{"id": "a", "label": f"S{i}"} for i, a in enumerate(["a"] * 21)],
            "transitions": ["x", {"to": "a"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "a"}] * 30,
        }
        check(spec, expect_errors=("$.transitions[0]", "$.transitions[1].from",
                                   "$.transitions[2].to"),
              expect_warnings=("$.states", "$.transitions"))


class DfdBranchTest(unittest.TestCase):
    def test_dfd_branches(self):
        spec = {
            "layout": "dfd", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "nodes": [
                "not-a-dict",
                {"kind": "vortex"},
                {"label": "no id"},
                {"id": "a"},
                {"id": "a"},
                {"id": "b", "accent": "banana"},
            ],
            "flows": "not-a-list",
        }
        check(spec, expect_errors=("$.nodes[1].kind", "$.nodes[2].id", "$.nodes[4].id",
                                   "$.flows"),
              expect_warnings=("$.nodes[5].accent", "$.canvas"))

    def test_flow_entries_and_caps(self):
        spec = {
            "layout": "dfd", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a"}, {"id": "b"}],
            "flows": ["x", {"to": "b"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 30,
        }
        check(spec, expect_errors=("$.flows[0]", "$.flows[1].from", "$.flows[2].to"),
              expect_warnings=("$.flows",))


class DeploymentBranchTest(unittest.TestCase):
    def test_deployment_branches(self):
        spec = {
            "layout": "deployment", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "nodes": [
                "not-a-dict",
                {"kind": "cloud"},
                {"label": "no id"},
                {"id": "a"},
                {"id": "a"},
                {"id": "b", "parent": "ghost"},
                {"id": "c", "accent": "banana"},
            ],
            "connections": "not-a-list",
        }
        check(spec, expect_errors=("$.nodes[1].kind", "$.nodes[2].id", "$.nodes[4].id",
                                   "$.nodes[5].parent", "$.connections"),
              expect_warnings=("$.nodes[6].accent", "$.canvas"))

    def test_connection_entries_and_caps(self):
        spec = {
            "layout": "deployment", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a"}, {"id": "b"}],
            "connections": ["x", {"to": "b", "kind": "telepathy"},
                            {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 20,
        }
        check(spec, expect_errors=("$.connections[0]", "$.connections[1].from",
                                   "$.connections[1].kind", "$.connections[2].to"),
              expect_warnings=("$.connections",))


class ComponentBranchTest(unittest.TestCase):
    def test_component_branches(self):
        spec = {
            "layout": "component", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "components": ["not-a-dict", {}, {"id": "c"}, {"id": "c"}],
            "interfaces": "not-a-list",
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.components[1].id", "$.components[3].id",
                                   "$.interfaces", "$.relations"),
              expect_warnings=("$.canvas",))

    def test_interface_and_relation_entries(self):
        spec = {
            "layout": "component", "title": {"prefix": "X", "highlight": "Y"},
            "components": [{"id": "a"}, {"id": "b"}],
            "interfaces": ["x", {"id": "i1", "kind": "socket2", "component": "a"}] + [
                {"id": f"i{n}", "component": "a"} for n in range(12)],
            "relations": [
                "not-a-dict",
                {"to": "b", "kind": "glues"},
                {"from": "a", "to": "ghost"},
            ] + [{"from": "a", "to": "b"}] * 16,
        }
        check(spec, expect_errors=("$.interfaces[1].kind", "$.relations[0]",
                                   "$.relations[1].kind", "$.relations[2].to"),
              expect_warnings=("$.interfaces", "$.relations"))


class PackageBranchTest(unittest.TestCase):
    def test_package_branches(self):
        spec = {
            "layout": "package", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "packages": ["not-a-dict", {}, {"id": "p"}, {"id": "p"}, {"id": "q", "parent": "ghost"}],
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.packages[1].id", "$.packages[3].id",
                                   "$.packages[4].parent", "$.relations"),
              expect_warnings=("$.canvas",))

    def test_relation_entries(self):
        spec = {
            "layout": "package", "title": {"prefix": "X", "highlight": "Y"},
            "packages": [{"id": "a"}, {"id": "b"}],
            "relations": ["x", {"to": "b", "kind": "owns"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 16,
        }
        check(spec, expect_errors=("$.relations[0]", "$.relations[1].kind",
                                   "$.relations[2].to"),
              expect_warnings=("$.relations",))


class ObjectBranchTest(unittest.TestCase):
    def test_object_branches(self):
        spec = {
            "layout": "object", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "objects": "not-a-list",
            "links": "not-a-list",
        }
        check(spec, expect_errors=("$.objects", "$.links"))
        spec["objects"] = ["x", {}, {"id": "o"}, {"id": "o"}, {"id": "p"}] + [
            {"id": f"n{i}", "name": "x"} for i in range(8)]
        check(spec, expect_errors=("$.objects[0]", "$.objects[1].id", "$.objects[3].id"),
              expect_warnings=("$.objects[1].name", "$.objects", "$.canvas"))

    def test_link_entries(self):
        spec = {
            "layout": "object", "title": {"prefix": "X", "highlight": "Y"},
            "objects": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "links": ["x", {"to": "b"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 16,
        }
        check(spec, expect_errors=("$.links[0]", "$.links[1].from", "$.links[2].to"),
              expect_warnings=("$.links",))


class CompositeBranchTest(unittest.TestCase):
    def test_composite_branches(self):
        spec = {
            "layout": "composite", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "parts": ["x", {}, {"id": "p"}, {"id": "p"}],
            "ports": "not-a-list",
            "connectors": "not-a-list",
        }
        check(spec, expect_errors=("$.parts[1].id", "$.parts[3].id", "$.ports", "$.connectors"),
              expect_warnings=("$.canvas",))

    def test_port_and_connector_entries(self):
        spec = {
            "layout": "composite", "title": {"prefix": "X", "highlight": "Y"},
            "parts": [{"id": "a"}, {"id": "b"}],
            "ports": ["x", {"id": "po", "part": "ghost"}, {"part": "a", "side": "inside"}] + [
                {"part": "a"} for _ in range(12)],
            "connectors": ["x", {"to": "b"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 16,
        }
        check(spec, expect_errors=("$.ports[1].part", "$.ports[2].side",
                                   "$.connectors[0]", "$.connectors[1].from",
                                   "$.connectors[2].to"),
              expect_warnings=("$.ports", "$.connectors"))


class ProfileBranchTest(unittest.TestCase):
    def test_profile_branches(self):
        spec = {
            "layout": "profile", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "stereotypes": "not-a-list",
            "metaclasses": ["x", {}, {"id": "m"}, {"id": "m"}] + [
                {"id": f"m{i}"} for i in range(9)],
            "extensions": "not-a-list",
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.stereotypes", "$.metaclasses[1].id",
                                   "$.metaclasses[3].id", "$.extensions", "$.relations"),
              expect_warnings=("$.metaclasses", "$.canvas"))

    def test_profile_relation_entries(self):
        spec = {
            "layout": "profile", "title": {"prefix": "X", "highlight": "Y"},
            "stereotypes": [{"id": "s"}], "metaclasses": [{"id": "m"}],
            "extensions": ["x", {"to": "m"}, {"from": "s", "to": "ghost"}] + [
                {"from": "s", "to": "m"}] * 12,
        }
        check(spec, expect_errors=("$.extensions[1].from", "$.extensions[2].to"),
              expect_warnings=("$.extensions",))


class CommunicationBranchTest(unittest.TestCase):
    def test_communication_branches(self):
        spec = {
            "layout": "communication", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "objects": ["x", {}, {"id": "o"}, {"id": "o"}],
            "links": "not-a-list",
        }
        check(spec, expect_errors=("$.objects[1].id", "$.objects[3].id", "$.links"),
              expect_warnings=("$.canvas",))

    def test_link_and_message_entries(self):
        spec = {
            "layout": "communication", "title": {"prefix": "X", "highlight": "Y"},
            "objects": [{"id": "a"}, {"id": "b"}],
            "links": [
                "x",
                {"to": "b"},
                {"from": "a", "to": "ghost"},
                {"from": "a", "to": "b", "messages": "not-a-list"},
                {"from": "a", "to": "b", "messages": [{"num": str(i)} for i in range(7)]},
            ] + [{"from": "a", "to": "b"}] * 20,
        }
        check(spec, expect_errors=("$.links[0]", "$.links[1].from", "$.links[2].to",
                                   "$.links[3].messages"),
              expect_warnings=("$.links[4].messages", "$.links"))


class TimingBranchTest(unittest.TestCase):
    def test_timing_branches(self):
        spec = {
            "layout": "timing", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "lifelines": "not-a-list",
            "messages": "not-a-list",
        }
        check(spec, expect_errors=("$.lifelines", "$.messages"))
        spec["lifelines"] = ["x", {}, {"id": "l"}, {"id": "l"},
                             {"id": "e", "events": [], "states": [{"t": i} for i in range(6)]}]
        check(spec, expect_errors=("$.lifelines[1].id", "$.lifelines[3].id"),
              expect_warnings=("$.lifelines[4].events", "$.lifelines[4].states", "$.canvas"))

    def test_timing_message_entries(self):
        spec = {
            "layout": "timing", "title": {"prefix": "X", "highlight": "Y"},
            "lifelines": [{"id": "a", "events": [{"t": 0}]}] * 6,
            "messages": ["x", {"to": "a"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "a"}] * 10,
        }
        check(spec, expect_errors=("$.messages[1].from", "$.messages[2].to"),
              expect_warnings=("$.lifelines", "$.messages"))


class InteractionBranchTest(unittest.TestCase):
    def test_interaction_branches(self):
        spec = {
            "layout": "interaction", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "nodes": "not-a-list",
            "edges": "not-a-list",
        }
        check(spec, expect_errors=("$.nodes", "$.edges"))
        spec["nodes"] = ["x", {"kind": "interaction"}, {"id": "i", "ref": "bogus"},
                         {"id": "i"}, {"id": "a", "kind": "initial"}, {"id": "b", "kind": "initial"}]
        check(spec, expect_errors=("$.nodes[3].id", "$.nodes"),
              expect_warnings=("$.nodes[1].label", "$.nodes[2].ref", "$.canvas"))

    def test_interaction_edge_entries(self):
        spec = {
            "layout": "interaction", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": f"n{i}", "label": "x"} for i in range(17)],
            "edges": ["x", {"to": "n0"}, {"from": "n0", "to": "ghost"}] + [
                {"from": "n0", "to": "n1"}] * 24,
        }
        check(spec, expect_errors=("$.edges[0]", "$.edges[1].from", "$.edges[2].to"),
              expect_warnings=("$.nodes", "$.edges"))


class C4BranchTest(unittest.TestCase):
    def test_c4_branches(self):
        spec = {
            "layout": "c4", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "elements": ["x", {"kind": "galaxy"}, {}, {"id": "e"}, {"id": "e"}],
            "boundaries": "not-a-list",
            "relations": "not-a-list",
        }
        check(spec, expect_errors=("$.elements[1].kind", "$.elements[2].id",
                                   "$.elements[4].id", "$.boundaries", "$.relations"),
              expect_warnings=("$.canvas",))

    def test_boundary_and_relation_entries(self):
        spec = {
            "layout": "c4", "title": {"prefix": "X", "highlight": "Y"},
            "elements": [{"id": "a"}, {"id": "b"}],
            "boundaries": [{}, {"id": "b1"}] + [{"id": f"b{i}"} for i in range(4)],
            "relations": ["x", {"to": "b"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 20,
        }
        check(spec, expect_errors=("$.boundaries[0].id", "$.relations[0]",
                                   "$.relations[1].from", "$.relations[2].to"),
              expect_warnings=("$.boundaries", "$.relations"))


class GanttBranchTest(unittest.TestCase):
    def test_gantt_branches(self):
        spec = {
            "layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "sections": "not-a-list",
        }
        check(spec, expect_errors=("$.sections",))
        spec["sections"] = [
            "x",
            {"label": "empty", "tasks": []},
            {"label": "big", "tasks": [{"label": f"t{i}"} for i in range(11)]},
            {"label": "bad", "tasks": [{"label": ""}, {"label": "x", "kind": "warp"},
                                        {"label": "y", "start": "not-a-date"}]},
        ] + [{"label": f"s{i}", "tasks": [{"label": "t"}]} for i in range(8)]
        check(spec, expect_errors=("$.sections[3].tasks[1].kind",),
              expect_warnings=("$.sections", "$.sections[1].tasks", "$.sections[2].tasks",
                               "$.sections[3].tasks[0].label", "$.canvas"))

    def test_gantt_total_tasks_warn(self):
        spec = {
            "layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
            "sections": [{"label": f"s{i}", "tasks": [{"label": f"t{j}"} for j in range(8)]}
                         for i in range(4)],
        }
        check(spec, expect_warnings=("$.sections",))


class BpmnBranchTest(unittest.TestCase):
    def test_bpmn_branches(self):
        spec = {
            "layout": "bpmn", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "pools": "not-a-list",
            "elements": "not-a-list",
            "flows": "not-a-list",
        }
        check(spec, expect_errors=("$.pools", "$.elements", "$.flows"))
        spec["pools"] = [{"lanes": [{"id": "l1"}, "x"]}] * 4
        spec["elements"] = ["x", {"kind": "blackhole"}, {}, {"id": "e"}, {"id": "e"}]
        check(spec, expect_errors=("$.elements[1].kind", "$.elements[2].id", "$.elements[4].id"),
              expect_warnings=("$.pools", "$.canvas"))

    def test_bpmn_flow_entries(self):
        spec = {
            "layout": "bpmn", "title": {"prefix": "X", "highlight": "Y"},
            "elements": [{"id": "a"}, {"id": "b"}],
            "flows": ["x", {"to": "b", "kind": "pigeon"}, {"from": "a", "to": "ghost"}] + [
                {"from": "a", "to": "b"}] * 30,
        }
        check(spec, expect_errors=("$.flows[0]", "$.flows[1].kind", "$.flows[2].to"),
              expect_warnings=("$.flows",))


class OrgchartMindmapTimelineFishboneTest(unittest.TestCase):
    def test_orgchart_branches(self):
        spec = {
            "layout": "orgchart", "title": {"prefix": "X", "highlight": "Y"},
            "canvas": {"width": 900},
            "nodes": ["x", {}, {"id": "o"}, {"id": "o"}, {"id": "p", "parent": "ghost"},
                      {"id": "q", "parent": "r"}, {"id": "r", "parent": "q"}],
        }
        check(spec, expect_errors=("$.nodes[1].id", "$.nodes[3].id", "$.nodes[4].parent"),
              expect_warnings=("$.canvas",))

    def test_orgchart_no_root(self):
        spec = {
            "layout": "orgchart", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}],
        }
        r = validate(spec)
        assert any("no root" in e["message"] for e in r["errors"]), r["errors"]

    def test_mindmap_branches(self):
        spec = {"layout": "mindmap", "title": {"prefix": "X", "highlight": "Y"},
                "canvas": {"width": 900}}
        check(spec, expect_errors=("$.root",))
        spec["root"] = {"label": ""}
        check(spec, expect_warnings=("$.root.label", "$.root.children", "$.canvas"))
        spec["root"] = {"label": "R", "children": "nope"}
        check(spec, expect_errors=("$.root.children",))
        spec["root"] = {"label": "R", "children": [{"label": "only"}]}
        check(spec, expect_warnings=("$.root.children",))
        spec["root"] = {"label": "R", "children": [
            "x", {"label": "t", "children": [{"label": f"l{i}"} for i in range(6)]}
        ] + [{"label": f"t{i}"} for i in range(10)]}
        check(spec, expect_warnings=("$.root.children[1].children", "$.root.children"))

    def test_timeline_branches(self):
        spec = {"layout": "timeline", "title": {"prefix": "X", "highlight": "Y"},
                "canvas": {"width": 900}}
        check(spec, expect_errors=("$.events",), expect_warnings=("$.canvas",))
        spec["events"] = [{"label": "a"}, {"label": "b", "side": "sideways"}]
        check(spec, expect_errors=("$.events[1].side",))

    def test_fishbone_branches(self):
        spec = {"layout": "fishbone", "title": {"prefix": "X", "highlight": "Y"},
                "canvas": {"width": 900}}
        check(spec, expect_errors=("$.categories",),
              expect_warnings=("$.problem", "$.canvas"))
        spec["categories"] = "not-a-list"
        check(spec, expect_errors=("$.categories",))
        spec["categories"] = [{"label": "one"}]
        check(spec, expect_errors=("$.categories",))
        spec["problem"] = "P"
        spec["categories"] = ["x", {"causes": []},
                              {"label": "c", "causes": [f"c{i}" for i in range(6)]}
                              ] + [{"label": f"c{i}"} for i in range(5)]
        check(spec, expect_warnings=("$.categories[1].label", "$.categories[2].causes",
                                     "$.categories"))


if __name__ == "__main__":
    unittest.main()


class ValidateIconAndGraphLeftoversTest(unittest.TestCase):
    def test_icon_style_and_motion_errors(self):
        spec = {"layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
                "inputs": [{"label": "A", "icon": "gear", "icon_style": "neon",
                            "icon_motion": "wormhole"}],
                "steps": [{"label": "B"}], "outputs": [{"label": "C"}]}
        errors = [e["path"] for e in validate(spec)["errors"]]
        assert "$.inputs[0].icon_style" in errors
        assert "$.inputs[0].icon_motion" in errors

    def test_graph_direction_and_node_branches(self):
        spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                "direction": "sideways",
                "nodes": [{"id": "a"}, {"id": "a"}, {"id": "b", "kind": "wat"}]}
        errors = [e["path"] for e in validate(spec)["errors"]]
        assert "$.direction" in errors
        assert "$.nodes[1].id" in errors
        assert "$.nodes[2].kind" in errors

    def test_graph_long_right_chain_warns(self):
        spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                "direction": "right",
                "nodes": [{"id": f"n{i}"} for i in range(9)],
                "edges": [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(8)]}
        warnings = [w["path"] for w in validate(spec)["warnings"]]
        assert "$.direction" in warnings
