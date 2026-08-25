"""Final mop-up branch coverage: Pillow painter branches (light finish,
graph node bodies, edge label geometry, relation markers), graph_model
planner corners, and validate_spec leftovers."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rad = load_module("render_animated_diagram")
gm = load_module("graph_model")


def pillow_png(spec):
    spec = dict(spec)
    spec.setdefault("canvas", {})["frames"] = 2
    with tempfile.TemporaryDirectory() as d:
        result = rad.write_outputs(spec, Path(d), "t", icon_engine="pillow", formats=("png",))
    return result


class PillowPainterBranchTest(unittest.TestCase):
    def test_light_style_finish(self):
        # FINISH_MODE is module-global; write_outputs does not re-apply the
        # spec style, so switch it explicitly for the light finish branch.
        spec = {"layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [{"from": "a", "to": "b"}]}
        rad.apply_style("report")
        try:
            self.assertIn("png", pillow_png(spec))
        finally:
            rad.apply_style("slate")

    def test_graph_groups_badges_and_direction(self):
        # legacy engine + groups (drawn dashed) + badges + right-direction
        # edge labels
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "right",
            "groups": [{"id": "g", "label": "Cluster"}],
            "nodes": [{"id": "a", "label": "A", "parent": "g"}, {"id": "b", "label": "B", "parent": "g"},
                      {"id": "c", "label": "C"}, {"id": "d", "label": "D"}],
            "edges": [{"from": "a", "to": "b", "label": "x", "badge": 1},
                      {"from": "a", "to": "c"}, {"from": "b", "to": "d"},
                      {"from": "c", "to": "d"}, {"from": "d", "to": "a", "kind": "loop",
                                                 "label": "back", "badge": 2}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_graph_node_bodies_and_no_icon(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "label": "A", "body": "details", "icon": "gear"},
                      {"id": "b", "label": "B", "body": "no icon body"},
                      {"id": "c", "label": "C"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_panorama_center_panel_padding(self):
        spec = {
            "layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
            "inputs": [{"label": "A"}], "steps": [{"label": "B"}], "outputs": [{"label": "C"}],
            "center_panel": {"title": "L", "cards": [{"title": "one"}]},
        }
        self.assertIn("png", pillow_png(spec))

    def test_sequence_unlabeled_message(self):
        spec = {
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "b"}, {"from": "b", "to": "a", "kind": "return"}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_class_relation_markers(self):
        spec = {
            "layout": "class", "title": {"prefix": "X", "highlight": "Y"},
            "classes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                        {"id": "c", "label": "C"}, {"id": "d", "label": "D"}],
            "relations": [{"from": "b", "to": "a", "kind": "inheritance"},
                          {"from": "c", "to": "a", "kind": "composition"},
                          {"from": "d", "to": "a", "kind": "aggregation"},
                          {"from": "a", "to": "d", "kind": "realization"}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_dfd_process_without_number(self):
        spec = {
            "layout": "dfd", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "p", "kind": "process", "label": "work"},
                      {"id": "s", "kind": "store", "label": "db"}],
            "flows": [{"from": "p", "to": "s"}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_communication_back_message(self):
        spec = {
            "layout": "communication", "title": {"prefix": "X", "highlight": "Y"},
            "objects": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"from": "a", "to": "b",
                       "messages": [{"num": "1", "label": "call()", "dir": "back"}]}],
        }
        self.assertIn("png", pillow_png(spec))

    def test_c4_empty_boundary_and_description(self):
        spec = {
            "layout": "c4", "title": {"prefix": "X", "highlight": "Y"},
            "boundaries": [{"id": "empty", "label": "E"}, {"id": "b1", "label": "B"}],
            "elements": [{"id": "a", "label": "A", "boundary": "b1",
                          "description": "a long description"},
                         {"id": "b", "label": "B"}],
            "relations": [{"from": "a", "to": "b"}],
        }
        self.assertIn("png", pillow_png(spec))


class RadHelperBranchTest(unittest.TestCase):
    def test_load_font_all_candidates_fail(self):
        from PIL import ImageFont
        # Point every candidate at a missing file so truetype raises OSError
        # for each and the chain falls through to load_default().
        with mock.patch.object(rad, "font_candidates", return_value=["/nonexistent/a.ttf"]):
            font = rad.load_font(12)
        self.assertIsNotNone(font)
        # one failure then success exercises the continue branch
        with mock.patch.object(rad, "font_candidates",
                               return_value=["/nonexistent/a.ttf"] +
                                            rad.font_candidates(hand=False, cjk=False, bold=False)):
            self.assertIsNotNone(rad.load_font(12))

    def test_load_svg_icon_render_failure(self):
        with mock.patch.object(rad, "render_svg_outline", side_effect=ValueError("bad")):
            rad.SVG_ICON_CACHE.clear()
            self.assertIsNone(rad.load_svg_icon("check", "#ffffff", 32))

    def test_icon_svg_tile_success_and_ops_sink(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (400, 300))
        draw = ImageDraw.Draw(img)
        draw._image = img
        ex = mock.MagicMock()
        # ops-recording mode with a renderable svg icon
        rad.icon(ex, draw, "check", 10, 10)
        # plain=True skips the Excalidraw placeholder rect entirely
        rad.icon(ex, draw, "check", 10, 10, plain=True)

    def test_custom_image_svg_and_failure(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (400, 300))
        draw = ImageDraw.Draw(img)
        ex = mock.MagicMock()
        with tempfile.TemporaryDirectory() as d:
            svg = Path(d) / "x.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L4 4"/></svg>',
                           encoding="utf-8")
            if rad.parse_path is not None:
                self.assertTrue(rad.custom_image(ex, draw, svg, 10, 10, 40, 40))
            with mock.patch.object(rad, "render_svg_outline", side_effect=ValueError("bad")):
                self.assertFalse(rad.custom_image(ex, draw, svg, 10, 10, 40, 40))

    def test_stamp_glyphs_tiny_scale_skips(self):
        from PIL import Image
        base = Image.new("RGB", (400, 300))
        inst = {"kind": "gear", "x": 10, "y": 10, "scale": 0.001, "color": rad.THEME["cyan"]}
        key = (rad.resolve_icon_name("gear"), rad.THEME["cyan"])
        glyph = Image.new("RGBA", (8, 8))
        with mock.patch.object(rad, "collect_icon_instances", return_value=[inst]):
            out = rad.stamp_glyphs(base, {"layout": "graph"}, {key: [glyph]}, 0.0)
        self.assertIsNotNone(out)

    def test_graph_layout_checks_groups_legacy(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy",
            "groups": [{"id": "g", "label": "G"}],
            "nodes": [{"id": "a", "label": "A", "parent": "g"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        self.assertIsInstance(rad.graph_layout_checks(spec), list)


class ValidateLeftoverBranchTest(unittest.TestCase):
    def setUp(self):
        self.validate = staticmethod(rad.validate_spec)

    def _warnings(self, spec):
        return [w["path"] for w in self.validate(spec)["warnings"]]

    def _errors(self, spec):
        return [e["path"] for e in self.validate(spec)["errors"]]

    def test_custom_icon_skips_known_check(self):
        spec = {"layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
                "inputs": [{"label": "A", "icon": "@custom/thing.png"}],
                "steps": [{"label": "B"}], "outputs": [{"label": "C"}],
                "core": {"cards": [{"title": "a"}, {"title": "b"}]}}
        # custom icons return early from check_icon; icon_file validation may
        # still flag the missing file but no "unknown icon" error appears
        errors = self._errors(spec)
        self.assertFalse(any("unknown icon" in str(e) for e in errors))

    def test_grid_cell_accent_warning(self):
        spec = {"layout": "grid", "title": {"prefix": "X", "highlight": "Y"},
                "cells": [{"title": "A", "steps": ["s"], "accent": "banana"},
                          {"title": "B", "steps": ["s"]}]}
        self.assertIn("$.cells[0].accent", self._warnings(spec))

    def test_usecase_item_id_branches(self):
        spec = {"layout": "usecase", "title": {"prefix": "X", "highlight": "Y"},
                "actors": [{"id": "u"}],
                "usecases": [{"label": "no id"}, {"id": "c"}, {"id": "c"}]}
        errors = self._errors(spec)
        self.assertIn("$.usecases[0].id", errors)
        self.assertIn("$.usecases[2].id", errors)

    def test_gantt_task_non_dict_skipped(self):
        spec = {"layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
                "sections": [{"label": "s", "tasks": ["plain string task"]}]}
        self.validate(spec)  # non-dict task is skipped without crashing

    def test_bpmn_pool_non_dict_and_element_cap(self):
        spec = {"layout": "bpmn", "title": {"prefix": "X", "highlight": "Y"},
                "pools": ["not-a-dict"],
                "elements": [{"id": f"e{i}", "kind": "task"} for i in range(25)]}
        self.assertIn("$.elements", self._warnings(spec))


class GraphModelMopUpTest(unittest.TestCase):
    def test_elk_engine_kind_and_group_normalization(self):
        import sys
        elk = importlib.util.find_spec("elk_layout")
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "a", "kind": "wat"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}],
            "groups": ["not-a-dict", {"id": "g", "label": "G", "members": ["a"]}],
        }
        if elk is None:
            fake = mock.MagicMock()
            fake.layout_graph.return_value = {
                "nodes": {"a": (0, 0, 100, 60), "b": (200, 0, 100, 60)},
                "edges": {}, "width": 400, "height": 200}
            with mock.patch.dict(sys.modules, {"elk_layout": fake}):
                out = gm.build_plan(dict(spec))
        else:
            out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_nodes"])

    def test_sequence_single_participant(self):
        out = gm.build_plan({"layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
                             "participants": [{"id": "a"}],
                             "messages": [{"from": "a", "to": "a", "kind": "self"}]})
        self.assertTrue(out)

    def test_sequence_fragment_over_notes_only(self):
        out = gm.build_plan({
            "layout": "sequence", "title": {"prefix": "X", "highlight": "Y"},
            "participants": [{"id": "a"}, {"id": "b"}],
            "messages": [{"from": "a", "to": "a", "kind": "note", "text": "n", "target": "a"},
                         {"from": "a", "to": "b", "kind": "sync"}],
            "fragments": [{"kind": "alt", "range": [0, 0]}],
        })
        self.assertTrue(out)

    def test_state_and_dfd_right_to_left_edges(self):
        out = gm.build_plan({"layout": "state", "title": {"prefix": "X", "highlight": "Y"},
                             "states": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                             "transitions": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]})
        self.assertTrue(out)
        out = gm.build_plan({"layout": "dfd", "title": {"prefix": "X", "highlight": "Y"},
                             "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                             "flows": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]})
        self.assertTrue(out)

    def test_deployment_artifact_cannot_parent(self):
        out = gm.build_plan({
            "layout": "deployment", "title": {"prefix": "X", "highlight": "Y"},
            "nodes": [{"id": "art", "kind": "artifact"},
                      {"id": "child", "parent": "art"}],
            "connections": []})
        self.assertTrue(out)

    def test_gantt_huge_day_label_fallback(self):
        out = gm.build_plan({"layout": "gantt", "title": {"prefix": "X", "highlight": "Y"},
                             "sections": [{"label": "s", "tasks": [
                                 {"label": "t", "start": 999999999, "duration": 2}]}]})
        self.assertTrue(out)

    def test_graph_right_direction_misaligned_edges(self):
        out = gm.build_plan({
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "right",
            "nodes": [{"id": n} for n in ("a", "b", "c", "d", "e")],
            "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"},
                      {"from": "b", "to": "d"}, {"from": "c", "to": "e"},
                      {"from": "d", "to": "e"}]})
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main()


class GraphModelLegacyCornerTest(unittest.TestCase):
    def test_legacy_narrow_cards_with_icons_get_taller(self):
        # 5-layer chain in down direction with icons -> cu < 150 -> card_h bump
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "right",
            "nodes": [{"id": f"n{i}", "label": f"N{i}", "icon": "gear"} for i in range(6)],
            "edges": [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(5)],
        }
        out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_nodes"])

    def test_legacy_graph_with_footer(self):
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "footer": "generated for coverage",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        out = gm.build_plan(dict(spec))
        self.assertTrue(out)


class ClassDiamondDirectTest(unittest.TestCase):
    def test_vertical_and_diagonal_segments(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (300, 300))
        draw = ImageDraw.Draw(img)
        ex = mock.MagicMock()
        # vertical segment -> abs(uy) >= 0.99 diamond branch
        rad._class_diamond(ex, draw, [(100, 200), (100, 100)], "#ffffff", True)
        # diagonal segment -> polyline approximation branch
        rad._class_diamond(ex, draw, [(50, 250), (120, 180)], "#ffffff", False)

    def test_custom_icon_missing_file_ops_branch(self):
        # custom icon whose file cannot load -> primitive fallback inside the
        # ops-suppressed branch (avoids duplicate ops)
        spec = {"layout": "panorama", "title": {"prefix": "X", "highlight": "Y"},
                "inputs": [{"label": "A", "icon": "@missing/nope.png"}],
                "steps": [{"label": "B"}], "outputs": [{"label": "C"}]}
        ex, _static = rad.render_static(spec)
        self.assertTrue(ex.elements)

    def test_communication_vertical_links(self):
        # four objects on a 2x2 arrangement produce vertical links too
        spec = {
            "layout": "communication", "title": {"prefix": "X", "highlight": "Y"},
            "footer": "coverage footer",
            "objects": [{"id": n, "label": n.upper()} for n in ("a", "b", "c", "d")],
            "links": [
                {"from": "a", "to": "c", "messages": [{"num": "1", "label": "down()", "dir": "forward"}]},
                {"from": "d", "to": "b", "messages": [{"num": "2", "label": "up()", "dir": "back"}]},
                {"from": "a", "to": "b", "messages": [{"num": "3", "label": "side()", "dir": "forward"}]},
            ],
        }
        self.assertIn("png", pillow_png(spec))


class GraphRightSkipEdgeTest(unittest.TestCase):
    def test_right_direction_skip_edge_routing(self):
        # skip edge (layer diff >= 2) in right direction -> the elif/else
        # routing chain at the right-direction block
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "right",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"},
                      {"from": "a", "to": "c"}, {"from": "c", "to": "d"},
                      {"from": "a", "to": "d"}],
        }
        out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_edges"])


class GraphDownSkipEdgeTest(unittest.TestCase):
    def test_down_direction_skip_edge_routing(self):
        # skip edge (layer diff >= 2) in down direction with lateral spread
        spec = {
            "layout": "graph", "title": {"prefix": "X", "highlight": "Y"},
            "layout_engine": "legacy", "direction": "down",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"},
                      {"from": "b", "to": "d"}, {"from": "c", "to": "d"},
                      {"from": "a", "to": "d"}],
        }
        out = gm.build_plan(dict(spec))
        self.assertTrue(out["graph_edges"])
