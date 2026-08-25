"""Branch coverage for graph_model planners: malformed entries, id
collisions, self-loops, back edges, kind normalization, and layout-specific
edge cases the example specs never exercise.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gm = load_module("graph_model")


def plan(spec):
    """Build a plan without going through validation (planners must be
    robust to malformed input on their own)."""
    out = gm.build_plan(dict(spec))
    return out


class PanoramaGridBranchTest(unittest.TestCase):
    def test_single_card_padding(self):
        out = plan({"layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
                    "inputs": [{"label": "A"}], "steps": [{"label": "B"}],
                    "outputs": [{"label": "C"}],
                    "core": {"cards": [{"title": "only"}]},
                    "center_panel": {"title": "L", "cards": [{"title": "one"}]},
                    "legend": [{"color": "green", "label": "ok"}]})
        self.assertTrue(out)

    def test_grid_legend_and_padding(self):
        out = plan({"layout": "grid", "title": {"prefix": "X", "highlight": "Y"},
                    "cells": [{"title": "only"}], "legend": [{"color": "green", "label": "g"}]})
        self.assertTrue(out)


class SwimlaneBranchTest(unittest.TestCase):
    def test_unknown_connection_endpoints(self):
        out = plan({"layout": "swimlane", "title": {"prefix": "X", "highlight": "Y"},
                    "legend": [{"color": "green", "label": "g"}],
                    "lanes": [{"title": "L", "steps": [{"title": "A"}, {"title": "B"}]}],
                    "connections": [{"from": "ghost", "to": "A"}, {"from": "A", "to": "B"}]})
        self.assertTrue(out)


class GraphBranchTest(unittest.TestCase):
    def test_duplicate_ids_unknown_kind_circle_groups_legend(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy",
            "legend": [{"color": "green", "label": "g"}],
            "groups": ["not-a-dict", {"id": "g", "label": "G", "members": ["a"]}],
            "nodes": [
                {"id": "a", "kind": "wat"},
                {"id": "a", "kind": "circle"},
                {"id": "b"},
            ],
            "edges": [
                {"from": "a", "to": "a", "kind": "loop"},      # self loop
                {"from": "b", "to": "a", "kind": "loop"},      # back loop
                {"from": "a", "to": "b"},
            ],
        }
        out = plan(spec)
        self.assertTrue(out["graph_nodes"])

    def test_graph_same_layer_and_direction_branches(self):
        # direction right + same-layer edge + back edge exercise the elbow /
        # lane branches in the legacy engine.
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "right",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "c", "to": "b"},
                      {"from": "b", "to": "b"}],
        }
        out = plan(spec)
        self.assertTrue(out["graph_edges"])

    def test_elk_failure_falls_back_to_legacy(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        import sys
        fake_elk = mock.MagicMock()
        fake_elk.layout_graph.return_value = None
        with mock.patch.dict(sys.modules, {"elk_layout": fake_elk}):
            out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_nodes"])

    def test_elk_short_edge_points_fall_back(self):
        import sys
        fake_elk = mock.MagicMock()
        fake_elk.layout_graph.return_value = {
            "nodes": {"a": (0, 0, 100, 60), "b": (200, 0, 100, 60)},
            "edges": {"e0": [[0, 0]]},  # fewer than 2 points -> straight fallback
            "width": 400, "height": 200,
        }
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "elk",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b", "id": "e0"}],
        }
        with mock.patch.dict(sys.modules, {"elk_layout": fake_elk}):
            out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_edges"])


class SequenceBranchTest(unittest.TestCase):
    def test_fragments_dedup_and_self_activation(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "a"}, {"id": "b"}],
            "messages": [
                {"from": "a", "to": "b", "kind": "sync", "activate": True},
                {"from": "a", "to": "a", "kind": "self", "activate": True},
                {"from": "b", "to": "a", "kind": "return"},
            ],
            "fragments": [
                "not-a-dict",
                {"kind": "wat", "range": [0, 1]},
                {"kind": "alt", "range": "nope"},
                {"kind": "alt", "range": ["x", "y"]},
                {"kind": "alt", "range": [1, 1]},               # no message coverage
                {"kind": "alt", "range": [0, 2],
                 "dividers": ["x", {"at": "nope"}, {"at": 1}]},
            ],
        }
        out = plan(spec)
        self.assertTrue(out)

    def test_single_message_spacing(self):
        out = plan({"layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
                    "participants": [{"id": "a"}, {"id": "b"}],
                    "messages": [{"from": "a", "to": "b"}]})
        self.assertTrue(out)


class ErUsecaseClassBranchTest(unittest.TestCase):
    def test_er_branches(self):
        spec = {
            "layout": "er", "title": {"prefix": "X", "highlight": "Y"},
            "entities": [
                {"id": "a", "attributes": ["plain", {"name": "id", "key": "pk"}]},
                {"id": "a"},
                {"id": "b"},
            ],
            "relations": [
                "not-a-dict",
                {"from": "ghost", "to": "b"},
                {"from": "a", "to": "a"},   # self relation
                {"from": "a", "to": "b", "cardinality": "1:N"},
                {"from": "b", "to": "a"},
            ],
        }
        self.assertTrue(plan(spec))

    def test_usecase_branches(self):
        spec = {
            "layout": "usecase", "title": {"prefix": "X", "highlight": "Y"},
            "actors": [{"id": "u"}],
            "usecases": [{"id": "c"}],
            "links": ["x", {"from": "u", "to": "ghost"},
                      {"from": "u", "to": "c", "kind": "inherits"},
                      {"from": "u", "to": "c"}],
        }
        self.assertTrue(plan(spec))

    def test_class_branches(self):
        spec = {
            "layout": "class", "title": {"prefix": "X", "highlight": "Y"},
            "classes": [{"id": "a"}, {"id": "b"}],
            "relations": ["x", {"from": "a", "to": "ghost"},
                          {"from": "a", "to": "b", "kind": "inherits"}],
        }
        self.assertTrue(plan(spec))


class ActivityStateDfdBranchTest(unittest.TestCase):
    def test_activity_branches(self):
        spec = {
            "layout": "activity", "title": {"prefix": "X", "highlight": "Y"},
            "direction": "right",
            "nodes": [{"id": "_start"}, {"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": ["x", {"from": "a", "to": "ghost"},
                      {"from": "a", "to": "a"},
                      {"from": "b", "to": "a"},   # back edge
                      {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_activity_down_back_edge(self):
        spec = {
            "layout": "activity", "title": {"prefix": "X", "highlight": "Y"},
            "direction": "down",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        }
        self.assertTrue(plan(spec))

    def test_state_branches(self):
        spec = {
            "layout": "state", "title": {"prefix": "X", "highlight": "Y"},
            "states": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "transitions": ["x", {"from": "a", "to": "ghost"},
                            {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_dfd_branches(self):
        spec = {
            "layout": "dfd", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "kind": "process"}, {"id": "b", "kind": "store"}],
            "flows": ["x", {"from": "a", "to": "ghost"},
                      {"from": "a", "to": "a"},
                      {"from": "b", "to": "a"},   # back
                      {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))


class DeploymentComponentPackageBranchTest(unittest.TestCase):
    def test_deployment_branches(self):
        spec = {
            "layout": "deployment", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [
                {"id": "dev", "kind": "device"},
                {"id": "art", "kind": "artifact", "parent": "dev"},   # artifact parent reset
                {"id": "deep", "parent": "dev"},
                {"id": "deeper", "parent": "deep"},   # second nesting level -> flattened
            ],
            "connections": ["x", {"from": "dev", "to": "ghost"},
                            {"from": "dev", "to": "deep", "kind": "wireless"},
                            {"from": "dev", "to": "deep"}],
        }
        self.assertTrue(plan(spec))

    def test_component_branches(self):
        spec = {
            "layout": "component", "title": {"prefix": "X", "highlight": "Y"},
            "components": [{"id": "a"}, {"id": "b"}],
            "interfaces": ["x", {"id": "i0", "component": "ghost"},
                           {"id": "i1", "component": "a", "kind": "socket2"},
                           {"id": "i1", "component": "a"}],
            "relations": ["x", {"from": "a", "to": "ghost"},
                          {"from": "a", "to": "b", "kind": "glues"},
                          {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_package_branches(self):
        spec = {
            "layout": "package", "title": {"prefix": "X", "highlight": "Y"},
            "packages": [{"id": "a"}, {"id": "b", "parent": "a"}],
            "relations": ["x", {"from": "a", "to": "ghost"},
                          {"from": "a", "to": "b", "kind": "owns"},
                          {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))


class ObjectCompositeProfileBranchTest(unittest.TestCase):
    def test_object_branches(self):
        spec = {
            "layout": "object", "title": {"prefix": "X", "highlight": "Y"},
            "objects": [{"id": "a", "name": "A", "attributes": ["plain", {"name": "x", "value": 1}]},
                        {"id": "b", "name": "B"}],
            "links": ["x", {"from": "a", "to": "ghost"}, {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_composite_branches(self):
        spec = {
            "layout": "composite", "title": {"prefix": "X", "highlight": "Y"},
            "parts": [{"id": "a"}, {"id": "b"}],
            "ports": ["x", {"id": "p0", "part": "ghost"},
                      {"id": "p1", "part": "a", "side": "bottom"},
                      {"id": "p1", "part": "a", "side": "left"}],
            "connectors": ["x", {"from": "a", "to": "ghost"}, {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_profile_branches(self):
        spec = {
            "layout": "profile", "title": {"prefix": "X", "highlight": "Y"},
            "stereotypes": [{"id": "s"}], "metaclasses": [{"id": "m"}],
            "extensions": ["x", {"from": "s", "to": "m"}],
            "relations": ["x", {"from": "s", "to": "m"}],
        }
        self.assertTrue(plan(spec))


class CommunicationTimingInteractionBranchTest(unittest.TestCase):
    def test_communication_branches(self):
        spec = {
            "layout": "communication", "title": {"prefix": "X", "highlight": "Y"},
            "objects": [{"id": "a"}, {"id": "b"}],
            "links": ["x", {"from": "a", "to": "ghost"}, {"from": "a", "to": "a"},
                      {"from": "a", "to": "b",
                       "messages": ["plain string", {"num": "1", "label": "call()", "dir": "back"}]}],
        }
        self.assertTrue(plan(spec))

    def test_timing_branches(self):
        spec = {
            "layout": "timing", "title": {"prefix": "X", "highlight": "Y"},
            "lifelines": [
                {"id": "a", "events": ["x", {"t": "nope"},
                                          {"t": 0, "state": "idle"}, {"t": 5, "state": "busy"}]},
                {"id": "b"},   # no events -> default states/t range
            ],
            "messages": ["x", {"from": "a", "to": "ghost"}, {"from": "a", "to": "b", "t": "nope"},
                         {"from": "a", "to": "b", "t": 2, "label": "m"}],
        }
        self.assertTrue(plan(spec))

    def test_timing_no_events_at_all(self):
        spec = {
            "layout": "timing", "title": {"prefix": "X", "highlight": "Y"},
            "lifelines": [{"id": "a"}],
        }
        self.assertTrue(plan(spec))

    def test_interaction_branches(self):
        spec = {
            "layout": "interaction", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "_start", "label": "F"}, {"id": "a", "label": "A"}],
            "edges": ["x", {"from": "a", "to": "ghost"},
                      {"from": "a", "to": "a"},
                      {"from": "a", "to": "_start"},   # back edge
                      {"from": "_start", "to": "a"}],
        }
        self.assertTrue(plan(spec))


class C4GanttBpmnOrgchartBranchTest(unittest.TestCase):
    def test_c4_branches(self):
        spec = {
            "layout": "c4", "title": {"prefix": "X", "highlight": "Y"},
            "boundaries": [{"id": "empty", "label": "E"}],  # no members -> box None
            "elements": [{"id": "a"}, {"id": "b"}],
            "relations": ["x", {"from": "a", "to": "ghost"}, {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_gantt_branches(self):
        spec = {
            "layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
            "sections": [
                "x",
                {"label": "s", "tasks": [
                    "y",
                    {"label": "num", "start": 3, "duration": "weird"},
                    {"label": "baddate", "start": "not-a-date"},
                    {"label": "badkind", "start": 1, "end": 1, "kind": "warp"},
                    {"label": "ok", "start": "2026-08-01", "end": "2026-08-01"},  # end<=start
                ]},
            ],
        }
        self.assertTrue(plan(spec))

    def test_gantt_empty_and_single_day(self):
        spec = {"layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
                "sections": [{"label": "s", "tasks": [{"label": "t", "start": 0, "duration": 1}]}]}
        self.assertTrue(plan(spec))
        spec2 = {"layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
                 "sections": [{"label": "s"}]}
        self.assertTrue(plan(spec2))

    def test_bpmn_branches(self):
        spec = {
            "layout": "bpmn", "title": {"prefix": "X", "highlight": "Y"},
            "pools": ["x", {"id": "p", "label": "P"}],   # pool without lanes
            "elements": [{"id": "a", "kind": "start"}, {"id": "b", "kind": "task", "label": "T"}],
            "flows": ["x", {"from": "a", "to": "ghost"},
                      {"from": "a", "to": "b", "kind": "pigeon"},
                      {"from": "a", "to": "b"}],
        }
        self.assertTrue(plan(spec))

    def test_orgchart_cycle_and_depth(self):
        spec = {
            "layout": "orgchart", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [
                {"id": "root", "label": "R"},
                {"id": "x", "parent": "y"},   # cycle x<->y -> both become roots
                {"id": "y", "parent": "x"},
            ],
        }
        self.assertTrue(plan(spec))
        # deep nesting beyond depth 8 hits the measure/place depth guards
        deep = {"layout": "orgchart", "title": {"prefix": "X", "highlight": "Y"},
                "nodes": [{"id": "n0", "label": "0"}] + [
                    {"id": f"n{i}", "parent": f"n{i-1}"} for i in range(1, 12)]}
        self.assertTrue(plan(deep))


if __name__ == "__main__":
    unittest.main()
