# -*- coding: utf-8 -*-
"""Tests for the replication-driven feature batch (2026-08):

- swimlane capacity 8x8, spec-driven canvas width, caption rows, vertical fill
- grid layout planning + validation
- graph nested group boxes ("groups" + node "parent")
- edge badges, circle nodes, amber accents, legends, pinned-zone warnings
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


graph_model = _load("graph_model", "scripts/graph_model.py")
renderer = _load("render_animated_diagram", "scripts/render_animated_diagram.py")


def _lane(i, steps=3):
    return {"title": f"Lane {i}", "steps": [{"id": f"l{i}s{j}", "title": f"S{j}"} for j in range(steps)]}


class SwimlaneCapacityTest(unittest.TestCase):
    def test_eight_lanes_all_render(self):
        spec = {"layout": "swimlane", "lanes": [_lane(i) for i in range(8)]}
        plan = graph_model.build_plan(spec)
        groups = [n for n in plan["nodes"] if n["kind"] == "group"]
        self.assertEqual(len(groups), 8)

    def test_ninth_lane_dropped_with_named_warning(self):
        spec = {"layout": "swimlane", "lanes": [_lane(i) for i in range(9)]}
        result = renderer.validate_spec(spec)
        self.assertTrue(result["ok"])
        msgs = [w["message"] for w in result["warnings"] if w["path"] == "$.lanes"]
        self.assertTrue(any("Lane 8" in m for m in msgs), msgs)

    def test_seven_steps_all_render(self):
        spec = {"layout": "swimlane", "lanes": [_lane(0, 7), _lane(1, 2)]}
        plan = graph_model.build_plan(spec)
        lane0 = plan["lanes"]["items"][0]
        self.assertEqual(len(lane0["steps"]), 7)


class SwimlaneCanvasTest(unittest.TestCase):
    def test_spec_width_flows_into_planner(self):
        spec = {"layout": "swimlane", "canvas": {"width": 900}, "lanes": [_lane(0), _lane(1)]}
        plan = graph_model.build_plan(spec)
        self.assertEqual(plan["canvas"]["width"], 900)
        self.assertEqual(plan["lanes"]["w"], 900 - 110)
        rightmost = max(n["x"] + n["w"] for n in plan["nodes"])
        self.assertLessEqual(rightmost, 900 - 40)

    def test_caption_grows_lane_height(self):
        base = graph_model.build_plan({"layout": "swimlane", "lanes": [_lane(0), _lane(1)]})
        cap = graph_model.build_plan({"layout": "swimlane", "lanes": [
            dict(_lane(0), caption="a caption row"), _lane(1)]})
        self.assertEqual(cap["lanes"]["items"][0]["_h"], base["lanes"]["items"][0]["_h"] + 26)

    def test_taller_spec_canvas_fills_vertically(self):
        spec = {"layout": "swimlane", "canvas": {"height": 1600}, "lanes": [_lane(0), _lane(1), _lane(2)]}
        plan = graph_model.build_plan(spec)
        natural = graph_model.build_plan({"layout": "swimlane", "lanes": [_lane(0), _lane(1), _lane(2)]})
        self.assertGreater(plan["canvas"]["height"], natural["canvas"]["height"])
        self.assertLessEqual(plan["canvas"]["height"], 1600)

    def test_step_note_grows_lane_height(self):
        noted = graph_model.build_plan({"layout": "swimlane", "lanes": [
            {"title": "A", "steps": [{"id": "a", "title": "a", "note": "reuse"}]}, _lane(1)]})
        plain = graph_model.build_plan({"layout": "swimlane", "lanes": [_lane(0), _lane(1)]})
        self.assertEqual(noted["lanes"]["items"][0]["_h"], plain["lanes"]["items"][0]["_h"] + 16)


class GridLayoutTest(unittest.TestCase):
    def _cells(self, n, steps=4):
        return {"layout": "grid", "cells": [
            {"title": f"C{i}", "steps": [{"title": f"s{j}"} for j in range(steps)]} for i in range(n)]}

    def test_eight_cells_three_columns_centered_last_row(self):
        plan = graph_model.build_plan(self._cells(8))
        self.assertEqual(plan["layout"], "grid")
        self.assertEqual(plan["grid"]["columns"], 3)
        items = plan["grid"]["items"]
        last_row = [c for c in items if c["_box"][1] == items[-1]["_box"][1]]
        self.assertEqual(len(last_row), 2)
        # centered: first cell of the short row starts right of the full rows
        first_row_x = min(c["_box"][0] for c in items if c["_box"][1] == items[0]["_box"][1])
        self.assertGreater(last_row[0]["_box"][0], first_row_x)

    def test_validation_columns_and_capacity(self):
        bad = renderer.validate_spec(dict(self._cells(3), columns=4))
        self.assertFalse(bad["ok"])
        many = renderer.validate_spec(self._cells(10))
        self.assertTrue(any("C9" in w["message"] for w in many["warnings"]))

    def test_missing_cells_is_error(self):
        self.assertFalse(renderer.validate_spec({"layout": "grid"})["ok"])


class GraphGroupsTest(unittest.TestCase):
    def _spec(self):
        return {"layout": "graph",
                "nodes": [{"id": "a", "label": "A", "x": 300, "y": 300},
                          {"id": "b", "label": "B", "x": 500, "y": 300},
                          {"id": "c", "label": "C", "x": 500, "y": 450}],
                "edges": [{"from": "a", "to": "b"}],
                "groups": [{"id": "g1", "label": "Tiers"}]}

    def test_group_box_wraps_members(self):
        spec = self._spec()
        spec["nodes"][1]["parent"] = "g1"
        spec["nodes"][2]["parent"] = "g1"
        plan = graph_model.build_plan(spec)
        self.assertEqual(len(plan["graph_groups"]), 1)
        box = plan["graph_groups"][0]["box"]
        bx = [n["_box"] for n in plan["graph_nodes"] if n["id"] in ("b", "c")]
        self.assertLessEqual(box[0], min(b[0] for b in bx))
        self.assertGreaterEqual(box[1] + box[3], max(b[1] + b[3] for b in bx))

    def test_unknown_parent_is_error(self):
        spec = self._spec()
        spec["nodes"][1]["parent"] = "nope"
        self.assertFalse(renderer.validate_spec(spec)["ok"])

    def test_unreferenced_group_renders_nothing(self):
        plan = graph_model.build_plan(self._spec())
        self.assertEqual(plan["graph_groups"], [])


class EdgeBadgeTest(unittest.TestCase):
    def test_swimlane_badge_passthrough(self):
        spec = {"layout": "swimlane", "lanes": [_lane(0), _lane(1)],
                "connections": [{"from": "l0s0", "to": "l0s1", "badge": "1"}]}
        plan = graph_model.build_plan(spec)
        self.assertEqual(plan["edges"][0].get("badge"), "1")

    def test_graph_badge_passthrough(self):
        spec = {"layout": "graph",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [{"from": "a", "to": "b", "badge": "2"}]}
        plan = graph_model.build_plan(spec)
        self.assertEqual(plan["graph_edges"][0].get("badge"), "2")


class MiscFeatureTest(unittest.TestCase):
    def test_circle_kind_accepted(self):
        spec = {"layout": "graph",
                "nodes": [{"id": "a", "label": "A", "kind": "circle"}, {"id": "b", "label": "B"}],
                "edges": [{"from": "a", "to": "b"}]}
        self.assertTrue(renderer.validate_spec(spec)["ok"])

    def test_amber_accent_accepted(self):
        spec = {"layout": "swimlane", "lanes": [dict(_lane(0), accent="amber"), _lane(1)]}
        self.assertTrue(renderer.validate_spec(spec)["ok"])
        plan = graph_model.build_plan(spec)
        self.assertEqual(plan["lanes"]["items"][0]["_tint"]["stroke"], "amber")

    def test_legend_unknown_color_warns(self):
        spec = {"layout": "swimlane", "lanes": [_lane(0), _lane(1)],
                "legend": [{"color": "red", "label": "x"}]}
        result = renderer.validate_spec(spec)
        self.assertTrue(any(w["path"] == "$.legend[0].color" for w in result["warnings"]))

    def test_pinned_title_zone_warns(self):
        spec = {"layout": "graph",
                "nodes": [{"id": "a", "label": "A", "x": 300, "y": 120},
                          {"id": "b", "label": "B", "x": 500, "y": 400}],
                "edges": [{"from": "a", "to": "b"}]}
        result = renderer.validate_spec(spec)
        self.assertTrue(any("title zone" in w["message"] for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
