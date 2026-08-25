import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The original hand-tuned panorama animation geometry. plan_panorama() must
# reproduce it exactly for the default spec (4 inputs / 3 cards / 3 panels).
LEGACY_FLOW_PATHS = [
    ([(605, 239), (605, 316)], "green", 0.00),
    ([(355, 411), (472, 411)], "cyan", 0.10),
    ([(732, 411), (850, 411)], "cyan", 0.24),
    ([(982, 456), (982, 481), (768, 481), (768, 508)], "core_stroke", 0.38),
    ([(826, 568), (1022, 568)], "green", 0.54),
    ([(707, 568), (510, 568), (222, 568), (222, 456)], "purple", 0.66),
    ([(156, 637), (156, 736)], "green", 0.18),
    ([(205, 736), (205, 637)], "green", 0.58),
    ([(458, 890), (486, 890), (598, 890), (626, 890), (738, 890), (766, 890)], "purple", 0.32),
    ([(855, 890), (904, 890)], "white", 0.46),
    ([(1036, 735), (1036, 691), (766, 691), (766, 628)], "amber", 0.72),
]

LEGACY_PULSE_BOXES = [
    (389, 138, 819, 239),
    (95, 366, 355, 456),
    (472, 366, 732, 456),
    (850, 366, 1110, 456),
    (706, 508, 826, 628),
    (333, 734, 855, 1080),
    (904, 735, 1162, 1079),
]


class PanoramaPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")
        cls.renderer = load_module("render_animated_diagram")
        cls.spec = json.loads((ROOT / "assets" / "default-spec.json").read_text(encoding="utf-8"))
        cls.plan = cls.graph_model.plan_panorama(cls.spec)
        cls.graph = cls.graph_model.build_graph(cls.spec)

    def test_node_ids_unique(self):
        ids = [n["id"] for n in self.graph["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_edges_reference_existing_nodes(self):
        ids = {n["id"] for n in self.graph["nodes"]}
        for edge in self.graph["edges"]:
            self.assertIn(edge["from"], ids, edge["id"])
            self.assertIn(edge["to"], ids, edge["id"])

    def test_default_spec_produces_full_panorama(self):
        by_kind = {}
        for node in self.graph["nodes"]:
            by_kind.setdefault(node["kind"], []).append(node)
        self.assertEqual(len(by_kind["group"]), 5)
        self.assertEqual(len(by_kind["input"]), 4)
        self.assertEqual(len(by_kind["card"]), 3)
        self.assertEqual(len(by_kind["decision"]), 1)
        self.assertEqual(len(by_kind["output"]), 1)
        self.assertEqual(len(by_kind["panel-card"]), 10)

    def test_default_plan_matches_legacy_flow_paths(self):
        plan_flow = {
            (tuple(tuple(p) for p in fp["points"]), fp["color"], fp["offset"])
            for fp in self.plan["flow_paths"]
        }
        legacy = {(tuple(pts), color, offset) for pts, color, offset in LEGACY_FLOW_PATHS}
        self.assertEqual(plan_flow, legacy)

    def test_default_plan_matches_legacy_pulse_targets(self):
        plan_boxes = [tuple(pt["box"]) for pt in self.plan["pulse_targets"]]
        self.assertEqual(plan_boxes, LEGACY_PULSE_BOXES)

    def test_default_plan_matches_legacy_positions(self):
        self.assertEqual(self.plan["inputs"]["box"], (389, 130, 430, 128))
        self.assertEqual(self.plan["inputs"]["xs"], [423, 532, 640, 748])
        self.assertEqual(self.plan["inputs"]["arrow_cx"], 605)
        self.assertEqual(self.plan["core"]["xs"], [95, 472, 850])
        self.assertEqual(self.plan["core"]["w"], 260)
        self.assertEqual(self.plan["panels"]["x"], {"left_panel": 39, "center_panel": 333, "right_panel": 904})
        self.assertEqual(self.plan["panels"]["layer_xs"], [346, 486, 626, 766])
        self.assertEqual(self.plan["canvas"], {"width": 1210, "height": 1138})
        self.assertEqual(self.plan["frame"], (18, 117, 1174, 994))

    def test_icon_instances_sit_inside_graph_nodes(self):
        tile = self.renderer.ICON_TILE
        ordinal_to_node = {}
        for i in range(4):
            ordinal_to_node[i] = f"input.{i}"
        for i in range(3):
            ordinal_to_node[4 + i] = f"core.{i}"
        ordinal_to_node[7] = "output"
        for i in range(3):
            ordinal_to_node[8 + i] = f"left.{i}"
        for i in range(4):
            ordinal_to_node[11 + i] = f"layer.{i}"
        for i in range(3):
            ordinal_to_node[15 + i] = f"pack.{i}"

        nodes = {n["id"]: n for n in self.graph["nodes"]}
        instances = self.renderer.collect_icon_instances(self.spec)
        self.assertEqual(len(instances), 18)
        for inst in instances:
            node = nodes[ordinal_to_node[inst["ordinal"]]]
            size = tile * inst.get("scale", 1.0)
            self.assertGreaterEqual(inst["x"], node["x"], node["id"])
            self.assertGreaterEqual(inst["y"], node["y"], node["id"])
            self.assertLessEqual(inst["x"] + size, node["x"] + node["w"], node["id"])
            self.assertLessEqual(inst["y"] + size, node["y"] + node["h"], node["id"])

    def test_canvas_matches_renderer_defaults(self):
        self.assertEqual(self.graph["canvas"]["width"], self.renderer.DEFAULT_W)
        self.assertEqual(self.graph["canvas"]["height"], self.renderer.DEFAULT_H)

    def test_adjacency_is_symmetric(self):
        neighbors = self.graph_model.adjacency(self.graph)
        for node_id, adjacent in neighbors.items():
            for other in adjacent:
                self.assertIn(node_id, neighbors[other])
        self.assertIn("core.1", neighbors["core.0"])
        self.assertIn("decision", neighbors["output"])


class ElasticPanoramaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_omitted_panels_shrink_canvas(self):
        bare = {
            "inputs": [{"label": "a"}, {"label": "b"}],
            "core": {"cards": [{"title": "x"}, {"title": "y"}]},
        }
        plan = self.graph_model.plan_panorama(bare)
        self.assertLess(plan["canvas"]["height"], 800)
        self.assertEqual(plan["panels"]["present"], [])
        ids = {n["id"] for n in plan["nodes"]}
        self.assertNotIn("left_panel", ids)
        edge_ids = {e["id"] for e in plan["edges"]}
        self.assertNotIn("e.core_left", edge_ids)
        self.assertNotIn("e.right_decision", edge_ids)

    def test_input_counts_stay_inside_box(self):
        for n in (2, 3, 5, 6):
            spec = {"inputs": [{"label": f"i{k}"} for k in range(n)]}
            plan = self.graph_model.plan_panorama(spec)
            box_x, _y, box_w, _h = plan["inputs"]["box"]
            xs = plan["inputs"]["xs"]
            self.assertEqual(len(xs), n)
            self.assertGreaterEqual(xs[0], box_x, n)
            self.assertLessEqual(xs[-1] + 78, box_x + box_w + 12, n)

    def test_core_card_counts_fit_band(self):
        for n in (2, 3, 4):
            spec = {"core": {"cards": [{"title": f"c{k}"} for k in range(n)]}}
            plan = self.graph_model.plan_panorama(spec)
            xs, w = plan["core"]["xs"], plan["core"]["w"]
            self.assertEqual(len(xs), n)
            self.assertGreaterEqual(xs[0], 53)
            self.assertLessEqual(xs[-1] + w, 1157)
            for a, b in zip(xs, xs[1:]):
                self.assertGreater(b, a + w, "cards must not overlap")

    def test_two_panel_subset_is_centered(self):
        spec = {
            "inputs": [{"label": "a"}, {"label": "b"}],
            "core": {"cards": [{"title": "x"}, {"title": "y"}]},
            "center_panel": {"cards": [{"title": "l1"}, {"title": "l2"}]},
            "right_panel": {"cards": [{"title": "p1"}]},
        }
        plan = self.graph_model.plan_panorama(spec)
        self.assertEqual(plan["panels"]["present"], ["center_panel", "right_panel"])
        boxes = plan["panels"]["boxes"]
        left_edge = boxes["center_panel"][0]
        right_edge = boxes["right_panel"][0] + boxes["right_panel"][2]
        # Roughly centered inside [39, 1162]
        self.assertAlmostEqual(left_edge - 39, 1162 - right_edge, delta=30)
        self.assertEqual(plan["canvas"]["height"], 1138)


class SwimlanePlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def _spec(self, connections=None, subtitles=False):
        lanes = [
            {"title": "Lane A", "steps": [
                {"id": "a1", "title": "A1"}, {"id": "a2", "title": "A2"}, {"id": "a3", "title": "A3"}]},
            {"title": "Lane B", "steps": [
                {"id": "b1", "title": "B1"}, {"id": "b2", "title": "B2"}]},
        ]
        if subtitles:
            for lane in lanes:
                lane["subtitle"] = "Triggered by: something"
        spec = {"layout": "swimlane", "lanes": lanes}
        if connections is not None:
            spec["connections"] = connections
        return spec

    def test_alternating_tints(self):
        # Enterprise scheme: hierarchical bands read through gray lightness
        # steps, not hue swaps; every band shares the neutral frame stroke.
        plan = self.graph_model.plan_swimlane(self._spec())
        tints = [lane["_tint"]["stroke"] for lane in plan["lanes"]["items"]]
        self.assertEqual(tints, ["frame", "frame"])
        bands = [lane["_tint"]["band"] for lane in plan["lanes"]["items"]]
        self.assertEqual(bands, ["lane_band_0", "lane_band_1"])

    def test_external_lane_sinks_to_deep_gray(self):
        spec = self._spec()
        spec["lanes"][1]["subtitle"] = "external / third-party services"
        plan = self.graph_model.plan_swimlane(spec)
        tint = plan["lanes"]["items"][1]["_tint"]
        self.assertEqual(tint["stroke"], "lane_border")
        self.assertEqual(tint["band"], "lane_band_3")

    def test_subtitle_grows_lane(self):
        base = self.graph_model.plan_swimlane(self._spec())
        tall = self.graph_model.plan_swimlane(self._spec(subtitles=True))
        h_base = base["lanes"]["items"][0]["_h"]
        h_tall = tall["lanes"]["items"][0]["_h"]
        self.assertGreater(h_tall, h_base)

    def test_loopback_uses_dashed_channel(self):
        plan = self.graph_model.plan_swimlane(self._spec(connections=[
            {"from": "a1", "to": "a2"}, {"from": "a2", "to": "a3"},
            {"from": "a3", "to": "a1", "label": "retry"},
        ]))
        loop = next(e for e in plan["edges"] if e["loop"])
        self.assertEqual(loop["style"], "dashed")
        lane = plan["lanes"]["items"][0]
        self.assertTrue(lane["_has_channel"])
        # Channel runs under the cards but inside the lane.
        channel_y = loop["points"][1][1]
        card_bottom = max(s["_box"][1] + s["_box"][3] for s in lane["steps"])
        self.assertGreater(channel_y, card_bottom)
        self.assertLess(channel_y, lane["_y"] + lane["_h"])

    def test_cards_stay_inside_lane_after_channel_shift(self):
        plan = self.graph_model.plan_swimlane(self._spec(connections=[
            {"from": "a3", "to": "a1"}, {"from": "b2", "to": "b1"},
        ]))
        for lane in plan["lanes"]["items"]:
            for step in lane["steps"]:
                _, sy, _, sh = step["_box"]
                self.assertGreaterEqual(sy, lane["_y"])
                self.assertLessEqual(sy + sh, lane["_y"] + lane["_h"])

    def test_default_connections_chain_all_steps(self):
        plan = self.graph_model.plan_swimlane(self._spec())
        self.assertEqual(len(plan["edges"]), 4)

    def _assert_routes_clear(self, plan):
        """Every non-loop segment stays out of every card except its endpoints."""
        boxes = {s["id"]: s["_box"]
                 for lane in plan["lanes"]["items"] for s in lane["steps"]}
        for e in plan["edges"]:
            for a, b in zip(e["points"], e["points"][1:]):
                self.assertNotEqual(a, b, f"{e['id']} has a zero-length segment")
                for nid, (bx, by, bw, bh) in boxes.items():
                    if nid in (e["from"], e["to"]):
                        continue
                    if a[0] == b[0]:  # vertical run
                        x, y0, y1 = a[0], min(a[1], b[1]), max(a[1], b[1])
                        clear = not (bx < x < bx + bw and max(y0, by) < min(y1, by + bh))
                    elif a[1] == b[1]:  # horizontal run
                        y, x0, x1 = a[1], min(a[0], b[0]), max(a[0], b[0])
                        clear = not (by < y < by + bh and max(x0, bx) < min(x1, bx + bw))
                    else:
                        continue  # only orthogonal routes are produced
                    self.assertTrue(clear, f"{e['id']} crosses card {nid}")

    def test_cross_lane_links_never_cross_cards(self):
        # Two-lane skip: must not spear the intermediate lane's cards.
        lanes = [
            {"title": "L0", "steps": [{"id": "s0", "title": "S0"}]},
            {"title": "L1", "steps": [{"id": "m0", "title": "M0"}, {"id": "m1", "title": "M1"}]},
            {"title": "L2", "steps": [{"id": "t0", "title": "T0"}]},
        ]
        plan = self.graph_model.plan_swimlane({"layout": "swimlane", "lanes": lanes,
                                               "connections": [{"from": "s0", "to": "t0", "label": "skip"}]})
        self._assert_routes_clear(plan)

    def test_adjacent_cross_lane_uses_gap_corridor(self):
        # Far-apart cards in neighboring lanes: the horizontal run must sit in
        # the gap between the bands, not at card center height.
        lanes = [
            {"title": "L0", "steps": [{"id": "s0", "title": "S0"}] + [{"id": f"x{i}", "title": "X"} for i in range(4)]},
            {"title": "L1", "steps": [{"id": "t0", "title": "T0"}] + [{"id": f"y{i}", "title": "Y"} for i in range(4)]},
        ]
        # t0 first in lane 1, s0 first in lane 0 -> adjacent lane, same slot;
        # reverse the target order so source and target are far apart in x.
        lanes[1]["steps"] = list(reversed(lanes[1]["steps"]))
        plan = self.graph_model.plan_swimlane({"layout": "swimlane", "lanes": lanes,
                                               "connections": [{"from": "s0", "to": "t0", "label": "hop"}]})
        self._assert_routes_clear(plan)
        edge = plan["edges"][0]
        ys = [p[1] for p in edge["points"]]
        lane0, lane1 = plan["lanes"]["items"][0], plan["lanes"]["items"][1]
        card_bottom0 = max(s["_box"][1] + s["_box"][3] for s in lane0["steps"])
        card_top1 = min(s["_box"][1] for s in lane1["steps"])
        for a, b in zip(edge["points"], edge["points"][1:]):
            if a[1] == b[1]:  # horizontal corridor run inside the gap
                self.assertGreaterEqual(a[1], card_bottom0)
                self.assertLessEqual(a[1], card_top1)

    def test_parallel_edges_get_distinct_ports(self):
        plan = self.graph_model.plan_swimlane(self._spec(connections=[
            {"from": "a1", "to": "b1"}, {"from": "a1", "to": "b2"},
        ]))
        starts = [tuple(e["points"][0]) for e in plan["edges"]]
        self.assertEqual(len(starts), len(set(starts)), "parallel stubs must not overlap")

    def test_label_pos_stays_clear_of_cards_and_title_column(self):
        spec = self._spec(connections=[{"from": "a1", "to": "b2", "label": "hop"}],
                          subtitles=True)
        plan = self.graph_model.plan_swimlane(spec)
        edge = plan["edges"][0]
        lx, ly, lw = edge["label_pos"]
        zone_x = plan["lanes"]["x"] + plan["lanes"]["column_w"]
        self.assertGreaterEqual(lx, zone_x)
        for lane in plan["lanes"]["items"]:
            for step in lane["steps"]:
                sx, sy, sw, sh = step["_box"]
                hit = lx < sx + sw and lx + lw > sx and ly < sy + sh and ly + 18 > sy
                self.assertFalse(hit, f"label overlaps card {step.get('id')}")


class GraphPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")
        cls.renderer = load_module("render_animated_diagram")

    def _loop_spec(self, direction="right"):
        return {
            "layout": "graph",
            "layout_engine": "legacy",
            "direction": direction,
            "nodes": [
                {"id": "ingest", "label": "Ingest", "icon": "ingest"},
                {"id": "plan", "label": "Plan", "icon": "plan"},
                {"id": "act", "label": "Act", "icon": "agent"},
                {"id": "gate", "label": "Pass?", "kind": "decision"},
                {"id": "ship", "label": "Ship", "kind": "terminal"},
            ],
            "edges": [
                {"from": "ingest", "to": "plan"},
                {"from": "plan", "to": "act"},
                {"from": "act", "to": "gate"},
                {"from": "gate", "to": "ship", "label": "yes"},
                {"from": "gate", "to": "act", "kind": "loop", "label": "retry"},
                {"from": "gate", "to": "plan", "kind": "loop", "label": "replan"},
            ],
        }

    def _long_chain_spec(self):
        nodes = [{"id": f"n{i}", "label": f"N{i}", "icon": "file"} for i in range(10)]
        edges = [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(9)]
        edges.append({"from": "n8", "to": "n2", "kind": "loop", "label": "revise"})
        return {"layout": "graph", "layout_engine": "legacy", "direction": "right", "nodes": nodes, "edges": edges}

    def test_chain_layers_are_monotonic(self):
        plan = self.graph_model.plan_graph(self._loop_spec())
        boxes = {n["id"]: n["_box"] for n in plan["graph_nodes"]}
        order = ["ingest", "plan", "act", "gate", "ship"]
        centers = [boxes[i][0] + boxes[i][2] / 2 for i in order]
        self.assertEqual(centers, sorted(centers))
        self.assertEqual(plan["graph_meta"]["n_layers"], 5)

    def test_loop_edges_are_dashed_and_routed_below(self):
        plan = self.graph_model.plan_graph(self._loop_spec())
        loops = [e for e in plan["graph_edges"] if e["loop"]]
        self.assertEqual(len(loops), 2)
        grid_bottom = max(n["_box"][1] + n["_box"][3] for n in plan["graph_nodes"])
        for edge in loops:
            self.assertEqual(edge["style"], "dashed")
            lane_y = max(p[1] for p in edge["points"])
            self.assertGreater(lane_y, grid_bottom)
        # Distinct lanes so parallel loops never overlap.
        lanes = {max(p[1] for p in e["points"]) for e in loops}
        self.assertEqual(len(lanes), 2)

    def test_loops_fire_after_the_forward_wave(self):
        plan = self.graph_model.plan_graph(self._loop_spec())
        loop_pts = {tuple(map(tuple, e["points"])) for e in plan["graph_edges"] if e["loop"]}
        forward_offsets, loop_offsets = [], []
        for fp in plan["flow_paths"]:
            pts = tuple(map(tuple, fp["points"]))
            (loop_offsets if pts in loop_pts else forward_offsets).append(fp["offset"])
        self.assertLess(max(forward_offsets), min(loop_offsets))

    def test_back_edge_without_kind_is_detected_as_loop(self):
        spec = {"layout": "graph", "layout_engine": "legacy",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"}]}
        plan = self.graph_model.plan_graph(spec)
        loops = [e for e in plan["graph_edges"] if e["loop"]]
        self.assertEqual(len(loops), 1)
        self.assertEqual((loops[0]["from"], loops[0]["to"]), ("c", "a"))
        self.assertEqual(plan["graph_meta"]["n_layers"], 3)

    def test_fork_and_join_share_a_column(self):
        spec = {"layout": "graph", "layout_engine": "legacy",
                "nodes": [{"id": "s", "label": "S"}, {"id": "f1", "label": "F1"},
                          {"id": "f2", "label": "F2"}, {"id": "j", "label": "J"}],
                "edges": [{"from": "s", "to": "f1"}, {"from": "s", "to": "f2"},
                          {"from": "f1", "to": "j"}, {"from": "f2", "to": "j"}]}
        plan = self.graph_model.plan_graph(spec)
        boxes = {n["id"]: n["_box"] for n in plan["graph_nodes"]}
        self.assertEqual(boxes["f1"][0], boxes["f2"][0])
        self.assertNotEqual(boxes["f1"][1], boxes["f2"][1])

    def test_manual_coordinates_override_auto_layout(self):
        spec = self._loop_spec()
        spec["nodes"][1].update({"x": 400, "y": 480})
        plan = self.graph_model.plan_graph(spec)
        box = next(n["_box"] for n in plan["graph_nodes"] if n["id"] == "plan")
        self.assertAlmostEqual(box[0] + box[2] / 2, 400, delta=1)
        self.assertAlmostEqual(box[1] + box[3] / 2, 480, delta=1)

    def test_direction_down_stacks_vertically_and_centers(self):
        plan = self.graph_model.plan_graph(self._loop_spec(direction="down"))
        boxes = {n["id"]: n["_box"] for n in plan["graph_nodes"]}
        order = ["ingest", "plan", "act", "gate", "ship"]
        centers = [boxes[i][1] + boxes[i][3] / 2 for i in order]
        self.assertEqual(centers, sorted(centers))
        cx = boxes["ingest"][0] + boxes["ingest"][2] / 2
        self.assertGreater(cx, 350)
        self.assertLess(cx, 850)
        self.assertGreater(plan["canvas"]["height"], 700)

    def test_long_rightward_chain_auto_stacks_down(self):
        plan = self.graph_model.plan_graph(self._long_chain_spec())
        self.assertFalse(plan["graph_meta"]["horizontal"])
        self.assertTrue(plan["graph_meta"]["auto_stacked"])
        self.assertEqual(plan["graph_meta"]["requested_direction"], "right")
        boxes = {n["id"]: n["_box"] for n in plan["graph_nodes"]}
        centers = [boxes[f"n{i}"][1] + boxes[f"n{i}"][3] / 2 for i in range(10)]
        self.assertEqual(centers, sorted(centers))
        self.assertGreater(plan["canvas"]["height"], 1200)

    def test_graph_uses_natural_canvas_height_to_avoid_dead_space_or_clipping(self):
        spec = self._long_chain_spec()
        natural = self.graph_model.plan_graph(spec)["canvas"]["height"]
        spec["canvas"] = {"height": 600, "frames": 12}
        self.renderer.apply_style("slate")
        self.renderer.render_static(spec)
        self.assertEqual(self.renderer.CURRENT_PLAN["canvas"]["height"], natural)

    def test_nodes_edges_flow_are_consistent_and_serializable(self):
        plan = self.graph_model.plan_graph(self._loop_spec())
        ids = [n["id"] for n in plan["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        for edge in plan["edges"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)
        self.assertEqual(len(plan["flow_paths"]), len(plan["graph_edges"]))
        self.assertEqual(len(plan["pulse_targets"]), len(plan["graph_nodes"]))
        json.dumps({"nodes": plan["nodes"], "edges": [dict(e, points=[list(p) for p in e["points"]]) for e in plan["edges"]],
                    "flow": plan["flow_paths"], "pulse": plan["pulse_targets"]})

    def test_icons_registered_for_pillow_motion_layer(self):
        plan = self.graph_model.plan_graph(self._loop_spec())
        kinds = {i["kind"] for i in plan["icons"]}
        self.assertEqual(kinds, {"ingest", "plan", "agent"})


class SequencePlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def _spec(self):
        return {
            "layout": "sequence",
            "participants": [
                {"id": "u", "label": "用户", "kind": "actor"},
                {"id": "gw", "label": "网关"},
                {"id": "svc", "label": "服务"},
            ],
            "messages": [
                {"from": "u", "to": "gw", "label": "请求", "kind": "sync"},
                {"from": "gw", "to": "svc", "label": "转发", "kind": "sync"},
                {"kind": "note", "target": "svc", "text": "备注"},
                {"from": "svc", "to": "gw", "label": "结果", "kind": "return"},
                {"from": "gw", "to": "u", "label": "响应", "kind": "return"},
                {"from": "gw", "to": "gw", "label": "自检", "kind": "self"},
            ],
            "fragments": [
                {"kind": "alt", "label": "ok", "range": [1, 3], "dividers": [{"at": 3, "label": "fail"}]},
            ],
        }

    def test_lifelines_and_heads(self):
        plan = self.graph_model.build_plan(self._spec())
        seq = plan["sequence"]
        cxs = [p["_cx"] for p in seq["participants"]]
        self.assertEqual(cxs, sorted(cxs))
        self.assertEqual(len(plan["nodes"]), 3)
        life = seq["lifeline"]
        first_msg_y = min(m["_y"] for m in seq["messages"])
        self.assertLess(life["top"], first_msg_y)
        self.assertGreater(life["bottom"], max(m["_y"] for m in seq["messages"]))

    def test_message_order_top_down(self):
        plan = self.graph_model.build_plan(self._spec())
        ys = [m["_y"] for m in plan["sequence"]["messages"]]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(len(set(ys)), len(ys))

    def test_arrow_and_style_semantics(self):
        plan = self.graph_model.build_plan(self._spec())
        by_label = {m.get("label"): m for m in plan["sequence"]["messages"] if m["kind"] != "note"}
        self.assertEqual((by_label["请求"]["_arrow"], by_label["请求"]["_style"]), ("filled", "solid"))
        self.assertEqual((by_label["结果"]["_arrow"], by_label["结果"]["_style"]), ("open", "dashed"))

    def test_activation_pairing(self):
        plan = self.graph_model.build_plan(self._spec())
        seq = plan["sequence"]
        acts = {a["pid"]: a for a in seq["activations"]}
        ret_svc = next(m for m in seq["messages"] if m.get("label") == "结果")
        self.assertEqual(acts["svc"]["y"] + acts["svc"]["h"], ret_svc["_y"])
        ret_gw = next(m for m in seq["messages"] if m.get("label") == "响应")
        self.assertEqual(acts["gw"]["y"] + acts["gw"]["h"], ret_gw["_y"])

    def test_fragment_frame_contains_range(self):
        plan = self.graph_model.build_plan(self._spec())
        seq = plan["sequence"]
        frag = seq["fragments"][0]
        first, last = seq["messages"][1], seq["messages"][3]
        self.assertLess(frag["y"], first["_y"])
        self.assertGreater(frag["y"] + frag["h"], last["_y"])
        self.assertEqual(len(frag["dividers"]), 1)
        self.assertLess(frag["dividers"][0]["y"], last["_y"])

    def test_self_message_loops_right(self):
        plan = self.graph_model.build_plan(self._spec())
        self_msg = next(m for m in plan["sequence"]["messages"] if m["kind"] == "self")
        pts = self_msg["_points"]
        self.assertEqual(pts[0][1], pts[1][1])
        self.assertGreater(pts[1][0], pts[0][0])
        self.assertGreater(pts[2][1], pts[1][1])
        self.assertLess(pts[3][0], pts[2][0])

    def test_async_does_not_auto_activate(self):
        spec = self._spec()
        spec["messages"].append({"from": "svc", "to": "u", "label": "事件", "kind": "async"})
        plan = self.graph_model.build_plan(spec)
        pids = [a["pid"] for a in plan["sequence"]["activations"]]
        self.assertEqual(pids.count("u"), 0)


class BoxDiagramPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def _er_spec(self):
        return {
            "layout": "er",
            "entities": [
                {"id": "a", "label": "A", "attributes": [{"name": "id", "type": "int", "key": "pk"},
                                                          {"name": "name"}]},
                {"id": "b", "label": "B"},
                {"id": "c", "label": "C"},
            ],
            "relations": [
                {"from": "a", "to": "b", "cardinality": "1:N", "label": "has"},
                {"from": "b", "to": "c", "cardinality": "1:N"},
                {"from": "a", "to": "c", "cardinality": "1:1"},  # skips the b layer
            ],
        }

    def test_er_cardinality_expansion(self):
        plan = self.graph_model.build_plan(self._er_spec())
        rel = plan["er"]["relations"][0]
        self.assertEqual((rel["from_card"], rel["to_card"]), ("1", "N"))

    def test_er_boxes_have_header_and_row_height(self):
        plan = self.graph_model.build_plan(self._er_spec())
        a = next(e for e in plan["er"]["entities"] if e["id"] == "a")
        b = next(e for e in plan["er"]["entities"] if e["id"] == "b")
        self.assertGreater(a["_h"], b["_h"])  # a has two attribute rows, b has none

    def test_skip_layer_relation_routes_above_boxes(self):
        plan = self.graph_model.build_plan(self._er_spec())
        rels = {r["to"]: r for r in plan["er"]["relations"]}
        self.assertGreater(len(rels["c"]["_points"]), 2)
        lane_y = min(p[1] for p in rels["c"]["_points"])
        box_tops = [e["_box"][1] for e in plan["er"]["entities"]]
        self.assertLess(lane_y, min(box_tops))

    def test_class_relation_markers(self):
        plan = self.graph_model.build_plan({
            "layout": "class",
            "classes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            "relations": [
                {"from": "a", "to": "b", "kind": "inheritance"},
                {"from": "b", "to": "c", "kind": "composition"},
                {"from": "c", "to": "a", "kind": "dependency"},
            ],
        })
        by_kind = {r["kind"]: r for r in plan["class"]["relations"]}
        self.assertEqual((by_kind["inheritance"]["_style"], by_kind["inheritance"]["_arrow"]), ("solid", "triangle"))
        self.assertEqual((by_kind["dependency"]["_style"], by_kind["dependency"]["_arrow"]), ("dashed", "open"))
        self.assertFalse(by_kind["composition"]["_arrow"])

    def test_class_member_normalization(self):
        plan = self.graph_model.build_plan({
            "layout": "class",
            "classes": [{"id": "a", "label": "A", "kind": "interface",
                         "attributes": [{"name": "x", "visibility": "bad"}],
                         "methods": ["save()"]},
                        {"id": "b", "label": "B"}],
            "relations": [],
        })
        a = plan["class"]["classes"][0]
        self.assertEqual(a["_stereo"], "«interface»")
        self.assertEqual(a["_attrs"][0]["visibility"], "+")
        self.assertEqual(a["_methods"][0]["name"], "save()")

    def test_usecase_anchors_and_link_kinds(self):
        plan = self.graph_model.build_plan({
            "layout": "usecase",
            "actors": [{"id": "u", "label": "用户"}, {"id": "s", "label": "网关", "side": "right"}],
            "system": {"label": "平台"},
            "usecases": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"from": "u", "to": "a"}, {"from": "a", "to": "b", "kind": "include"},
                      {"from": "u", "to": "b", "kind": "include"}],  # actor->usecase include degrades
        })
        uc = plan["usecase"]
        b = uc["boundary"]
        for u in uc["usecases"]:
            self.assertGreater(u["_cx"], b["x"])
            self.assertLess(u["_cx"], b["x"] + b["w"])
        by_to = {l["to"]: l for l in uc["links"] if l["kind"] != "association"}
        self.assertEqual(len(by_to), 1)  # only the usecase->usecase include survives
        inc = next(l for l in uc["links"] if l["kind"] == "include")
        self.assertEqual((inc["_style"], inc["_arrow"]), ("dashed", "open"))



class BehaviorDiagramPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_activity_auto_prepends_initial(self):
        plan = self.graph_model.build_plan({
            "layout": "activity",
            "nodes": [{"id": "a", "label": "动作", "kind": "action"},
                      {"id": "b", "kind": "final"}],
            "edges": [{"from": "a", "to": "b"}],
        })
        kinds = [n["kind"] for n in plan["activity"]["nodes"]]
        self.assertEqual(kinds[0], "initial")
        starts = [e for e in plan["activity"]["edges"] if e["from"].startswith("_start")]
        self.assertEqual(len(starts), 1)

    def test_activity_back_edge_is_dashed_loop(self):
        plan = self.graph_model.build_plan({
            "layout": "activity",
            "nodes": [{"id": "s", "kind": "initial"}, {"id": "a", "label": "A", "kind": "action"},
                      {"id": "b", "label": "B", "kind": "action"}, {"id": "f", "kind": "final"}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "b"},
                      {"from": "b", "to": "a", "label": "retry"}, {"from": "b", "to": "f"}],
        })
        back = next(e for e in plan["activity"]["edges"] if e["label"] == "retry")
        self.assertTrue(back["_back"])
        self.assertEqual(back["_style"], "dashed")
        lane_x = min(p[0] for p in back["_points"])
        box_lefts = [n["_box"][0] for n in plan["activity"]["nodes"]]
        self.assertLess(lane_x, min(box_lefts))

    def test_activity_down_layers_stack_top_down(self):
        plan = self.graph_model.build_plan({
            "layout": "activity",
            "nodes": [{"id": "s", "kind": "initial"}, {"id": "a", "label": "A", "kind": "action"},
                      {"id": "f", "kind": "final"}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "f"}],
        })
        boxes = {n["id"]: n["_box"] for n in plan["activity"]["nodes"]}
        self.assertLess(boxes["s"][1], boxes["a"][1])
        self.assertLess(boxes["a"][1], boxes["f"][1])

    def test_state_self_transition_and_back_edge(self):
        plan = self.graph_model.build_plan({
            "layout": "state",
            "states": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "transitions": [{"from": "a", "to": "b"}, {"from": "b", "to": "b", "label": "tick"},
                            {"from": "b", "to": "a", "label": "reset"}],
        })
        self_t = next(t for t in plan["state"]["transitions"] if t["label"] == "tick")
        self.assertEqual(len(self_t["_points"]), 4)  # right-side loop
        back = next(t for t in plan["state"]["transitions"] if t["label"] == "reset")
        self.assertEqual(back["_style"], "dashed")

    def test_dfd_kind_geometry(self):
        plan = self.graph_model.build_plan({
            "layout": "dfd",
            "nodes": [{"id": "e", "label": "E", "kind": "external"},
                      {"id": "p", "label": "P", "kind": "process"},
                      {"id": "s", "label": "S", "kind": "store"}],
            "flows": [{"from": "e", "to": "p"}, {"from": "p", "to": "s"}],
        })
        boxes = {n["id"]: n["_box"] for n in plan["dfd"]["nodes"]}
        self.assertGreater(boxes["p"][3], boxes["s"][3])  # process circle taller than store
        flows = plan["dfd"]["flows"]
        self.assertEqual(len(flows), 2)


class BuildPlanDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_dispatch(self):
        self.assertEqual(self.graph_model.build_plan({})["layout"], "panorama")
        self.assertEqual(self.graph_model.build_plan({"layout": "swimlane"})["layout"], "swimlane")
        self.assertEqual(self.graph_model.build_plan({"layout": "graph", "nodes": [], "edges": []})["layout"], "graph")
        self.assertEqual(self.graph_model.build_plan({"layout": "sequence"})["layout"], "sequence")
        self.assertEqual(self.graph_model.build_plan({"layout": "er"})["layout"], "er")
        self.assertEqual(self.graph_model.build_plan({"layout": "usecase"})["layout"], "usecase")
        self.assertEqual(self.graph_model.build_plan({"layout": "class"})["layout"], "class")
        self.assertEqual(self.graph_model.build_plan({"layout": "activity"})["layout"], "activity")
        self.assertEqual(self.graph_model.build_plan({"layout": "state"})["layout"], "state")
        self.assertEqual(self.graph_model.build_plan({"layout": "dfd"})["layout"], "dfd")
        self.assertEqual(self.graph_model.build_plan({"layout": "grid"})["layout"], "grid")
        for name in ("deployment", "component", "package", "object", "composite", "profile",
                     "communication", "timing", "interaction",
                     "c4", "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone"):
            self.assertEqual(self.graph_model.build_plan({"layout": name})["layout"], name)

    def test_layout_registry_is_trimmed(self):
        self.assertEqual(self.graph_model.LAYOUTS,
                         ("panorama", "swimlane", "graph", "grid", "sequence", "er", "usecase", "class",
                          "activity", "state", "dfd",
                          "deployment", "component", "package", "object", "composite", "profile",
                          "communication", "timing", "interaction",
                          "c4", "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone"))

    def test_plans_are_json_serializable(self):
        for layout in self.graph_model.LAYOUTS:
            plan = self.graph_model.build_plan({"layout": layout})
            json.dumps({"nodes": plan["nodes"], "edges": [dict(e, points=[list(p) for p in e["points"]]) for e in plan["edges"]],
                        "flow": plan["flow_paths"], "pulse": plan["pulse_targets"]})


class StructureDiagramPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_deployment_nesting_grows_container(self):
        plan = self.graph_model.build_plan({
            "layout": "deployment",
            "nodes": [{"id": "host", "label": "Host"},
                      {"id": "a1", "label": "app.jar", "kind": "artifact", "parent": "host"},
                      {"id": "a2", "label": "cfg.yaml", "kind": "artifact", "parent": "host"},
                      {"id": "db", "label": "DB", "kind": "device"}],
            "connections": [{"from": "host", "to": "db"}],
        })
        boxes = {n["id"]: n["_box"] for n in plan["deployment"]["nodes"]}
        host = boxes["host"]
        for kid in ("a1", "a2"):
            kx, ky, kw, kh = boxes[kid]
            self.assertGreaterEqual(kx, host[0])
            self.assertGreaterEqual(ky, host[1])
            self.assertLessEqual(kx + kw, host[0] + host[2] + 1)
            self.assertLessEqual(ky + kh, host[1] + host[3] + 1)
        self.assertGreater(host[3], self.graph_model.DEPLOYMENT_NODE_H)

    def test_component_interfaces_hug_edges(self):
        plan = self.graph_model.build_plan({
            "layout": "component",
            "components": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "interfaces": [{"id": "p", "label": "I", "kind": "provided", "component": "b"},
                           {"id": "r", "label": "I", "kind": "required", "component": "a"}],
            "relations": [{"from": "r", "to": "p", "kind": "assembly"}],
        })
        cmp_plan = plan["component"]
        boxes = {c["id"]: c["_box"] for c in cmp_plan["components"]}
        ifs = {i["id"]: i for i in cmp_plan["interfaces"]}
        ax, ay, aw, ah = boxes["a"]
        self.assertEqual(ifs["r"]["_cx"], ax)          # required on left edge
        bx, by, bw, bh = boxes["b"]
        self.assertEqual(ifs["p"]["_cx"], bx + bw)     # provided on right edge
        rel = cmp_plan["relations"][0]
        self.assertEqual(rel["_style"], "solid")

    def test_package_nesting_and_stereotype_labels(self):
        plan = self.graph_model.build_plan({
            "layout": "package",
            "packages": [{"id": "ui", "label": "UI"},
                         {"id": "core", "label": "Core"},
                         {"id": "model", "label": "model", "parent": "core"}],
            "relations": [{"from": "ui", "to": "core", "kind": "import"}],
        })
        pkg = plan["package"]
        child = next(p for p in pkg["packages"] if p["id"] == "model")
        parent = next(p for p in pkg["packages"] if p["id"] == "core")
        cx, cy, cw, ch = child["_box"]
        px, py, pw, ph = parent["_box"]
        self.assertGreaterEqual(cx, px)
        self.assertLessEqual(cy + ch, py + ph + 1)
        edge = plan["edges"][0]
        self.assertEqual(edge["label"], "«import»")
        self.assertEqual(edge["style"], "dashed")

    def test_object_title_and_link_style(self):
        plan = self.graph_model.build_plan({
            "layout": "object",
            "objects": [{"id": "o1", "name": "cart", "class": "Cart",
                         "attributes": [{"name": "total", "value": "42"}]},
                        {"id": "o2", "name": "item", "class": "Item"}],
            "links": [{"from": "o1", "to": "o2", "label": "items"}],
        })
        obj = plan["object"]
        o1 = next(o for o in obj["objects"] if o["id"] == "o1")
        self.assertEqual(o1["_title"], "cart: Cart")
        self.assertEqual(o1["_attrs"][0]["value"], "42")
        self.assertEqual(plan["edges"][0]["style"], "solid")

    def test_composite_ports_and_boundary(self):
        plan = self.graph_model.build_plan({
            "layout": "composite", "classifier": "Engine",
            "parts": [{"id": "p1", "label": "A"}, {"id": "p2", "label": "B"}],
            "ports": [{"id": "po", "part": "p1", "side": "right"}],
            "connectors": [{"from": "po", "to": "p2"}],
        })
        comp = plan["composite"]
        po = comp["ports"][0]
        p1 = next(p for p in comp["parts"] if p["id"] == "p1")
        # A right-side port centers on the part's right edge.
        self.assertAlmostEqual(po["_box"][0] + po["_box"][2] / 2, p1["_box"][0] + p1["_box"][2], delta=1.5)
        b = comp["boundary"]
        for p in comp["parts"]:
            x, y, w, h = p["_box"]
            self.assertGreater(x, b["x"])
            self.assertLess(x + w, b["x"] + b["w"])

    def test_profile_extension_arrow_style(self):
        plan = self.graph_model.build_plan({
            "layout": "profile",
            "stereotypes": [{"id": "s", "label": "Entity"}],
            "metaclasses": [{"id": "m", "label": "Class"}],
            "extensions": [{"from": "s", "to": "m"}],
        })
        rel = plan["profile"]["relations"][0]
        self.assertEqual((rel["_style"], rel["_arrow"]), ("solid", "filled"))


class Behavior2PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_communication_messages_normalized(self):
        plan = self.graph_model.build_plan({
            "layout": "communication",
            "objects": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "links": [{"from": "a", "to": "b",
                       "messages": [{"label": "go()"}, {"num": "2", "label": "back()", "dir": "back"}]}],
        })
        msgs = plan["communication"]["links"][0]["messages"]
        self.assertEqual(msgs[0]["num"], "1")
        self.assertEqual(msgs[1]["dir"], "back")
        self.assertEqual(len(plan["edges"]), 1)

    def test_timing_step_line_and_ticks(self):
        plan = self.graph_model.build_plan({
            "layout": "timing",
            "lifelines": [{"id": "w", "label": "Web", "states": ["idle", "busy"],
                           "events": [{"t": 0, "state": "idle"}, {"t": 2, "state": "busy"},
                                      {"t": 4, "state": "idle"}]}],
        })
        tim = plan["timing"]
        pts = tim["lifelines"][0]["_points"]
        ys = sorted({p[1] for p in pts})
        self.assertEqual(len(ys), 2)  # two state levels
        self.assertEqual(pts[0][0], round(self.graph_model.TIMING_CHART_X0))
        self.assertGreaterEqual(len(tim["ticks"]), 2)

    def test_timing_message_spans_lifelines(self):
        plan = self.graph_model.build_plan({
            "layout": "timing",
            "lifelines": [
                {"id": "a", "label": "A", "states": ["x", "y"],
                 "events": [{"t": 0, "state": "x"}]},
                {"id": "b", "label": "B", "states": ["x", "y"],
                 "events": [{"t": 0, "state": "x"}]}],
            "messages": [{"from": "a", "to": "b", "t": 1, "label": "ping"}],
        })
        msg = plan["timing"]["messages"][0]
        self.assertEqual(msg["_points"][0][0], msg["_points"][1][0])  # vertical drop
        self.assertNotEqual(msg["_points"][0][1], msg["_points"][1][1])

    def test_interaction_auto_initial_and_skip_lane(self):
        plan = self.graph_model.build_plan({
            "layout": "interaction",
            "nodes": [{"id": "a", "label": "A", "kind": "interaction"},
                      {"id": "b", "label": "B", "kind": "interaction"},
                      {"id": "c", "label": "C", "kind": "interaction"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "a", "to": "c"}],
        })
        kinds = [n["kind"] for n in plan["interaction"]["nodes"]]
        self.assertEqual(kinds[0], "initial")
        skip = next(e for e in plan["interaction"]["edges"]
                    if e["from"] == "a" and e["to"] == "c")
        max_x = max(p[0] for p in skip["_points"])
        frame_right = max(n["_box"][0] + n["_box"][2] for n in plan["interaction"]["nodes"])
        self.assertGreater(max_x, frame_right)  # routed around the middle frame


class OfficeDiagramPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_model = load_module("graph_model")

    def test_c4_boundary_wraps_members(self):
        plan = self.graph_model.build_plan({
            "layout": "c4",
            "boundaries": [{"id": "b", "label": "内部"}],
            "elements": [{"id": "u", "label": "U", "kind": "person"},
                         {"id": "s", "label": "S", "kind": "container", "boundary": "b"}],
            "relations": [{"from": "u", "to": "s"}],
        })
        bound = plan["c4"]["boundaries"][0]["_box"]
        s = next(e for e in plan["c4"]["elements"] if e["id"] == "s")
        x, y, w, h = s["_box"]
        self.assertGreater(x, bound[0])
        self.assertLess(x + w, bound[0] + bound[2])
        u = next(e for e in plan["c4"]["elements"] if e["id"] == "u")
        self.assertLess(u["_box"][0], bound[0])  # person stays outside

    def test_gantt_dates_and_milestone(self):
        plan = self.graph_model.build_plan({
            "layout": "gantt",
            "sections": [{"label": "S", "tasks": [
                {"label": "a", "start": "2026-08-01", "end": "2026-08-05", "kind": "done"},
                {"label": "m", "start": "2026-08-06", "kind": "milestone"}]}],
        })
        tasks = plan["gantt"]["sections"][0]["tasks"]
        self.assertLess(tasks[0]["_x1"], tasks[1]["_x0"] + 1)
        self.assertEqual(tasks[1]["_x0"], tasks[1]["_x1"])  # milestone has no width
        self.assertEqual(len(plan["gantt"]["ticks"]), 8)

    def test_bpmn_lane_assignment_and_columns(self):
        plan = self.graph_model.build_plan({
            "layout": "bpmn",
            "pools": [{"label": "P", "lanes": [{"id": "l1", "label": "A"}, {"id": "l2", "label": "B"}]}],
            "elements": [{"id": "s", "kind": "start", "lane": "l1"},
                         {"id": "t", "label": "T", "kind": "task", "lane": "l2"},
                         {"id": "e", "kind": "end", "lane": "l2"}],
            "flows": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}],
        })
        boxes = {e["id"]: e["_box"] for e in plan["bpmn"]["elements"]}
        lanes = {l["id"]: l for l in plan["bpmn"]["lanes"]}
        self.assertGreaterEqual(boxes["s"][1], lanes["l1"]["_y"])
        self.assertLessEqual(boxes["s"][1] + boxes["s"][3], lanes["l1"]["_y"] + lanes["l1"]["_h"])
        self.assertGreaterEqual(boxes["t"][1], lanes["l2"]["_y"])
        self.assertLess(boxes["s"][0], boxes["t"][0])
        self.assertLess(boxes["t"][0], boxes["e"][0])

    def test_orgchart_parents_center_over_children(self):
        plan = self.graph_model.build_plan({
            "layout": "orgchart",
            "nodes": [{"id": "r", "label": "R"},
                      {"id": "a", "label": "A", "parent": "r"},
                      {"id": "b", "label": "B", "parent": "r"}],
        })
        boxes = {n["id"]: n["_box"] for n in plan["orgchart"]["nodes"]}
        rc = boxes["r"][0] + boxes["r"][2] / 2
        ac = boxes["a"][0] + boxes["a"][2] / 2
        bc = boxes["b"][0] + boxes["b"][2] / 2
        self.assertAlmostEqual(rc, (ac + bc) / 2, delta=1.5)
        self.assertLess(boxes["r"][1], boxes["a"][1])

    def test_mindmap_radial_around_root(self):
        plan = self.graph_model.build_plan({
            "layout": "mindmap",
            "root": {"label": "R", "children": [{"label": "A"}, {"label": "B"}, {"label": "C"}]},
        })
        mm = plan["mindmap"]
        rx, ry, rw, rh = mm["root"]["_box"]
        rcx, rcy = rx + rw / 2, ry + rh / 2
        for t in mm["topics"]:
            x, y, w, h = t["_box"]
            dist = ((x + w / 2 - rcx) ** 2 + (y + h / 2 - rcy) ** 2) ** 0.5
            self.assertGreater(dist, 150)  # topics pushed out to a ring
            self.assertLess(dist, 500)

    def test_timeline_alternates_sides(self):
        plan = self.graph_model.build_plan({
            "layout": "timeline",
            "events": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
        })
        events = plan["timeline"]["events"]
        self.assertTrue(events[0]["_above"])
        self.assertFalse(events[1]["_above"])
        self.assertTrue(events[2]["_above"])

    def test_fishbone_bones_alternate(self):
        plan = self.graph_model.build_plan({
            "layout": "fishbone",
            "problem": "P",
            "categories": [{"label": "c1", "causes": ["x"]}, {"label": "c2"}, {"label": "c3"}],
        })
        cats = plan["fishbone"]["categories"]
        spine_y = plan["fishbone"]["spine"]["y"]
        self.assertLess(cats[0]["_tip"][1], spine_y)
        self.assertGreater(cats[1]["_tip"][1], spine_y)
        self.assertLess(cats[2]["_tip"][1], spine_y)


if __name__ == "__main__":
    unittest.main()
