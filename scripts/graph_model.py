#!/usr/bin/env python3
"""Layout planning + graph model for DiagramForge diagrams.

Single source of truth for diagram geometry. For each layout preset a
``plan_<layout>(spec)`` function turns spec content into a *plan*:

- element geometry (boxes, slots, computed canvas height),
- animation data (``flow_paths`` polylines + ``pulse_targets``, colors as
  THEME keys),
- icon instances (for the pillow icon-motion layer),
- interaction graph (``nodes`` / ``edges`` for the interactive HTML).

Consumers:

- ``render_animated_diagram`` draws the Pillow raster + records the op
  stream from a plan,
- ``svg_renderer`` animates ``flow_paths`` / ``pulse_targets`` in Chromium,
- the interactive HTML uses ``nodes`` / ``edges`` for hotspots and
  adjacency highlighting.

The module is stdlib-only. Coordinates are calibrated so that the classic
default spec (4 inputs / 3 cards / 3 panels) reproduces the original
hand-tuned panorama exactly; tests assert this.
"""
from __future__ import annotations

import math
import sys as _sys
from pathlib import Path as _Path

# Make sibling scripts (elk_layout) importable even when this module is loaded
# directly via importlib from a test, not via the render entry point.
_SCRIPTS_DIR = str(_Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)  # pragma: no cover

LAYOUTS = ("panorama", "swimlane", "graph", "grid", "sequence", "er", "usecase", "class", "activity", "state", "dfd",
           "deployment", "component", "package", "object", "composite", "profile",
           "communication", "timing", "interaction",
           "c4", "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone")

# ---------------------------------------------------------------------------
# Legacy panorama constants (canonical art direction at default counts)
# ---------------------------------------------------------------------------

CANVAS_W = 1210
CANVAS_H = 1138

INPUT_Y = 174
CORE_Y = 366
CORE_CARD_H = 90
DECISION_BOX = (706, 508, 120, 120)
OUTPUT_BOX = (1022, 527, 100, 94)

LEFT_CARD_SLOTS = [(797, 78), (892, 78), (987, 62)]  # (y, h) inside left panel
LAYER_Y = 827
LAYER_CARD_W = 112
LAYER_CARD_H = 142
PACK_YS = [786, 884, 982]
PACK_H = 84

PANEL_WIDTHS = {"left_panel": 281, "center_panel": 522, "right_panel": 258}
LEGACY_PANEL_X = {"left_panel": 39, "center_panel": 333, "right_panel": 904}
PANEL_Y = {"left_panel": 735, "center_panel": 734, "right_panel": 735}
PANEL_H = {"left_panel": 344, "center_panel": 346, "right_panel": 344}


def _node(node_id, kind, x, y, w, h, label="", icon=None, group=None, link=None):
    node = {"id": node_id, "kind": kind, "x": round(x), "y": round(y), "w": round(w), "h": round(h), "label": label}
    if icon:
        node["icon"] = icon
    if group:
        node["group"] = group
    if link:
        node["link"] = link
    return node


def _icon(kind, x, y, color, group, ordinal, scale=1.0):
    return {"kind": kind, "x": x, "y": y, "scale": scale, "color": color, "group": group, "ordinal": ordinal}


def get_layout(spec):
    return (spec or {}).get("layout", "panorama")


def build_plan(spec):
    layout = get_layout(spec)
    if layout == "swimlane":
        return plan_swimlane(spec)
    if layout == "grid":
        return plan_grid(spec)
    if layout == "graph":
        return plan_graph(spec)
    if layout == "sequence":
        return plan_sequence(spec)
    if layout == "er":
        return plan_er(spec)
    if layout == "usecase":
        return plan_usecase(spec)
    if layout == "class":
        return plan_class(spec)
    if layout == "activity":
        return plan_activity(spec)
    if layout == "state":
        return plan_state(spec)
    if layout == "dfd":
        return plan_dfd(spec)
    if layout == "deployment":
        return plan_deployment(spec)
    if layout == "component":
        return plan_component(spec)
    if layout == "package":
        return plan_package(spec)
    if layout == "object":
        return plan_object(spec)
    if layout == "composite":
        return plan_composite(spec)
    if layout == "profile":
        return plan_profile(spec)
    if layout == "communication":
        return plan_communication(spec)
    if layout == "timing":
        return plan_timing(spec)
    if layout == "interaction":
        return plan_interaction(spec)
    if layout == "c4":
        return plan_c4(spec)
    if layout == "gantt":
        return plan_gantt(spec)
    if layout == "bpmn":
        return plan_bpmn(spec)
    if layout == "orgchart":
        return plan_orgchart(spec)
    if layout == "mindmap":
        return plan_mindmap(spec)
    if layout == "timeline":
        return plan_timeline(spec)
    if layout == "fishbone":
        return plan_fishbone(spec)
    return plan_panorama(spec)


def build_graph(spec):
    """Interaction graph (canvas + nodes + edges) for any layout."""
    plan = build_plan(spec)
    return {"canvas": plan["canvas"], "nodes": plan["nodes"], "edges": plan["edges"]}


def adjacency(graph):
    """node id -> set of directly connected node ids (undirected view)."""
    neighbors = {n["id"]: set() for n in graph["nodes"]}
    for edge in graph["edges"]:
        neighbors[edge["from"]].add(edge["to"])
        neighbors[edge["to"]].add(edge["from"])
    return neighbors


# ---------------------------------------------------------------------------
# Panorama (elastic: 2-6 inputs, 2-4 core cards, panels optional)
# ---------------------------------------------------------------------------

CORE_CARD_WIDTHS = {2: 300, 3: 260, 4: 230}


def plan_panorama(spec):
    spec = spec or {}
    nodes, edges, flow, pulses, icons = [], [], [], [], []

    inputs = list(spec.get("inputs", []))
    if not inputs:
        inputs = [{"label": "", "icon": "file"} for _ in range(4)]
    inputs = inputs[:6]
    n_in = len(inputs)

    cards = list(spec.get("core", {}).get("cards", []))
    if not cards:
        cards = [{"title": "", "body": "", "icon": "file"} for _ in range(3)]
    cards = cards[:4]
    if len(cards) < 2:
        cards.append({"title": "", "body": "", "icon": "file"})
    n_cards = len(cards)

    has_left = bool(spec.get("left_panel", {}).get("cards"))
    has_center = bool(spec.get("center_panel", {}).get("cards"))
    has_right = bool(spec.get("right_panel", {}).get("cards"))
    any_panel = has_left or has_center or has_right

    # --- input strip -----------------------------------------------------
    if n_in == 4:
        input_xs = [423, 532, 640, 748]  # legacy hand-tuned positions
    else:
        pitch = 108.34
        span = (n_in - 1) * pitch + 78
        first = 624.5 - span / 2
        input_xs = [round(first + i * pitch) for i in range(n_in)]
    box_x = input_xs[0] - 34
    box_w = (input_xs[-1] + 71) - box_x
    input_box = (box_x, 130, box_w, 128)
    arrow_cx = box_x + box_w // 2 + 1

    nodes.append(_node("inputs", "group", *input_box, label=spec.get("input_title", "Source / Input")))
    for i, (x, item) in enumerate(zip(input_xs, inputs)):
        nodes.append(_node(f"input.{i}", "input", x - 5, INPUT_Y, 78, 76,
                           label=item.get("label", ""), icon=item.get("icon", "file"), group="inputs"))
        icons.append(_icon(item.get("icon", "file"), x + 9, INPUT_Y, item.get("color"), "input", i))

    # --- core band ---------------------------------------------------------
    card_w = CORE_CARD_WIDTHS[min(4, max(2, n_cards))]
    if n_cards == 1:
        card_xs = [472]  # pragma: no cover - cards are padded to >=2 above
    else:
        left0, right0 = 95, 1110 - card_w
        card_xs = [round(left0 + (right0 - left0) * i / (n_cards - 1)) for i in range(n_cards)]

    core_group = (53, 317, 1104, 320)
    nodes.append(_node("core", "group", *core_group, label=spec.get("core", {}).get("title", "Archive Core")))
    for i, (x, card) in enumerate(zip(card_xs, cards)):
        nodes.append(_node(f"core.{i}", "card", x, CORE_Y, card_w, CORE_CARD_H,
                           label=card.get("title", ""), icon=card.get("icon", "file"), group="core"))
        icons.append(_icon(card.get("icon", "file"), x + 14, CORE_Y + 13, card.get("color"), "core", 4 + i))

    nodes.append(_node("decision", "decision", *DECISION_BOX, label=spec.get("decision", {}).get("title", "Ready?")))
    output = spec.get("output", {})
    nodes.append(_node("output", "output", *OUTPUT_BOX, label=output.get("label", "Report"), icon=output.get("icon", "file")))
    icons.append(_icon(output.get("icon", "file"), 1035, 537, output.get("color"), "output", 7))

    # --- edges + flow for the top half --------------------------------------
    def add_edge(eid, src, dst, points, color, offset, label=None, style="solid", draw_arrow=True):
        edges.append({"id": eid, "from": src, "to": dst, "points": [tuple(p) for p in points],
                      "color": color, "label": label, "style": style})
        flow.append({"points": [list(p) for p in points], "color": color, "offset": round(offset, 4)})
        return draw_arrow

    add_edge("e.inputs_core", "inputs", "core.0", [(arrow_cx, 239), (arrow_cx, 316)], "green", 0.0)
    for i in range(n_cards - 1):
        pts = [(card_xs[i] + card_w, 411), (card_xs[i + 1], 411)]
        add_edge(f"e.core{i}_core{i+1}", f"core.{i}", f"core.{i+1}", pts, "cyan", 0.10 + 0.14 * i)

    last_cx = card_xs[-1] + card_w // 2 + 2
    first_loop_x = card_xs[0] + card_w // 2 - 3
    add_edge("e.core_last_decision", f"core.{n_cards-1}", "decision",
             [(last_cx, 456), (last_cx, 481), (768, 481), (768, 508)], "core_stroke", 0.38)
    add_edge("e.decision_output", "decision", "output", [(826, 568), (1022, 568)], "green", 0.54,
             label=(spec.get("decision") or {}).get("yes_label", "Yes"))
    add_edge("e.decision_core0", "decision", "core.0",
             [(707, 568), (510, 568), (first_loop_x, 568), (first_loop_x, 456)], "purple", 0.66,
             label=spec.get("retry_label", "No / missing source or conflict"), style="dashed")

    # --- bottom panels -------------------------------------------------------
    present = [name for name, flag in
               [("left_panel", has_left), ("center_panel", has_center), ("right_panel", has_right)] if flag]
    if present == ["left_panel", "center_panel", "right_panel"]:
        panel_x = dict(LEGACY_PANEL_X)
    else:
        total = sum(PANEL_WIDTHS[p] for p in present) + 24 * (len(present) - 1) if present else 0
        start = 39 + (1123 - total) // 2 if present else 0
        panel_x = {}
        for p in present:
            panel_x[p] = start
            start += PANEL_WIDTHS[p] + 24

    panel_boxes = {}
    for p in present:
        panel_boxes[p] = (panel_x[p], PANEL_Y[p], PANEL_WIDTHS[p], PANEL_H[p])
        title_key = {"left_panel": "title", "center_panel": "title", "right_panel": "title"}[p]
        nodes.append(_node(p, "group", *panel_boxes[p], label=spec.get(p, {}).get(title_key, "")))

    if has_left:
        lx = panel_x["left_panel"]
        for i, ((y, h), card) in enumerate(zip(LEFT_CARD_SLOTS, spec.get("left_panel", {}).get("cards", [])[:3])):
            nodes.append(_node(f"left.{i}", "panel-card", lx + 12, y, 258, h,
                               label=card.get("title", ""), icon=card.get("icon", "file"), group="left_panel"))
            icons.append(_icon(card.get("icon", "file"), lx + 22, y + 10, card.get("color"), "panel", 8 + i))
        left_spec = spec.get("left_panel", {})
        add_edge("e.core_left", "core", "left_panel", [(lx + 117, 637), (lx + 117, 736)], "green", 0.18,
                 label=left_spec.get("down_label", "Read"))
        add_edge("e.left_core", "left_panel", "core", [(lx + 166, 736), (lx + 166, 637)], "green", 0.58,
                 label=left_spec.get("up_label", "Context"))

    layer_xs = []
    if has_center:
        cx0 = panel_x["center_panel"]
        layer_cards = list(spec.get("center_panel", {}).get("cards", []))[:4]
        k = max(2, len(layer_cards))
        while len(layer_cards) < k:
            layer_cards.append({"title": "", "body": "", "icon": "file"})
        pitch_layers = 140
        span_layers = (k - 1) * pitch_layers + LAYER_CARD_W
        # +13 reproduces the legacy hand-tuned x=346 at the canonical 4 cards.
        first = cx0 + 13 if k == 4 else cx0 + (PANEL_WIDTHS["center_panel"] - span_layers) // 2
        layer_xs = [first + i * pitch_layers for i in range(k)]
        chain_pts = []
        for i, (x, card) in enumerate(zip(layer_xs, layer_cards)):
            nodes.append(_node(f"layer.{i}", "panel-card", x, LAYER_Y, LAYER_CARD_W, LAYER_CARD_H,
                               label=card.get("title", ""), icon=card.get("icon", "file"), group="center_panel"))
            icons.append(_icon(card.get("icon", "file"), x + 18, 840, card.get("color"), "layer", 11 + i))
            if i:
                pts = [(layer_xs[i - 1] + LAYER_CARD_W, 890), (x, 890)]
                edges.append({"id": f"e.layer{i-1}_layer{i}", "from": f"layer.{i-1}", "to": f"layer.{i}",
                              "points": [tuple(p) for p in pts], "color": "purple", "label": None, "style": "solid"})
                chain_pts.extend(pts)
        if chain_pts:
            flow.append({"points": [list(p) for p in chain_pts], "color": "purple", "offset": 0.32})

    if has_center and has_right:
        rx = panel_x["right_panel"]
        c_right = panel_x["center_panel"] + PANEL_WIDTHS["center_panel"]
        add_edge("e.center_right", "center_panel", "right_panel", [(c_right, 890), (rx, 890)], "white", 0.46,
                 label=spec.get("right_panel", {}).get("incoming_label", "Compile"))
    if has_right:
        rx = panel_x["right_panel"]
        for i, (y, card) in enumerate(zip(PACK_YS, spec.get("right_panel", {}).get("cards", [])[:3])):
            nodes.append(_node(f"pack.{i}", "panel-card", rx + 14, y, 228, PACK_H,
                               label=card.get("title", ""), icon=card.get("icon", "file"), group="right_panel"))
            icons.append(_icon(card.get("icon", "file"), rx + 26, y + 10, card.get("color"), "pack", 15 + i))
        add_edge("e.right_decision", "right_panel", "decision",
                 [(rx + 132, 735), (rx + 132, 691), (766, 691), (766, 628)], "amber", 0.72,
                 label=spec.get("right_panel", {}).get("return_label", "Reusable"))

    # --- canvas + chrome -----------------------------------------------------
    height = CANVAS_H if any_panel else 704
    frame = (18, 117, 1174, height - 144)

    pulses.append({"box": [input_box[0], 138, input_box[0] + input_box[2], 239], "color": "green"})
    for i, x in enumerate(card_xs):
        pulses.append({"box": [x, CORE_Y, x + card_w, CORE_Y + CORE_CARD_H], "color": "green" if i % 2 else "core_stroke"})
    pulses.append({"box": [706, 508, 826, 628], "color": "green"})
    if has_center:
        b = panel_boxes["center_panel"]
        pulses.append({"box": [b[0], b[1], b[0] + b[2], b[1] + b[3]], "color": "purple"})
    if has_right:
        b = panel_boxes["right_panel"]
        pulses.append({"box": [b[0], b[1], b[0] + b[2], b[1] + b[3]], "color": "green"})

    def _glow(box, color, width, light=None):
        return {"box": list(box), "color": color, "light": light or color, "width": width}

    glow = [_glow([18, 117, 1192, height - 27], "frame", 3),
            _glow([53, 317, 1157, 637], "core_stroke", 3)]
    if has_center:
        b = panel_boxes["center_panel"]
        glow.append(_glow([b[0], b[1], b[0] + b[2], b[1] + b[3]], "purple", 3))
    if has_left:
        b = panel_boxes["left_panel"]
        glow.append(_glow([b[0], b[1], b[0] + b[2], b[1] + b[3]], "green", 3))
    if has_right:
        b = panel_boxes["right_panel"]
        glow.append(_glow([b[0], b[1], b[0] + b[2], b[1] + b[3]], "green", 3, light="pink"))
    glow.append(_glow([600, 27, 992, 99], "green", 2, light="pink"))

    return {
        "layout": "panorama",
        "canvas": {"width": spec.get("canvas", {}).get("width", CANVAS_W), "height": height},
        "frame": frame,
        "inputs": {"box": input_box, "xs": input_xs, "items": inputs, "arrow_cx": arrow_cx},
        "core": {"group": core_group, "xs": card_xs, "w": card_w, "cards": cards,
                 "last_cx": last_cx, "first_loop_x": first_loop_x},
        "panels": {"present": present, "x": panel_x, "boxes": panel_boxes, "layer_xs": layer_xs},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": icons,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Swimlane (2-5 category bands, hand-drawn-style: tinted band + darker
# title column + steps + dashed in-lane return channel)
# ---------------------------------------------------------------------------

# Enterprise band scheme (Carbon / C4): hierarchical levels read through
# neutral-gray lightness steps, never hue swaps; external layers sink to the
# deepest gray with a heavier border (the C4 "external system" convention).
# Semantic accents stay available for explicit status coloring only.
SWIMLANE_LEVEL_TINTS = [  # band gray steps by hierarchy level (THEME keys)
    {"stroke": "frame", "band": "lane_band_0", "column": "lane_band_1"},
    {"stroke": "frame", "band": "lane_band_1", "column": "lane_band_2"},
    {"stroke": "frame", "band": "lane_band_2", "column": "lane_band_3"},
    {"stroke": "frame", "band": "lane_band_3", "column": "lane_column"},
]
SWIMLANE_EXTERNAL_TINT = {"stroke": "lane_border", "band": "lane_band_3", "column": "lane_column"}
SWIMLANE_EXTERNAL_KEYWORDS = ("外部", "第三方", "external", "3rd", "third-party", "third party")
SWIMLANE_ACCENT_TINTS = {  # explicit lane/cell "accent" overrides (semantic only)
    "green": {"stroke": "green", "band": "source_fill", "column": "green_fill"},
    "purple": {"stroke": "purple", "band": "archive_fill", "column": "purple_fill"},
    "amber": {"stroke": "amber", "band": "sand_fill", "column": "amber_fill"},
    "blue": {"stroke": "core_stroke", "band": "blue_fill", "column": "blue_fill"},
    "external": SWIMLANE_EXTERNAL_TINT,
}
SWIMLANE_COLUMN_W = 178


def _is_external_lane(lane):
    """External/third-party layers sink to the deep gray (C4 convention)."""
    if lane.get("accent") == "external":
        return True
    text = f"{lane.get('title', '')} {lane.get('subtitle', '')}".lower()
    return any(kw in text for kw in SWIMLANE_EXTERNAL_KEYWORDS)


def _swim_edge_anchor(points):
    """Midpoint of the longest segment; fallback anchor when a route has no
    horizontal corridor run. Returns ((mx, my), horiz)."""
    best, best_len = None, -1
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if seg > best_len:
            best_len = seg
            best = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, abs(b[0] - a[0]) >= abs(b[1] - a[1]))
    if best is None:
        best = (points[0][0], points[0][1], True)
    return (best[0], best[1]), best[2]


def _swimlane_tint(lane, index):
    if _is_external_lane(lane):
        return SWIMLANE_EXTERNAL_TINT
    if lane.get("accent"):
        return SWIMLANE_ACCENT_TINTS.get(lane["accent"], SWIMLANE_LEVEL_TINTS[min(index, 3)])
    return SWIMLANE_LEVEL_TINTS[min(index, 3)]


def plan_swimlane(spec):
    spec = spec or {}
    lanes = [dict(x) for x in spec.get("lanes", [])][:8]
    while len(lanes) < 2:
        lanes.append({"title": "", "steps": []})
    canvas_spec = spec.get("canvas") or {}
    width = int(canvas_spec.get("width") or 1210)
    lane_x, gap, top = 55, 22, 190
    lane_w = width - lane_x * 2
    nodes, edges, flow, pulses, icons, ys = [], [], [], [], [], []
    step_nodes = {}
    step_lane = {}
    ordinal = 0

    connections = spec.get("connections") or []

    # Base lane heights first, so a forced-taller spec canvas can distribute
    # the extra vertical space across bands instead of leaving a dead bottom.
    for lane in lanes:
        base_h = 122
        if lane.get("subtitle"):
            base_h += 18
        if lane.get("caption"):
            base_h += 26
        if any(isinstance(s, dict) and s.get("note") for s in lane.get("steps", [])):
            base_h += 16
        lane["_base_h"] = base_h
    spec_h = int(canvas_spec.get("height") or 0)
    natural_h = top + sum(l["_base_h"] for l in lanes) + gap * (len(lanes) - 1) + 62
    stretch = max(0, (spec_h - natural_h) // len(lanes)) if spec_h > natural_h else 0

    y = top
    zone_x, zone_w = lane_x + SWIMLANE_COLUMN_W + 12, lane_w - SWIMLANE_COLUMN_W - 42
    for i, lane in enumerate(lanes):
        lane["_tint"] = _swimlane_tint(lane, i)
        steps = [dict(s) for s in lane.get("steps", [])][:8]
        lane["steps"] = steps
        lane_h = lane["_base_h"] + stretch
        card_dy = 20 + stretch // 2
        lane["_card_dy"] = card_dy
        lane["_has_channel"] = False
        ys.append(y)
        lane["_y"], lane["_h"] = y, lane_h
        nodes.append(_node(f"lane.{i}", "group", lane_x, y, lane_w, lane_h, label=lane.get("title", "")))
        count = max(1, len(steps))
        card_w = min(170, int((zone_w - (count - 1) * 28) / count))
        total = count * card_w + (count - 1) * 28
        x = zone_x + (zone_w - total) // 2
        for j, step in enumerate(steps):
            box = (x, y + card_dy, card_w, 82)
            step["_box"] = box
            node_id = step.get("id") or f"step.{i}.{j}"
            step_nodes[node_id] = box
            step_lane[node_id] = i
            nodes.append(_node(node_id, "card", *box, label=step.get("title", ""), icon=step.get("icon", "file"), group=f"lane.{i}"))
            icons.append(_icon(step.get("icon", "file"), x + 9, y + card_dy + 15, step.get("color"), "swimlane", ordinal))
            ordinal += 1
            pulses.append({"box": [x, y + card_dy, x + card_w, y + card_dy + 82], "color": lane["_tint"]["stroke"]})
            x += card_w + 28
        y += lane_h + gap
    if not connections:
        ordered = [n["id"] for n in nodes if n["kind"] == "card"]
        connections = [{"from": a, "to": b} for a, b in zip(ordered, ordered[1:])]

    # In-lane loop backs (target left of source, same lane) share a dashed
    # channel under the cards; reserve extra lane height once per lane.
    def is_loopback(edge):
        a, b = step_nodes.get(edge.get("from")), step_nodes.get(edge.get("to"))
        if not a or not b:
            return False
        same_lane = step_lane[edge["from"]] == step_lane[edge["to"]]
        return same_lane and (b[0] + b[2]) <= a[0]

    channel_lanes = {step_lane[e["from"]] for e in connections if is_loopback(e)}
    if channel_lanes:
        shift = 0
        for i, lane in enumerate(lanes):
            lane["_y"] += shift
            ys[i] = lane["_y"]
            if i in channel_lanes:
                lane["_h"] += 34
                lane["_has_channel"] = True
                shift += 34
        # Re-anchor node boxes to the shifted lanes.
        for node in nodes:
            if node["kind"] == "group":
                idx = int(node["id"].split(".")[1])
                node["y"] = lanes[idx]["_y"]
                node["h"] = lanes[idx]["_h"]
        for i, lane in enumerate(lanes):
            for j, step in enumerate(lane["steps"]):
                bx, _, bw, bh = step["_box"]
                step["_box"] = (bx, lane["_y"] + lane["_card_dy"], bw, bh)
                node_id = step.get("id") or f"step.{i}.{j}"
                step_nodes[node_id] = step["_box"]
        for node in nodes:
            if node["kind"] == "card":
                node["y"] = step_nodes[node["id"]][1]
        for icon_inst, (node_id, box) in zip(icons, ((n["id"], step_nodes[n["id"]]) for n in nodes if n["kind"] == "card")):
            icon_inst["y"] = box[1] + 15
        for pulse, (node_id, box) in zip(pulses, ((n["id"], step_nodes[n["id"]]) for n in nodes if n["kind"] == "card")):
            pulse["box"] = [box[0], box[1], box[0] + box[2], box[1] + box[3]]

    # --- edge routing -------------------------------------------------------
    # Horizontal runs live in "corridors" inside the gaps between lane bands;
    # long vertical runs use card-free "gutters". No segment crosses a card or
    # the lane title column, and labels anchor on corridor runs in the gaps.
    def _clean_route(pts):
        out = [tuple(pts[0])]
        for p in pts[1:]:
            if tuple(p) != out[-1]:
                out.append(tuple(p))
        i = 1
        while i < len(out) - 1:
            a, b, c = out[i - 1], out[i], out[i + 1]
            if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
                out.pop(i)
            else:
                i += 1
        return out

    gap_band = []
    for k in range(len(lanes) - 1):
        above_cards = [s["_box"][1] + s["_box"][3] for s in lanes[k]["steps"]]
        below_cards = [s["_box"][1] for s in lanes[k + 1]["steps"]]
        lo = (max(above_cards) if above_cards else lanes[k]["_y"] + 40) + 6
        hi = (min(below_cards) if below_cards else lanes[k + 1]["_y"] + lanes[k + 1]["_h"] - 40) - 6
        gap_band.append((lo, max(hi, lo)))
    gap_used = {}

    def corridor(k):
        """Staggered y slot inside gap k, clear of the card rows above/below."""
        lo, hi = gap_band[k]
        mid = (lo + hi) / 2
        if hi - lo < 10:
            return int(mid)
        n = gap_used.get(k, 0)
        gap_used[k] = n + 1
        seq = (0, -1, 1, -2, 2, -3, 3, -4, 4)
        off = seq[n] * 12 if n < len(seq) else (seq[-1] + n - len(seq) + 1) * 12
        return int(min(hi, max(lo, mid + off)))

    def pick_gutter(la, lb, x_pref):
        """Card-free vertical channel x spanning the lanes between la and lb."""
        lo_lane, hi_lane = min(la, lb), max(la, lb)
        intervals = []
        for li in range(lo_lane + 1, hi_lane):
            for s in lanes[li]["steps"]:
                bx, _, bw, _ = s["_box"]
                intervals.append((bx - 10, bx + bw + 10))
        intervals.sort()
        merged = []
        for iv in intervals:
            if merged and iv[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], iv[1]))
            else:
                merged.append(list(iv))
        x_hi = zone_x + zone_w
        windows, cur = [], float(zone_x)
        for iv in merged:
            if iv[0] > cur:
                windows.append((cur, iv[0]))
            cur = max(cur, iv[1])
        if cur < x_hi:
            windows.append((cur, x_hi))
        if not windows:
            return None
        def keyf(w):
            cen = (w[0] + w[1]) / 2
            return (abs(cen - x_pref), -(w[1] - w[0]))
        best = min(windows, key=keyf)
        return int((best[0] + best[1]) / 2)

    # Port spreading: edges sharing a card face fan out so their stubs never
    # overlap. Faces are decided by the route class (loopback/same/up/down).
    face_edges = {}
    for edge in connections:
        fr, to = edge.get("from"), edge.get("to")
        if fr not in step_nodes or to not in step_nodes:
            continue
        la, lb = step_lane[fr], step_lane[to]
        if is_loopback(edge):
            faces = ("bottom", "bottom")
        elif la == lb:
            right = step_nodes[to][0] > step_nodes[fr][0]
            faces = ("right" if right else "left", "left" if right else "right")
        elif lb > la:
            faces = ("bottom", "top")
        else:
            faces = ("top", "bottom")
        edge["_faces"] = faces
        face_edges.setdefault((fr, faces[0]), []).append(edge)
        face_edges.setdefault((to, faces[1]), []).append(edge)

    def face_spread(edge, nid, face, box):
        peers = face_edges.get((nid, face), [])
        if len(peers) < 2:
            return 0
        k = peers.index(edge)
        limit = (box[2] if face in ("top", "bottom") else box[3]) / 2 - 14
        return int(max(-limit, min(limit, (k - (len(peers) - 1) / 2) * 12)))

    all_boxes = [s["_box"] for lane in lanes for s in lane["steps"]]

    def label_spot(pts):
        """Label rect (x, y, w) anchored on the first horizontal corridor run
        (guaranteed card-free gap); falls back to the longest segment midpoint.
        The y candidate flips below the line when above would hit a card, and
        x is clamped out of the lane title column."""
        anchor, horiz = None, False
        for pa, pb in zip(pts, pts[1:]):
            if pa[1] == pb[1] and abs(pb[0] - pa[0]) > 4:
                anchor = ((pa[0] + pb[0]) / 2, pa[1])
                horiz = True
                break
        if anchor is None:
            anchor, horiz = _swim_edge_anchor(pts)
        mx, my = anchor
        lw = 150 if horiz else 130
        y_cands = [my - 22, my + 6] if horiz else [my - 11]
        for ly in y_cands:
            lx = max(mx - lw / 2, zone_x + 4)
            hit = any(lx < bx + bw and lx + lw > bx and ly < by + bh and ly + 18 > by
                      for (bx, by, bw, bh) in all_boxes)
            if not hit:
                return (int(lx), int(ly), lw)
        return (int(max(mx - lw / 2, zone_x + 4)), int(y_cands[0]), lw)

    for i, edge in enumerate(connections):
        a, b = step_nodes.get(edge.get("from")), step_nodes.get(edge.get("to"))
        if not a or not b:
            continue
        ac = (a[0] + a[2] // 2, a[1] + a[3] // 2)
        bc = (b[0] + b[2] // 2, b[1] + b[3] // 2)
        loopback = is_loopback(edge)
        la, lb = step_lane[edge["from"]], step_lane[edge["to"]]
        if loopback:
            lane = lanes[la]
            channel_y = lane["_y"] + lane["_h"] - 16
            s_off = face_spread(edge, edge["from"], "bottom", a)
            t_off = face_spread(edge, edge["to"], "bottom", b)
            p1 = (ac[0] + s_off, a[1] + a[3])
            p2 = (bc[0] + t_off, b[1] + b[3])
            pts = [p1, (p1[0], channel_y), (p2[0], channel_y), p2]
            style = edge.get("style", "dashed")
            color = edge.get("color", "muted")
        elif la == lb:
            right = bc[0] > ac[0]
            s_off = face_spread(edge, edge["from"], "right" if right else "left", a)
            t_off = face_spread(edge, edge["to"], "left" if right else "right", b)
            p1 = (a[0] + a[2] if right else a[0], ac[1] + s_off)
            p2 = (b[0] if right else b[0] + b[2], bc[1] + t_off)
            if abs(p1[1] - p2[1]) < 6:
                pts = [p1, p2]
            else:
                mid = (p1[0] + p2[0]) // 2
                pts = [p1, (mid, p1[1]), (mid, p2[1]), p2]
            style = edge.get("style", "solid")
            color = edge.get("color", "muted")
        else:
            # Cross-band link: exit with the flow (bottom going down, top going
            # up), ride the staggered corridor in the gap, and drop through a
            # card-free gutter when skipping lanes — never through cards.
            down = lb > la
            s_off = face_spread(edge, edge["from"], "bottom" if down else "top", a)
            t_off = face_spread(edge, edge["to"], "top" if down else "bottom", b)
            p1 = (ac[0] + s_off, a[1] + a[3] if down else a[1])
            p2 = (bc[0] + t_off, b[1] if down else b[1] + b[3])
            cy1 = corridor(la if down else la - 1)
            if abs(lb - la) == 1:
                if abs(p1[0] - p2[0]) <= 10:
                    # Near-aligned neighbors: straight line at the entry port
                    # (a micro-jog from port spreading reads as a defect).
                    pts = [(p2[0], p1[1]), p2]
                else:
                    pts = [p1, (p1[0], cy1), (p2[0], cy1), p2]
            else:
                gx = pick_gutter(la, lb, (ac[0] + bc[0]) / 2)
                if gx is None:
                    gx = min(zone_x + zone_w + 14, lane_x + lane_w - 10)
                cy2 = corridor(lb - 1 if down else lb)
                pts = [p1, (p1[0], cy1), (gx, cy1), (gx, cy2), (p2[0], cy2), p2]
            style = edge.get("style", "solid")
            color = edge.get("color", "muted")
        pts = [(round(px), round(py)) for px, py in pts]
        pts = [list(p) for p in _clean_route(pts)]
        rec = {"id": f"e.swim.{i}", "from": edge["from"], "to": edge["to"], "points": pts,
               "color": color, "label": edge.get("label"), "badge": edge.get("badge"),
               "style": style, "loop": loopback}
        if edge.get("label") and not loopback:
            rec["label_pos"] = label_spot(pts)
        edges.append(rec)
        flow.append({"points": [list(p) for p in pts], "color": edge.get("accent", "green"),
                     "offset": i / max(1, len(connections))})

    last = lanes[-1]
    height = last["_y"] + last["_h"] + 62
    if spec.get("legend"):
        height += 34  # reserve a strip for the legend row above the frame
    return {"layout": "swimlane", "canvas": {"width": width, "height": height}, "frame": (18, 117, width - 36, height - 144),
            "lanes": {"x": lane_x, "w": lane_w, "ys": ys, "items": lanes, "column_w": SWIMLANE_COLUMN_W},
            "glow_rects": [{"box": [18, 117, width - 18, height - 27], "color": "frame", "light": "frame", "width": 3}],
            "flow_paths": flow, "pulse_targets": pulses, "icons": icons, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Grid (catalog of mini-flow panels: 2-9 cells in 2-3 columns)
# ---------------------------------------------------------------------------

def plan_grid(spec):
    """Panel catalog: each cell is a titled mini flow of 1-6 step chips.

    Rows share a fixed column count; a short last row is centered, which
    reproduces the classic 3+3+2 catalog arrangement at 8 cells."""
    spec = spec or {}
    cells = [dict(c) for c in spec.get("cells", [])][:9]
    while len(cells) < 2:
        cells.append({"title": "", "steps": []})
    canvas_spec = spec.get("canvas") or {}
    width = int(canvas_spec.get("width") or 1210)
    n = len(cells)
    cols = int(spec.get("columns") or (3 if n > 4 else 2))
    cols = max(2, min(3, cols))
    margin_x, gap_x, gap_y, top = 55, 24, 24, 190
    cell_w = (width - 2 * margin_x - (cols - 1) * gap_x) // cols
    cell_h = 204
    nodes, edges, flow, pulses, icons = [], [], [], [], []
    ordinal = 0

    for i, cell in enumerate(cells):
        cell["_tint"] = _swimlane_tint(cell, i)
        row, col = divmod(i, cols)
        row_count = min(cols, n - row * cols)
        row_w = row_count * cell_w + (row_count - 1) * gap_x
        x0 = (width - row_w) // 2
        cx, cy = x0 + col * (cell_w + gap_x), top + row * (cell_h + gap_y)
        cell["_box"] = (cx, cy, cell_w, cell_h)
        nodes.append(_node(f"cell.{i}", "group", cx, cy, cell_w, cell_h, label=cell.get("title", "")))
        steps = [
            (dict(s) if isinstance(s, dict) else {"label": str(s)})
            for s in cell.get("steps", [])
        ][:6]
        cell["steps"] = steps
        zone_x, zone_w = cx + 14, cell_w - 28
        count = max(1, len(steps))
        card_w = min(118, int((zone_w - (count - 1) * 14) / count))
        card_h = 88
        total = count * card_w + (count - 1) * 14
        sx = zone_x + (zone_w - total) // 2
        sy = cy + cell_h - card_h - 18
        prev_box = None
        for j, step in enumerate(steps):
            box = (sx, sy, card_w, card_h)
            step["_box"] = box
            node_id = step.get("id") or f"cell.{i}.{j}"
            step["_id"] = node_id
            nodes.append(_node(node_id, "card", *box, label=step.get("title", ""),
                               icon=step.get("icon", "file"), group=f"cell.{i}"))
            icons.append(_icon(step.get("icon", "file"), sx + (card_w - 50) // 2, sy + 8,
                               step.get("color"), "grid", ordinal))
            ordinal += 1
            pulses.append({"box": [sx, sy, sx + card_w, sy + card_h], "color": cell["_tint"]["stroke"]})
            if prev_box is not None:
                ymid = sy + card_h // 2
                pts = [(prev_box[0] + prev_box[2], ymid), (sx, ymid)]
                edges.append({"id": f"e.grid.{i}.{j}", "from": prev_id, "to": node_id,
                              "points": pts, "color": "muted", "label": None, "style": "solid", "loop": False})
                flow.append({"points": [list(p) for p in pts], "color": cell["_tint"]["stroke"],
                             "offset": round(i / max(1, n), 4)})
            prev_box = box
            prev_id = node_id
            sx += card_w + 14

    rows = math.ceil(n / cols)
    height = top + rows * cell_h + (rows - 1) * gap_y + 62
    if spec.get("legend"):
        height += 34  # reserve a strip for the legend row above the frame
    return {"layout": "grid", "canvas": {"width": width, "height": height},
            "frame": (18, 117, width - 36, height - 144),
            "grid": {"items": cells, "columns": cols},
            "glow_rects": [{"box": [18, 117, width - 18, height - 27], "color": "frame", "light": "frame", "width": 3}],
            "flow_paths": flow, "pulse_targets": pulses, "icons": icons, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Graph (free-form workflow: nodes + edges, auto DAG layout, loop channels)
# ---------------------------------------------------------------------------

GRAPH_STROKES = ["core_stroke", "green", "purple", "amber", "cyan", "pink"]
GRAPH_LOOP_STROKES = ["purple", "pink", "amber"]
GRAPH_FILLS = {"core_stroke": "blue_fill", "green": "green_fill", "purple": "purple_fill",
               "amber": "icon_fill", "pink": "icon_fill", "cyan": "blue_fill"}
GRAPH_NODE_KINDS = ("card", "decision", "terminal", "circle", "person", "database", "document")
# Sizes for the figurative kinds (person/database/document): fixed so the
# hand-drawn figures keep their proportions at any graph scale.
PERSON_SIZE = (112, 108)
DATABASE_SIZE = (128, 88)
# THEME keys accepted for node/edge "accent" (flow beams + pulses resolve
# these through the active style's palette).
GRAPH_ACCENTS = {"core_stroke", "green", "purple", "amber", "cyan", "pink", "white", "muted"}


def _graph_accent(item, fallback):
    accent = (item or {}).get("accent")
    return accent if accent in GRAPH_ACCENTS else fallback


def _graph_prepare(spec):
    """Normalize nodes/edges: unique string ids, drop dangling edges, flag loops.

    Loop edges are either declared (kind: "loop") or detected back edges: any
    forward edge that would close a cycle is treated as a loop so the layered
    layout never breaks, whatever topology the caller sends.
    """
    raw_nodes = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:24]
    if not raw_nodes:
        raw_nodes = [{"id": "a", "label": "Step A"}, {"id": "b", "label": "Step B"}]
    seen = set()
    for i, node in enumerate(raw_nodes):
        nid = str(node.get("id") or f"n{i}")
        while nid in seen:
            nid += "_"
        node["id"] = nid
        seen.add(nid)
    by_id = {n["id"]: n for n in raw_nodes}

    raw_edges = [dict(e) for e in (spec.get("edges") or []) if isinstance(e, dict)]
    raw_edges = [e for e in raw_edges if e.get("from") in by_id and e.get("to") in by_id][:40]
    for edge in raw_edges:
        edge["_loop"] = edge.get("kind") == "loop" or edge["from"] == edge["to"]

    # Detect remaining back edges (DFS in declaration order, forward edges only).
    out = {nid: [] for nid in by_id}
    for edge in raw_edges:
        if not edge["_loop"]:
            out[edge["from"]].append(edge)
    state = {nid: 0 for nid in by_id}  # 0 new, 1 on stack, 2 done

    def visit(nid):
        state[nid] = 1
        for edge in out[nid]:
            if edge["_loop"]:
                continue  # pragma: no cover - loop edges are excluded from out[] when built
            nxt = edge["to"]
            if state[nxt] == 1:
                edge["_loop"] = True
            elif state[nxt] == 0:
                visit(nxt)
        state[nid] = 2

    for node in raw_nodes:
        if state[node["id"]] == 0:
            visit(node["id"])
    return raw_nodes, raw_edges, by_id


def _graph_layers(raw_nodes, raw_edges, by_id):
    """Longest-path layer per node + barycenter row order within each layer."""
    forward = [e for e in raw_edges if not e["_loop"]]
    indeg = {n["id"]: 0 for n in raw_nodes}
    out = {n["id"]: [] for n in raw_nodes}
    preds = {n["id"]: [] for n in raw_nodes}
    for e in forward:
        out[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
        preds[e["to"]].append(e["from"])

    layer = {}
    ready = [n["id"] for n in raw_nodes if indeg[n["id"]] == 0]
    for nid in ready:
        layer[nid] = 0
    pending = dict(indeg)
    while ready:
        nid = ready.pop(0)
        for nxt in out[nid]:
            layer[nxt] = max(layer.get(nxt, 0), layer[nid] + 1)
            pending[nxt] -= 1
            if pending[nxt] == 0:
                ready.append(nxt)
    for n in raw_nodes:  # safety: anything untouched sits at layer 0
        layer.setdefault(n["id"], 0)

    manual = {n["id"] for n in raw_nodes if isinstance(n.get("x"), (int, float)) and isinstance(n.get("y"), (int, float))}
    order_index = {n["id"]: i for i, n in enumerate(raw_nodes)}
    cols = {}
    for n in raw_nodes:
        if n["id"] not in manual:
            cols.setdefault(layer[n["id"]], []).append(n["id"])
    for l in cols:
        cols[l].sort(key=lambda nid: order_index[nid])
    for _ in range(2):
        for l in sorted(cols):
            if l - 1 not in cols:
                continue
            prev_row = {nid: r for r, nid in enumerate(cols[l - 1])}
            cur_row = {nid: r for r, nid in enumerate(cols[l])}

            def key(nid):
                ps = [prev_row[p] for p in preds[nid] if p in prev_row]
                return sum(ps) / len(ps) if ps else float(cur_row[nid])

            cols[l].sort(key=key)
    return layer, cols, manual


def _plan_graph_elk(spec, raw_nodes, raw_edges, by_id, layer, cols, manual):
    """ELK Layered layout for the ``graph`` layout.

    Produces a plan dict with the exact same shape as the legacy ``plan_graph``
    so every downstream consumer (render_graph, svg_renderer, --check, the
    interactive HTML) works unchanged. Coordinates come from ELK; everything
    else (accent assignment, group boxes, flow paths, pulse targets, meta) is
    derived exactly like the legacy path.

    Returns None when ELK / Playwright / Chromium is unavailable so the caller
    falls back to the stdlib legacy layout.
    """
    import elk_layout  # lazy: keeps graph_model stdlib-only at import time
    requested_direction = spec.get("direction", "right")
    horizontal = requested_direction != "down"
    n_layers = (max(cols) + 1) if cols else 1
    loops = [e for e in raw_edges if e["_loop"]]

    # --- node sizing + layout envelope (mirrors legacy so content fits) ---
    has_body = any(n.get("body") for n in raw_nodes if n.get("kind", "card") == "card")
    card_h = 96 if has_body else 78
    icon_present = any(n.get("icon") for n in raw_nodes)
    if horizontal:
        u_lo, u_hi = 60, 1150
        gap_u = 70 if n_layers <= 4 else 56 if n_layers <= 6 else 46
        cu = min(210, max(120, (u_hi - u_lo - (n_layers - 1) * gap_u) / n_layers))
        total_u = n_layers * cu + (n_layers - 1) * gap_u
        off_x = u_lo + max(0, (u_hi - u_lo - total_u) / 2)
        between_layers = int(gap_u)
        card_w = int(cu)
        card_h = max(card_h, 100 if (icon_present and cu < 150) else card_h)
    else:
        off_x = 60
        between_layers = 64
        card_w = 172
    # off_y clears the 117px title band with headroom for the dashed group
    # container, whose label sits 34px above its topmost member node.
    off_y = 165

    node_specs, size_map = [], {}
    for n in raw_nodes:
        kind = n.get("kind", "card")
        if kind not in GRAPH_NODE_KINDS:
            kind = "card"
        if kind == "decision":
            side = max(108, min(card_w, 132))
            w, h = side, side
        elif kind == "terminal":
            w, h = min(card_w, 122), 66
        elif kind == "circle":
            w = h = 96
        elif kind == "person":
            w, h = PERSON_SIZE
        elif kind == "database":
            w, h = DATABASE_SIZE
        elif kind == "document":
            w, h = card_w, max(72, card_h - 20)
        else:
            w, h = card_w, card_h
        node_specs.append({"id": n["id"], "w": w, "h": h})
        size_map[n["id"]] = (w, h, kind)

    edge_specs = [{"id": f"e{i}", "from": e["from"], "to": e["to"]}
                  for i, e in enumerate(raw_edges)]
    result = elk_layout.layout_graph(node_specs, edge_specs, requested_direction,
                                     spacing=max(40, int(card_h * 0.55)))
    if result is None:
        return None
    # ELK lays out from (0,0). Shift the content so it is centered within the
    # canvas frame whatever width ELK produces (prevents right-edge clipping).
    if result["nodes"]:
        elk_xs = [x for (x, _y, _w, _h) in result["nodes"].values()]
        elk_xr = [x + w for (x, _y, w, _h) in result["nodes"].values()]
        elk_min_x, elk_max_x = min(elk_xs), max(elk_xr)
        pad = 30
        content_w = elk_max_x - elk_min_x
        off_x = pad + max(0, (CANVAS_W - 2 * pad - content_w) / 2) - elk_min_x
    # off_y keeps the title band (117px) clear with breathing room.

    # --- node boxes -------------------------------------------------------
    gnodes, boxes = [], {}
    for n in raw_nodes:
        nid = n["id"]
        ex, ey, ew, eh = result["nodes"].get(nid, (0, 0, 172, card_h))
        if nid in manual:  # author-pinned nodes keep their coordinates
            bx, by = float(n["x"]), float(n["y"])
            w = size_map[nid][0]
            h = size_map[nid][1]
        else:
            bx, by = ex + off_x, ey + off_y
            w, h = ew, eh
        box = (round(bx), round(by), int(w), int(h))
        kind = size_map[nid][2]
        accent = _graph_accent(n, GRAPH_STROKES[layer[nid] % len(GRAPH_STROKES)])
        record = dict(n)
        record.update({"_box": box, "_kind": kind, "_accent": accent,
                       "_fill": GRAPH_FILLS.get(accent, "icon_fill"),
                       "_center": (bx + w / 2, by + h / 2)})
        gnodes.append(record)
        boxes[nid] = box

    # --- edge routes from ELK sections ------------------------------------
    gedges, flow = [], []
    loop_i = 0
    for i, e in enumerate(raw_edges):
        eid = f"e{i}"
        raw_pts = result["edges"].get(eid, [])
        if len(raw_pts) < 2:  # fallback: center-to-center straight line
            sx, sy, sw, sh = boxes[e["from"]]
            dx, dy, dw, dh = boxes[e["to"]]
            raw_pts = [[sx + sw / 2, sy + sh / 2], [dx + dw / 2, dy + dh / 2]]
        pts = [(round(p[0] + off_x), round(p[1] + off_y)) for p in raw_pts]
        if e["_loop"]:
            accent = _graph_accent(e, GRAPH_LOOP_STROKES[loop_i % len(GRAPH_LOOP_STROKES)])
            color = e.get("color", "muted")
            style = "dashed"
            offset = 0.80 if len(loops) <= 1 else 0.78 + 0.18 * loop_i / (len(loops) - 1)
            loop_i += 1
        else:
            src_accent = next((g["_accent"] for g in gnodes if g["id"] == e["from"]), "core_stroke")
            accent = _graph_accent(e, src_accent)
            color = e.get("color", "white")
            style = e.get("style", "solid")
            offset = 0.66 * layer[e["from"]] / max(n_layers, 1)
        gedges.append({"id": f"e.{i}.{e['from']}_{e['to']}", "from": e["from"], "to": e["to"],
                       "points": pts, "color": color, "label": e.get("label"),
                       "badge": e.get("badge"), "style": style, "loop": e["_loop"]})
        flow.append({"points": [list(p) for p in pts], "color": accent, "offset": round(offset, 4)})

    # --- group containers (1-level nesting) -------------------------------
    graph_groups = []
    for grp in (spec.get("groups") or [])[:4]:
        if not isinstance(grp, dict):
            continue
        members = [g for g in gnodes if g.get("parent") == grp.get("id")]
        if not members:
            continue
        x0 = min(g["_box"][0] for g in members) - 18
        y0 = min(g["_box"][1] for g in members) - 34
        x1 = max(g["_box"][0] + g["_box"][2] for g in members) + 18
        y1 = max(g["_box"][1] + g["_box"][3] for g in members) + 18
        graph_groups.append({"id": grp.get("id"), "label": grp.get("label", ""),
                             "box": (round(x0), round(y0), round(x1 - x0), round(y1 - y0))})

    # --- public nodes / icons / pulse targets -----------------------------
    nodes_out, icons, pulses = [], [], []
    ordinal = 0
    for g in gnodes:
        x, y, w, h = g["_box"]
        nodes_out.append(_node(g["id"], g["_kind"], x, y, w, h, label=g.get("label", ""),
                               icon=g.get("icon"), group=None, link=g.get("link")))
        pulses.append({"box": [x, y, x + w, y + h], "color": g["_accent"]})
        if g["_kind"] == "card" and g.get("icon"):
            narrow = w < 150
            ix = x + (w - 50) // 2 if narrow else x + 12
            iy = y + 8 if narrow else y + (h - 50) // 2
            g["_icon_xy"] = (ix, iy)
            icons.append(_icon(g["icon"], ix, iy, g.get("color"), "graph", ordinal))
            ordinal += 1

    # --- canvas height (hug content, floor 400, reserve footer/legend) ----
    bottoms = [b[1] + b[3] for b in boxes.values()]
    bottoms += [grp["box"][1] + grp["box"][3] for grp in graph_groups]
    content_bottom = max(bottoms, default=400)
    # Account for any edge that routes below the lowest box (ELK sometimes does).
    edge_bottom = max((p[1] for edge in gedges for p in edge["points"]), default=0)
    content_bottom = max(content_bottom, edge_bottom)
    if spec.get("footer"):
        content_bottom += 30
    if spec.get("legend"):
        content_bottom += 34
    height = max(400, int(content_bottom) + 120)
    frame = (18, 117, 1174, height - 144)
    glow = [{"box": [18, 117, 1192, height - 27], "color": "frame", "light": "frame", "width": 3},
            {"box": [600, 27, 992, 99], "color": "green", "light": "pink", "width": 2}]

    return {
        "layout": "graph",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "graph_nodes": gnodes,
        "graph_edges": gedges,
        "graph_groups": graph_groups,
        "graph_meta": {"layers": layer, "n_layers": n_layers, "horizontal": horizontal,
                       "requested_direction": requested_direction, "auto_stacked": False,
                       "loops": len(loops), "skips": 0, "card_h": card_h,
                       "layout_engine": "elk"},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": icons,
        "nodes": nodes_out,
        "edges": gedges,
    }


def plan_graph(spec):
    spec = spec or {}
    engine = (spec.get("layout_engine") or "elk").lower()
    requested_direction = spec.get("direction", "right")
    raw_nodes, raw_edges, by_id = _graph_prepare(spec)
    layer, cols, manual = _graph_layers(raw_nodes, raw_edges, by_id)
    if engine == "elk":
        elk_result = _plan_graph_elk(spec, raw_nodes, raw_edges, by_id, layer, cols, manual)
        if elk_result is not None:
            return elk_result
        # ELK unavailable or failed — fall through to the legacy layout.
    horizontal = requested_direction != "down"
    n_layers = (max(cols) + 1) if cols else 1
    auto_stacked = False
    if horizontal and n_layers > 7 and not manual:
        horizontal = False
        auto_stacked = True

    loops = [e for e in raw_edges if e["_loop"]]
    skips = [e for e in raw_edges if not e["_loop"] and e["from"] not in manual and e["to"] not in manual
             and layer[e["to"]] - layer[e["from"]] >= 2]
    lane_pitch = 36

    has_body = any(n.get("body") for n in raw_nodes if n.get("kind", "card") == "card")
    card_h = 96 if has_body else 78

    # Grid geometry along the flow axis (u) and the cross axis (v). For
    # direction "right": u = x, v = y (loops below, skips above). For
    # direction "down": u = y, v = x (loops right, skips left).
    if horizontal:
        u_lo, u_hi = 60, 1150
        gap_u = 70 if n_layers <= 4 else 56 if n_layers <= 6 else 46
        cu = min(210, max(120, (u_hi - u_lo - (n_layers - 1) * gap_u) / n_layers))
        total_u = n_layers * cu + (n_layers - 1) * gap_u
        u0 = u_lo + (u_hi - u_lo - total_u) / 2
        if cu < 150 and any(n.get("icon") for n in raw_nodes):
            # Narrow cards stack icon above label and need the extra height.
            card_h = max(card_h, 100)
        cv, gap_v = card_h, 52
        v_lo = 190 + (len(skips) * lane_pitch + 16 if skips else 0)
    else:
        cu, gap_u = card_h, 64
        u0 = 190
        max_rows = max((len(v) for v in cols.values()), default=1)
        v_left = 60 + (len(skips) * lane_pitch + 14 if skips else 0)
        v_right = 1150 - (len(loops) * lane_pitch + 14 if loops else 0)
        gap_v = 40
        cv = min(210, max(130, (v_right - v_left - (max_rows - 1) * gap_v) / max_rows))
        v_lo = v_left

    max_rows_all = max((len(v) for v in cols.values()), default=1)
    grid_span_v = max_rows_all * cv + (max_rows_all - 1) * gap_v
    if not horizontal:
        # The canvas width is fixed, so center the grid between the side lanes.
        v_lo = v_left + max(0, (v_right - v_left - grid_span_v) / 2)

    def cell_center(col, row, rows_in_col):
        span = rows_in_col * cv + (rows_in_col - 1) * gap_v
        u_c = u0 + col * (cu + gap_u) + cu / 2
        v_c = v_lo + (grid_span_v - span) / 2 + row * (cv + gap_v) + cv / 2
        return u_c, v_c

    def to_xy(u, v):
        return (u, v) if horizontal else (v, u)

    # --- node boxes ---------------------------------------------------------
    card_w_xy = cu if horizontal else cv
    card_h_xy = cv if horizontal else cu
    gnodes = []
    boxes = {}
    for n in raw_nodes:
        kind = n.get("kind", "card")
        if kind not in GRAPH_NODE_KINDS:
            kind = "card"
        if n["id"] in manual:
            cx, cy = float(n["x"]), float(n["y"])
        else:
            col = layer[n["id"]]
            row = cols[col].index(n["id"])
            u_c, v_c = cell_center(col, row, len(cols[col]))
            cx, cy = to_xy(u_c, v_c)
        if kind == "decision":
            side = min(card_w_xy, card_h_xy) + 22
            box = (cx - side / 2, cy - side / 2, side, side)
        elif kind == "terminal":
            box = (cx - card_w_xy * 0.42, cy - card_h_xy * 0.36, card_w_xy * 0.84, card_h_xy * 0.72)
        elif kind == "person":
            pw, ph = PERSON_SIZE
            box = (cx - pw / 2, cy - ph / 2, pw, ph)
        elif kind == "database":
            dw, dh = DATABASE_SIZE
            box = (cx - dw / 2, cy - dh / 2, dw, dh)
        elif kind == "document":
            dw = card_w_xy
            dh = max(72, card_h_xy - 20)
            box = (cx - dw / 2, cy - dh / 2, dw, dh)
        else:
            box = (cx - card_w_xy / 2, cy - card_h_xy / 2, card_w_xy, card_h_xy)
        box = tuple(round(v) for v in box)
        accent = _graph_accent(n, GRAPH_STROKES[layer[n["id"]] % len(GRAPH_STROKES)])
        record = dict(n)
        record.update({"_box": box, "_kind": kind, "_accent": accent,
                       "_fill": GRAPH_FILLS.get(accent, "icon_fill"), "_center": (cx, cy)})
        gnodes.append(record)
        boxes[n["id"]] = box

    # --- edge routing --------------------------------------------------------
    def port(box, side, offset=0.0):
        x, y, w, h = box
        if side == "left":
            return (x, y + h / 2 + offset)
        if side == "right":
            return (x + w, y + h / 2 + offset)
        if side == "top":
            return (x + w / 2 + offset, y)
        return (x + w / 2 + offset, y + h)  # bottom

    for e in raw_edges:
        if e["_loop"]:
            e["_class"] = "loop"
        elif e["from"] in manual or e["to"] in manual:
            e["_class"] = "manual"
        elif layer[e["to"]] - layer[e["from"]] >= 2:
            e["_class"] = "skip"
        else:
            e["_class"] = "straight"

    out_seq, in_seq = {}, {}
    for e in raw_edges:
        out_seq.setdefault(e["from"], []).append(e)
        in_seq.setdefault(e["to"], []).append(e)

    def spread(edge, seq_map, nid):
        # Only edges leaving/entering through the same face compete for the
        # port; loops use the bottom/right face, skips the top/left one, etc.
        peers = [p for p in seq_map.get(nid, []) if p["_class"] == edge["_class"]]
        if len(peers) < 2:
            return 0.0
        k = next(j for j, p in enumerate(peers) if p is edge)
        return (k - (len(peers) - 1) / 2) * 14

    # Vertical (cross-axis) segments in a column gap fan out so parallel
    # edges never overlap; count them per gap first.
    gap_traffic, gap_seen = {}, {}
    for e in raw_edges:
        if e["_loop"] or e["from"] in manual or e["to"] in manual:
            continue
        if layer[e["to"]] - layer[e["from"]] == 1:
            gap_traffic[layer[e["from"]]] = gap_traffic.get(layer[e["from"]], 0) + 1

    def elbow(a, b):
        """Generic orthogonal connector between two free boxes (manual nodes)."""
        ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
        bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
        if abs(by - ay) > abs(bx - ax):
            down = by > ay
            p1 = (ax, a[1] + a[3] if down else a[1])
            p2 = (bx, b[1] if down else b[1] + b[3])
            mid = (p1[1] + p2[1]) / 2
            return [p1, (p1[0], mid), (p2[0], mid), p2]
        right = bx > ax
        p1 = (a[0] + a[2] if right else a[0], ay)
        p2 = (b[0] if right else b[0] + b[2], by)
        mid = (p1[0] + p2[0]) / 2
        return [p1, (mid, p1[1]), (mid, p2[1]), p2]

    grid_v_hi = v_lo + grid_span_v
    if horizontal:
        # Lanes must clear every box, including manually placed ones.
        loop_lane_v = max([grid_v_hi] + [b[1] + b[3] for b in boxes.values()]) + 46
        skip_lane_v = 190 + 10
    else:
        loop_lane_v = max(1150 - len(loops) * lane_pitch + 8,
                          max(b[0] + b[2] for b in boxes.values()) + 26)
        skip_lane_v = 60 + 10

    gedges, flow, loop_i, skip_i = [], [], 0, 0
    for i, e in enumerate(raw_edges):
        src, dst = boxes[e["from"]], boxes[e["to"]]
        label = e.get("label")
        if e["_loop"]:
            lane = loop_lane_v + loop_i * lane_pitch
            loop_i += 1
            if e["from"] == e["to"]:
                s_off, t_off = 20, -20
            else:
                s_off, t_off = spread(e, out_seq, e["from"]), spread(e, in_seq, e["to"])
            if horizontal:
                p1, p4 = port(src, "bottom", s_off), port(dst, "bottom", t_off)
                pts = [p1, (p1[0], lane), (p4[0], lane), p4]
            else:
                p1, p4 = port(src, "right", s_off), port(dst, "right", t_off)
                pts = [p1, (lane, p1[1]), (lane, p4[1]), p4]
            accent = _graph_accent(e, GRAPH_LOOP_STROKES[(loop_i - 1) % len(GRAPH_LOOP_STROKES)])
            color, style = e.get("color", "muted"), "dashed"
            n_loops = max(1, len(loops))
            offset = 0.80 if n_loops == 1 else 0.78 + 0.18 * (loop_i - 1) / (n_loops - 1)
        elif e["from"] in manual or e["to"] in manual:
            pts = elbow(src, dst)
            accent = _graph_accent(e, next(g["_accent"] for g in gnodes if g["id"] == e["from"]))
            color, style = e.get("color", "white"), e.get("style", "solid")
            offset = 0.66 * layer[e["from"]] / n_layers
        elif layer[e["to"]] - layer[e["from"]] >= 2:
            lane = skip_lane_v + skip_i * lane_pitch
            skip_i += 1
            s_off, t_off = spread(e, out_seq, e["from"]), spread(e, in_seq, e["to"])
            if horizontal:
                p1, p4 = port(src, "top", s_off), port(dst, "top", t_off)
                pts = [p1, (p1[0], lane), (p4[0], lane), p4]
            else:
                p1, p4 = port(src, "left", s_off), port(dst, "left", t_off)
                pts = [p1, (lane, p1[1]), (lane, p4[1]), p4]
            accent = _graph_accent(e, next(g["_accent"] for g in gnodes if g["id"] == e["from"]))
            color, style = e.get("color", "white"), e.get("style", "solid")
            offset = 0.66 * layer[e["from"]] / n_layers
        else:
            s_off, t_off = spread(e, out_seq, e["from"]), spread(e, in_seq, e["to"])
            gap_col = layer[e["from"]]
            seen = gap_seen.get(gap_col, 0)
            gap_seen[gap_col] = seen + 1
            m = gap_traffic.get(gap_col, 1)
            mid_off = (seen - (m - 1) / 2) * 12
            if horizontal:
                p1, p4 = port(src, "right", s_off), port(dst, "left", t_off)
                if abs(p1[1] - p4[1]) < 3 and layer[e["to"]] > layer[e["from"]]:
                    pts = [p1, p4]
                elif layer[e["to"]] == layer[e["from"]]:
                    pts = elbow(src, dst)  # pragma: no cover - longest-path layering keeps to-layer > from-layer
                else:
                    mid = (p1[0] + p4[0]) / 2 + mid_off
                    pts = [p1, (mid, p1[1]), (mid, p4[1]), p4]
            else:
                p1, p4 = port(src, "bottom", s_off), port(dst, "top", t_off)
                if abs(p1[0] - p4[0]) < 3 and layer[e["to"]] > layer[e["from"]]:
                    pts = [p1, p4]
                elif layer[e["to"]] == layer[e["from"]]:
                    pts = elbow(src, dst)  # pragma: no cover - longest-path layering keeps to-layer > from-layer
                else:
                    mid = (p1[1] + p4[1]) / 2 + mid_off
                    pts = [p1, (p1[0], mid), (p4[0], mid), p4]
            accent = _graph_accent(e, next(g["_accent"] for g in gnodes if g["id"] == e["from"]))
            color, style = e.get("color", "white"), e.get("style", "solid")
            offset = 0.66 * layer[e["from"]] / n_layers

        pts = [(round(px), round(py)) for px, py in pts]
        gedges.append({"id": f"e.{i}.{e['from']}_{e['to']}", "from": e["from"], "to": e["to"],
                       "points": pts, "color": color, "label": label, "badge": e.get("badge"),
                       "style": style, "loop": e["_loop"]})
        flow.append({"points": [list(p) for p in pts], "color": accent, "offset": round(offset, 4)})

    # --- plan assembly --------------------------------------------------------
    # Nested group boxes: spec "groups": [{"id", "label"}] referenced by node
    # "parent"; rendered as a dashed container around member nodes (1 level).
    graph_groups = []
    for grp in (spec.get("groups") or [])[:4]:
        if not isinstance(grp, dict):
            continue
        members = [g for g in gnodes if g.get("parent") == grp.get("id")]
        if not members:
            continue
        x0 = min(g["_box"][0] for g in members) - 18
        y0 = min(g["_box"][1] for g in members) - 34
        x1 = max(g["_box"][0] + g["_box"][2] for g in members) + 18
        y1 = max(g["_box"][1] + g["_box"][3] for g in members) + 18
        graph_groups.append({"id": grp.get("id"), "label": grp.get("label", ""),
                             "box": (round(x0), round(y0), round(x1 - x0), round(y1 - y0))})

    nodes, icons, pulses = [], [], []
    ordinal = 0
    for g in gnodes:
        x, y, w, h = g["_box"]
        nodes.append(_node(g["id"], g["_kind"], x, y, w, h, label=g.get("label", ""),
                           icon=g.get("icon"), group=None, link=g.get("link")))
        pulses.append({"box": [x, y, x + w, y + h], "color": g["_accent"]})
        if g["_kind"] == "card" and g.get("icon"):
            narrow = w < 150
            ix = x + (w - 50) // 2 if narrow else x + 12  # icon tile is 50px
            iy = y + 8 if narrow else y + (h - 50) // 2
            g["_icon_xy"] = (ix, iy)
            icons.append(_icon(g["icon"], ix, iy, g.get("color"), "graph", ordinal))
            ordinal += 1

    if horizontal:
        content_bottom = max([grid_v_hi] + [b[1] + b[3] for b in boxes.values()]
                             + [g["box"][1] + g["box"][3] for g in graph_groups])
        if loops:
            content_bottom = max(content_bottom, loop_lane_v + (len(loops) - 1) * lane_pitch)
    else:
        content_bottom = max([u0 + n_layers * (cu + gap_u) - gap_u] + [b[1] + b[3] for b in boxes.values()])
    if spec.get("footer"):
        content_bottom += 30
    if spec.get("legend"):
        content_bottom += 34  # reserve a strip for the legend row above the frame
    # Floor + bottom padding keep the frame clear of content (the output
    # contract asks for ~96px of clearance) while hugging shallow graphs so a
    # single-row chain doesn't render on a half-empty tall canvas.
    height = max(400, int(content_bottom) + 120)
    frame = (18, 117, 1174, height - 144)
    glow = [{"box": [18, 117, 1192, height - 27], "color": "frame", "light": "frame", "width": 3},
            {"box": [600, 27, 992, 99], "color": "green", "light": "pink", "width": 2}]

    return {
        "layout": "graph",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "graph_nodes": gnodes,
        "graph_edges": gedges,
        "graph_groups": graph_groups,
        "graph_meta": {"layers": layer, "n_layers": n_layers, "horizontal": horizontal,
                       "requested_direction": requested_direction, "auto_stacked": auto_stacked,
                       "loops": len(loops), "skips": len(skips), "card_h": card_h},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": icons,
        "nodes": nodes,
        "edges": gedges,
    }


# ---------------------------------------------------------------------------
# Sequence (UML sequence diagram: participant heads + dashed lifelines,
# sync/async/return/self messages, auto activation bars, notes, and
# alt/loop/opt combined fragments). Canvas width is fixed like graph; the
# height grows with the message count.
# ---------------------------------------------------------------------------

SEQUENCE_MESSAGE_KINDS = ("sync", "async", "return", "self", "note")
SEQUENCE_FRAGMENT_KINDS = ("alt", "loop", "opt")
SEQUENCE_PARTICIPANT_KINDS = ("actor", "system")
SEQUENCE_ACCENTS = GRAPH_ACCENTS
SEQUENCE_HEAD_W = 168
SEQUENCE_HEAD_H = 64
SEQUENCE_HEAD_Y = 168
_SEQUENCE_PITCH = 68          # vertical rhythm per plain message row
_SEQUENCE_ACCENT_CYCLE = ["green", "purple", "amber", "cyan", "pink", "core_stroke"]


def _sequence_prepare(spec):
    """Normalize participants/messages/fragments; every reference is resolved
    to a declared participant so the painter never deals with dangling ids."""
    participants = [dict(p) for p in (spec.get("participants") or []) if isinstance(p, dict)][:8]
    while len(participants) < 2:
        participants.append({"id": f"p{len(participants)}", "label": ""})
    by_id, order = {}, []
    for i, p in enumerate(participants):
        pid = str(p.get("id") or f"p{i}")
        while pid in by_id:
            pid += "_"
        p["id"] = pid
        p["kind"] = p.get("kind") if p.get("kind") in SEQUENCE_PARTICIPANT_KINDS else "system"
        accent = p.get("accent")
        p["_accent"] = accent if accent in SEQUENCE_ACCENTS else _SEQUENCE_ACCENT_CYCLE[len(order) % len(_SEQUENCE_ACCENT_CYCLE)]
        by_id[pid] = p
        order.append(pid)

    messages = []
    for m in [dict(m) for m in (spec.get("messages") or []) if isinstance(m, dict)][:30]:
        kind = m.get("kind", "sync")
        if kind not in SEQUENCE_MESSAGE_KINDS:
            kind = "sync"
        m["kind"] = kind
        if kind == "note":
            targets = m.get("target")
            if isinstance(targets, str):
                targets = [targets]
            targets = [str(t) for t in (targets or []) if str(t) in by_id]
            m["_targets"] = (targets or [order[0]])[:2]
        else:
            frm = str(m.get("from") or order[0])
            to = str(m.get("to") or order[1])
            frm = frm if frm in by_id else order[0]
            to = to if to in by_id else order[1]
            if kind == "self":
                to = frm
            m["_from"], m["_to"] = frm, to
        messages.append(m)
    if not messages:
        messages = [{"kind": "sync", "label": "", "_from": order[0], "_to": order[1]}]

    non_note = [i for i, m in enumerate(messages) if m["kind"] != "note"]
    fragments = []
    for f in (spec.get("fragments") or [])[:6]:
        if not isinstance(f, dict):
            continue
        kind = f.get("kind", "alt")
        rng = f.get("range")
        if kind not in SEQUENCE_FRAGMENT_KINDS or not (isinstance(rng, list) and len(rng) == 2):
            continue
        try:
            a, b = int(rng[0]), int(rng[1])
        except (TypeError, ValueError):
            continue
        # Snap the range inward to real (non-note) messages so a frame never
        # opens or closes on a sticky note row.
        a2 = min([i for i in non_note if i >= a], default=None)
        b2 = max([i for i in non_note if i <= b], default=None)
        if a2 is None or b2 is None or a2 > b2:
            continue
        dividers = []
        if kind == "alt":
            for d in (f.get("dividers") or []):
                if not isinstance(d, dict):
                    continue
                try:
                    at = int(d.get("at", -1))
                except (TypeError, ValueError):
                    continue
                if a2 < at <= b2 and messages[at]["kind"] != "note":
                    dividers.append({"at": at, "label": str(d.get("label", ""))})
        fragments.append({"kind": kind, "label": str(f.get("label", "")),
                          "a": a2, "b": b2, "dividers": dividers})
    for f in fragments:
        f["depth"] = sum(1 for g in fragments
                         if g is not f and g["a"] <= f["a"] and g["b"] >= f["b"]
                         and (g["a"], g["b"]) != (f["a"], f["b"]))
    return participants, order, by_id, messages, fragments


def plan_sequence(spec):
    spec = spec or {}
    participants, order, by_id, messages, fragments = _sequence_prepare(spec)

    # --- lifeline x positions (centered row of participant heads) -----------
    n = len(order)
    x_lo, x_hi = 110.0, 1100.0
    if n > 1:
        spacing = min(300.0, (x_hi - x_lo) / (n - 1))
    else:
        spacing = 0.0  # pragma: no cover - participants are padded to >=2 above
    start = CANVAS_W / 2 - spacing * (n - 1) / 2
    cx = {pid: start + i * spacing for i, pid in enumerate(order)}

    # --- vertical rhythm: fragment openings/dividers/closings add room ------
    life_top = SEQUENCE_HEAD_Y + SEQUENCE_HEAD_H
    y = float(life_top + 56)
    open_at, close_at, divide_at = {}, {}, {}
    for f in fragments:
        open_at[f["a"]] = open_at.get(f["a"], 0) + 1
        close_at[f["b"]] = close_at.get(f["b"], 0) + 1
        for d in f["dividers"]:
            divide_at[d["at"]] = divide_at.get(d["at"], 0) + 1
    for i, m in enumerate(messages):
        y += 44 * open_at.get(i, 0)
        y += 28 * divide_at.get(i, 0)
        m["_y"] = y
        if m["kind"] == "note":
            y += 58
        elif m["kind"] == "self":
            y += 88
        else:
            y += _SEQUENCE_PITCH
        y += 34 * close_at.get(i, 0)
    life_bottom = y - _SEQUENCE_PITCH + 46

    # --- message geometry -----------------------------------------------------
    flow, edges = [], []
    arrow_for = {"sync": "filled", "async": "open", "return": "open", "self": "open"}
    msg_i = 0
    for i, m in enumerate(messages):
        if m["kind"] == "note":
            xs = [cx[t] for t in m["_targets"]]
            if len(xs) > 1:
                nx, nw = min(xs) - 70, max(xs) - min(xs) + 140
            else:
                nx, nw = xs[0] + 26, 156
            m["_note"] = {"x": round(nx), "y": round(m["_y"] - 22), "w": round(nw), "h": 44}
            continue
        x1, x2 = cx[m["_from"]], cx[m["_to"]]
        if m["kind"] == "self":
            pts = [(x1, m["_y"]), (x1 + 64, m["_y"]), (x1 + 64, m["_y"] + 26), (x1 + 6, m["_y"] + 26)]
        else:
            pts = [(x1, m["_y"]), (x2, m["_y"])]
        m["_points"] = [(round(px), round(py)) for px, py in pts]
        m["_style"] = "dashed" if m["kind"] == "return" else "solid"
        m["_arrow"] = arrow_for[m["kind"]]
        m["_color"] = "muted" if m["kind"] == "return" else "white"
        edges.append({"id": f"e.seq.{i}", "from": m["_from"], "to": m["_to"],
                      "points": m["_points"], "color": m["_color"], "label": m.get("label"),
                      "style": m["_style"], "loop": False})
        msg_count = max(1, sum(1 for mm in messages if mm["kind"] != "note"))
        flow.append({"points": [list(p) for p in m["_points"]],
                     "color": by_id[m["_from"]]["_accent"],
                     "offset": round(msg_i / msg_count, 4)})
        msg_i += 1

    # --- combined fragment frames --------------------------------------------
    for f in fragments:
        covered = set()
        for i in range(f["a"], f["b"] + 1):
            m = messages[i]
            if m["kind"] == "note":
                covered.update(m["_targets"])
            else:
                covered.update((m["_from"], m["_to"]))
        xs = [cx[pid] for pid in covered]
        x_min, x_max = min(xs), max(xs)
        for i in range(f["a"], f["b"] + 1):
            m = messages[i]
            if m["kind"] == "self":
                x_max = max(x_max, cx[m["_from"]] + 70)
        pad = 36 + 16 * f["depth"]
        f["x"] = round(x_min - pad)
        f["w"] = round(max(x_max - x_min + 2 * pad, 200))
        f["y"] = round(messages[f["a"]]["_y"] - 46)
        f["h"] = round(messages[f["b"]]["_y"] - f["y"] + 36)
        for d in f["dividers"]:
            d["y"] = round(messages[d["at"]]["_y"] - 30)

    # --- activation bars: LIFO pairing of calls and returns -------------------
    activations = []
    open_calls = []  # {"pid", "y", "depth"}
    for m in messages:
        kind = m["kind"]
        if kind == "note":
            continue
        # Auto activation: sync calls open a bar on the target (closed by the
        # paired return). Async is fire-and-forget: no bar unless the author
        # asks with "activate": true. Self messages likewise opt in.
        auto = kind == "sync" and m.get("activate", True) is not False
        explicit = kind == "async" and m.get("activate") is True
        if (auto or explicit) and (m["_from"] != m["_to"] or m.get("activate") is True):
            depth = sum(1 for c in open_calls if c["pid"] == m["_to"])
            open_calls.append({"pid": m["_to"], "y": m["_y"], "depth": depth})
        elif kind == "self" and m.get("activate"):
            depth = sum(1 for c in open_calls if c["pid"] == m["_from"])
            open_calls.append({"pid": m["_from"], "y": m["_y"] + 44, "depth": depth})
        close = kind == "return" or m.get("deactivate")
        if close:
            for j in range(len(open_calls) - 1, -1, -1):
                if open_calls[j]["pid"] == m["_from"]:
                    entry = open_calls.pop(j)
                    activations.append({"pid": entry["pid"], "y": round(entry["y"]),
                                        "h": round(max(26, m["_y"] - entry["y"])),
                                        "depth": entry["depth"]})
                    break
    for entry in open_calls:  # never returned: bar runs to the lifeline end
        activations.append({"pid": entry["pid"], "y": round(entry["y"]),
                            "h": round(max(26, life_bottom - 12 - entry["y"])),
                            "depth": entry["depth"]})
    for a in activations:
        a["x"] = round(cx[a["pid"]] - 6 + a["depth"] * 7)
        a["w"] = 12

    # --- heads, pulses, icons ---------------------------------------------------
    heads, nodes, pulses, icons = [], [], [], []
    for ordinal, p in enumerate(participants):
        hx = cx[p["id"]] - SEQUENCE_HEAD_W / 2
        p["_cx"], p["_x"], p["_y"] = round(cx[p["id"]]), round(hx), SEQUENCE_HEAD_Y
        p["_w"], p["_h"] = SEQUENCE_HEAD_W, SEQUENCE_HEAD_H
        heads.append(p)
        nodes.append(_node(p["id"], "card", hx, SEQUENCE_HEAD_Y, SEQUENCE_HEAD_W, SEQUENCE_HEAD_H,
                           label=p.get("label", ""), icon=p.get("icon")))
        pulses.append({"box": [round(hx), SEQUENCE_HEAD_Y, round(hx) + SEQUENCE_HEAD_W, SEQUENCE_HEAD_Y + SEQUENCE_HEAD_H],
                       "color": p["_accent"]})
        icons.append(_icon(p.get("icon") or ("user" if p["kind"] == "actor" else "server"),
                           hx + 10, SEQUENCE_HEAD_Y + 12, p.get("color"), "sequence", ordinal))

    height = int(life_bottom) + 96 + (30 if spec.get("footer") else 0)
    frame = (18, 117, 1174, height - 144)
    glow = [{"box": [18, 117, 1192, height - 27], "color": "frame", "light": "frame", "width": 3},
            {"box": [600, 27, 992, 99], "color": "green", "light": "pink", "width": 2}]
    return {
        "layout": "sequence",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "sequence": {"participants": heads, "messages": messages, "fragments": fragments,
                     "activations": activations,
                     "lifeline": {"top": life_top, "bottom": round(life_bottom)}},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": icons,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Box diagrams (ER / class): compartment boxes + typed relations, laid out in
# DAG columns by reusing the graph layering helpers.
# ---------------------------------------------------------------------------

ER_CARDINALITIES = ("1:1", "1:N", "N:1", "M:N")
CLASS_KINDS = ("class", "interface", "abstract", "enum")
CLASS_RELATION_KINDS = ("association", "inheritance", "realization", "composition", "aggregation", "dependency")
USECASE_LINK_KINDS = ("association", "include", "extend")
BOX_ACCENTS = GRAPH_ACCENTS


def _box_accent(item, fallback):
    accent = (item or {}).get("accent")
    return accent if accent in BOX_ACCENTS else fallback


def _unique_ids(items, prefix):
    by_id, order = {}, []
    for i, item in enumerate(items):
        iid = str(item.get("id") or f"{prefix}{i}")
        while iid in by_id:
            iid += "_"
        item["id"] = iid
        by_id[iid] = item
        order.append(iid)
    return by_id, order


def _layered_boxes(ids, relations, widths, heights, top=190, x_lo=90.0, x_hi=1120.0, gap_v=46,
                   direction="right"):
    """Layered box positions. relations: iterable of (from, to) pairs.

    direction "right": layers are columns, boxes in a column stack vertically
    (centered on the tallest column). direction "down": layers are rows,
    boxes in a row sit side by side (centered horizontally)."""
    fake = {"nodes": [{"id": i} for i in ids],
            "edges": [{"from": a, "to": b} for a, b in relations if a != b]}
    raw_nodes, raw_edges, _by_id = _graph_prepare(fake)
    layer, cols, _manual = _graph_layers(raw_nodes, raw_edges, _by_id)
    n_layers = (max(cols) + 1) if cols else 1
    boxes = {}
    if direction == "down":
        row_gap = 74
        y = top
        for l in sorted(cols):
            row_ids = cols[l]
            row_h = max(heights[i] for i in row_ids)
            total_w = sum(widths[i] for i in row_ids) + gap_v * (len(row_ids) - 1)
            x = CANVAS_W / 2 - total_w / 2
            for iid in row_ids:
                boxes[iid] = (round(x), round(y + (row_h - heights[iid]) / 2),
                              round(widths[iid]), round(heights[iid]))
                x += widths[iid] + gap_v
            y += row_h + row_gap
        bottom = y - row_gap
        return boxes, bottom, layer
    col_ws = {l: max(widths[i] for i in cols[l]) for l in cols}
    sum_w = sum(col_ws.values())
    if n_layers > 1:
        gap_u = min(70.0, max(24.0, (x_hi - x_lo - sum_w) / (n_layers - 1)))
        total_u = sum_w + (n_layers - 1) * gap_u
        u0 = max(x_lo, CANVAS_W / 2 - total_u / 2)
    else:
        gap_u = 0.0
        u0 = CANVAS_W / 2 - sum_w / 2
    col_x = {}
    x = u0
    for l in sorted(col_ws):
        col_x[l] = x
        x += col_ws[l] + gap_u
    col_totals = {}
    for l, col_ids in cols.items():
        col_totals[l] = sum(heights[i] for i in col_ids) + gap_v * (len(col_ids) - 1)
    span = max(col_totals.values(), default=0)
    for l, col_ids in cols.items():
        y = top + (span - col_totals[l]) / 2
        for iid in col_ids:
            bx = col_x[l] + (col_ws[l] - widths[iid]) / 2
            boxes[iid] = (round(bx), round(y), round(widths[iid]), round(heights[iid]))
            y += heights[iid] + gap_v
    bottom = max((b[1] + b[3] for b in boxes.values()), default=top)
    return boxes, bottom, layer


def _box_link(a, b):
    """Orthogonal connector between two boxes (side-to-side)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acx, acy = ax + aw / 2, ay + ah / 2
    bcx, bcy = bx + bw / 2, by + bh / 2
    if abs(bcx - acx) >= abs(bcy - acy):
        right = bcx > acx
        p1 = (ax + aw if right else ax, acy)
        p2 = (bx if right else bx + bw, bcy)
        if abs(p1[1] - p2[1]) < 3:
            return [p1, p2]
        mid = (p1[0] + p2[0]) / 2
        return [p1, (mid, p1[1]), (mid, p2[1]), p2]
    down = bcy > acy
    p1 = (acx, ay + ah if down else ay)
    p2 = (bcx, by if down else by + bh)
    if abs(p1[0] - p2[0]) < 3:
        return [p1, p2]
    mid = (p1[1] + p2[1]) / 2
    return [p1, (p1[0], mid), (p2[0], mid), p2]


def _self_link(box):
    x, y, w, h = box
    cy = y + h / 2
    return [(x + w, cy - 14), (x + w + 36, cy - 14), (x + w + 36, cy + 14), (x + w, cy + 14)]


def _is_horizontal(points, index=0):
    a, b = points[index], points[index + 1]
    return abs(b[0] - a[0]) >= abs(b[1] - a[1])

def _route_box_relations(rels, boxes, layer):
    """Route relation polylines between boxes.

    - Same/adjacent layer: direct orthogonal link between box sides.
    - Skipping one or more layers: routed through a lane above the boxes so
      the line never crosses an unrelated box.
    - Ports on a shared box side spread apart so parallel links don't stack.
    """
    skip_i = 0
    for r in rels:
        a, b = boxes[r["from"]], boxes[r["to"]]
        if r["from"] == r["to"]:
            r["_points"] = [(round(px), round(py)) for px, py in _self_link(a)]
            continue
        if abs(layer.get(r["to"], 0) - layer.get(r["from"], 0)) >= 2:
            # Cross-column link: run along a lane above the boxes, then drop
            # through the column gap and enter the target from the side so
            # stacked boxes in the target's own column are never crossed.
            lane = 158 + skip_i * 26
            skip_i += 1
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            p1 = (ax + aw / 2, ay)
            if bx >= ax:
                gap_x = bx - 36
                entry = (bx, by + bh / 2)
            else:
                gap_x = bx + bw + 36
                entry = (bx + bw, by + bh / 2)
            pts = [p1, (p1[0], lane), (gap_x, lane), (gap_x, entry[1]), entry]
            r["_points"] = [(round(px), round(py)) for px, py in pts]
        else:
            r["_points"] = [(round(px), round(py)) for px, py in _box_link(a, b)]

    usage = {}
    for r in rels:
        if r["from"] == r["to"]:
            continue
        pts = [list(p) for p in r["_points"]]
        for end in (0, -1):
            i, j = (0, 1) if end == 0 else (-1, -2)
            dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
            horiz = abs(dx) >= abs(dy)
            if horiz:
                side = "r" if dx >= 0 else "l"
            else:
                side = "b" if dy >= 0 else "t"
            key = (r["from"] if end == 0 else r["to"], end, side)
            k = usage.get(key, 0)
            usage[key] = k + 1
            if k == 0:
                continue
            off = ((k + 1) // 2) * 18 * (1 if k % 2 else -1)
            if horiz:
                pts[i][1] += off
                if abs(pts[j][1] - (pts[i][1] - off)) < 1:
                    pts[j][1] += off
            else:
                pts[i][0] += off
                if abs(pts[j][0] - (pts[i][0] - off)) < 1:
                    pts[j][0] += off
        r["_points"] = [tuple(p) for p in pts]


def _box_frame_glow(height):
    frame = (18, 117, 1174, height - 144)
    glow = [{"box": [18, 117, 1192, height - 27], "color": "frame", "light": "frame", "width": 3},
            {"box": [600, 27, 992, 99], "color": "green", "light": "pink", "width": 2}]
    return frame, glow


# ---------------------------------------------------------------------------
# ER (entity boxes with attribute rows + cardinality-labeled relations)
# ---------------------------------------------------------------------------

ER_BOX_W = 224
ER_HEADER_H = 36
ER_ROW_H = 22


def plan_er(spec):
    spec = spec or {}
    entities = [dict(e) for e in (spec.get("entities") or []) if isinstance(e, dict)][:12]
    while len(entities) < 2:
        entities.append({"id": f"e{len(entities)}", "label": ""})
    by_id, order = _unique_ids(entities, "e")
    for i, e in enumerate(entities):
        attrs = []
        for a in (e.get("attributes") or [])[:8]:
            if isinstance(a, dict) and a.get("name"):
                attrs.append({"name": str(a.get("name")), "type": str(a.get("type", "")),
                              "key": a.get("key") if a.get("key") in ("pk", "fk") else None})
            elif isinstance(a, str) and a.strip():
                attrs.append({"name": a.strip(), "type": "", "key": None})
        e["_attrs"] = attrs
        e["_accent"] = _box_accent(e, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        e["_h"] = ER_HEADER_H + ER_ROW_H * max(1, len(attrs)) + 12

    relations = []
    for r in (spec.get("relations") or [])[:16]:
        if not isinstance(r, dict):
            continue
        frm, to = str(r.get("from") or ""), str(r.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        card = str(r.get("cardinality", "1:N"))
        fc, tc = {"1:1": ("1", "1"), "1:N": ("1", "N"), "N:1": ("N", "1"), "M:N": ("M", "N")}.get(card, ("1", "N"))
        relations.append({"from": frm, "to": to, "label": str(r.get("label", "")),
                          "from_card": str(r.get("from_card", fc))[:5],
                          "to_card": str(r.get("to_card", tc))[:5]})

    widths = {e["id"]: ER_BOX_W for e in entities}
    heights = {e["id"]: e["_h"] for e in entities}
    boxes, bottom, layer = _layered_boxes(order, [(r["from"], r["to"]) for r in relations], widths, heights)
    for e in entities:
        e["_box"] = boxes[e["id"]]

    _route_box_relations(relations, boxes, layer)
    flow, edges, rels = [], [], []
    for i, r in enumerate(relations):
        rels.append(r)
        edges.append({"id": f"e.er.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": r["label"], "style": "solid", "loop": r["from"] == r["to"]})
        flow.append({"points": [list(p) for p in r["_points"]],
                     "color": by_id[r["from"]]["_accent"],
                     "offset": round(i / max(1, len(relations)), 4)})

    nodes, pulses = [], []
    for e in entities:
        x, y, w, h = e["_box"]
        nodes.append(_node(e["id"], "card", x, y, w, h, label=e.get("label", ""), icon=e.get("icon")))
        pulses.append({"box": [x, y, x + w, y + h], "color": e["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "er",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "er": {"entities": entities, "relations": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Use case (actors + system boundary + use-case ellipses + include/extend)
# ---------------------------------------------------------------------------

USECASE_ELLIPSE_W = 176
USECASE_ELLIPSE_H = 62


def plan_usecase(spec):
    spec = spec or {}
    actors = [dict(a) for a in (spec.get("actors") or []) if isinstance(a, dict)][:6]
    if not actors:
        actors = [{"id": "actor0", "label": ""}]
    actor_ids, actor_order = _unique_ids(actors, "a")
    for a in actors:
        a["side"] = "right" if a.get("side") == "right" else "left"

    usecases = [dict(u) for u in (spec.get("usecases") or []) if isinstance(u, dict)][:16]
    while len(usecases) < 2:
        usecases.append({"id": f"u{len(usecases)}", "label": ""})
    uc_ids, uc_order = _unique_ids(usecases, "u")

    system = spec.get("system") if isinstance(spec.get("system"), dict) else {}
    sys_label = str(system.get("label", ""))

    links = []
    known = set(actor_order) | set(uc_order)
    for l in (spec.get("links") or [])[:24]:
        if not isinstance(l, dict):
            continue
        frm, to = str(l.get("from") or ""), str(l.get("to") or "")
        if frm not in known or to not in known:
            continue
        kind = l.get("kind", "association")
        if kind not in USECASE_LINK_KINDS:
            kind = "association"
        # include/extend only make sense between use cases.
        if kind != "association" and (frm not in uc_ids or to not in uc_ids):
            kind = "association"
        links.append({"from": frm, "to": to, "kind": kind, "label": str(l.get("label", ""))})

    # Geometry: boundary box centered; use cases in up to 2 columns inside it.
    n = len(usecases)
    n_cols = 1 if n <= 6 else 2
    rows = (n + n_cols - 1) // n_cols
    pitch_v = 96
    bound_x, bound_w = 260.0, 730.0
    bound_y = 200.0
    bound_h = max(300.0, rows * pitch_v + 110)
    col_xs = [bound_x + bound_w / 2] if n_cols == 1 else [bound_x + bound_w * 0.28, bound_x + bound_w * 0.74]
    for i, u in enumerate(usecases):
        col = i // rows if n_cols == 2 else 0
        row = i % rows
        cx = col_xs[col]
        cy = bound_y + 70 + (bound_h - 110 - (rows - 1) * pitch_v) / 2 + row * pitch_v
        u["_cx"], u["_cy"] = round(cx), round(cy)

    # Actors stacked along the free side(s), centered on the boundary.
    left = [a for a in actors if a["side"] == "left"]
    right = [a for a in actors if a["side"] == "right"]
    for group, x in ((left, 130.0), (right, 1080.0)):
        if not group:
            continue
        pitch = min(150.0, (bound_h - 40) / len(group))
        y0 = bound_y + bound_h / 2 - pitch * (len(group) - 1) / 2
        for i, a in enumerate(group):
            a["_cx"], a["_cy"] = round(x), round(y0 + i * pitch)

    anchor = {}
    for a in actors:
        anchor[a["id"]] = (a["_cx"], a["_cy"])
    for u in usecases:
        anchor[u["id"]] = (u["_cx"], u["_cy"])

    flow, edges = [], []
    for i, l in enumerate(links):
        x1, y1 = anchor[l["from"]]
        x2, y2 = anchor[l["to"]]
        # Trim line ends to the ellipse outline (approximate with the ellipse radii).
        dx, dy = x2 - x1, y2 - y1
        dist = max(1.0, math.hypot(dx, dy))
        if l["to"] in uc_ids:
            rx, ry = USECASE_ELLIPSE_W / 2, USECASE_ELLIPSE_H / 2
            t = 1.0 / max(1e-6, math.hypot(dx / rx, dy / ry))
            trim = min(dist - 4, t)
            x2 = anchor[l["to"]][0] - dx / dist * trim
            y2 = anchor[l["to"]][1] - dy / dist * trim
        if l["from"] in uc_ids:
            rx, ry = USECASE_ELLIPSE_W / 2, USECASE_ELLIPSE_H / 2
            t = 1.0 / max(1e-6, math.hypot(dx / rx, dy / ry))
            x1 = anchor[l["from"]][0] + dx / dist * min(dist - 4, t)
            y1 = anchor[l["from"]][1] + dy / dist * min(dist - 4, t)
        pts = [(round(x1), round(y1)), (round(x2), round(y2))]
        l["_points"] = pts
        l["_style"] = "solid" if l["kind"] == "association" else "dashed"
        l["_arrow"] = False if l["kind"] == "association" else "open"
        edges.append({"id": f"e.uc.{i}", "from": l["from"], "to": l["to"], "points": pts,
                      "color": "white", "label": l["label"], "style": l["_style"], "loop": False})
        flow.append({"points": [list(p) for p in pts], "color": "green" if l["kind"] == "association" else "purple",
                     "offset": round(i / max(1, len(links)), 4)})

    nodes, pulses = [], []
    for a in actors:
        nodes.append(_node(a["id"], "terminal", a["_cx"] - 30, a["_cy"] - 44, 60, 100, label=a.get("label", "")))
        pulses.append({"box": [a["_cx"] - 30, a["_cy"] - 44, a["_cx"] + 30, a["_cy"] + 56], "color": "green"})
    for u in usecases:
        x, y = u["_cx"] - USECASE_ELLIPSE_W / 2, u["_cy"] - USECASE_ELLIPSE_H / 2
        nodes.append(_node(u["id"], "terminal", x, y, USECASE_ELLIPSE_W, USECASE_ELLIPSE_H, label=u.get("label", "")))
        pulses.append({"box": [x, y, x + USECASE_ELLIPSE_W, y + USECASE_ELLIPSE_H], "color": "cyan"})

    height = int(bound_y + bound_h) + 90 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "usecase",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "usecase": {"actors": actors, "usecases": usecases,
                    "boundary": {"x": round(bound_x), "y": round(bound_y), "w": round(bound_w), "h": round(bound_h),
                                 "label": sys_label},
                    "links": links},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Class (compartment boxes: stereotype/name, attributes, methods + the six
# UML relation kinds with correct end markers)
# ---------------------------------------------------------------------------

CLASS_BOX_W = 240
CLASS_HEADER_H = 32
CLASS_STEREO_H = 16
CLASS_ROW_H = 20


def plan_class(spec):
    spec = spec or {}
    classes = [dict(c) for c in (spec.get("classes") or []) if isinstance(c, dict)][:10]
    while len(classes) < 2:
        classes.append({"id": f"c{len(classes)}", "label": ""})
    by_id, order = _unique_ids(classes, "c")

    def member_list(value, cap):
        out = []
        for m in (value or [])[:cap]:
            if isinstance(m, dict) and m.get("name"):
                vis = str(m.get("visibility", "+"))
                out.append({"name": str(m.get("name")), "type": str(m.get("type", "")),
                            "visibility": vis if vis and vis[0] in "+-#~" else "+",
                            "static": bool(m.get("static"))})
            elif isinstance(m, str) and m.strip():
                out.append({"name": m.strip(), "type": "", "visibility": "+", "static": False})
        return out

    for i, c in enumerate(classes):
        kind = c.get("kind", "class")
        c["kind"] = kind if kind in CLASS_KINDS else "class"
        c["_attrs"] = member_list(c.get("attributes"), 8)
        c["_methods"] = member_list(c.get("methods"), 8)
        c["_accent"] = _box_accent(c, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        c["_stereo"] = {"interface": "«interface»", "enum": "«enumeration»"}.get(c["kind"], "")
        stereo_h = CLASS_STEREO_H if c["_stereo"] else 0
        c["_h"] = (CLASS_HEADER_H + stereo_h + 10 + CLASS_ROW_H * max(1, len(c["_attrs"]))
                   + 10 + CLASS_ROW_H * len(c["_methods"]) + 10)

    relations = []
    for r in (spec.get("relations") or [])[:16]:
        if not isinstance(r, dict):
            continue
        frm, to = str(r.get("from") or ""), str(r.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        kind = r.get("kind", "association")
        if kind not in CLASS_RELATION_KINDS:
            kind = "association"
        relations.append({"from": frm, "to": to, "kind": kind, "label": str(r.get("label", "")),
                          "from_card": str(r.get("from_card", ""))[:5], "to_card": str(r.get("to_card", ""))[:5]})

    widths = {c["id"]: CLASS_BOX_W for c in classes}
    heights = {c["id"]: c["_h"] for c in classes}
    boxes, bottom, layer = _layered_boxes(order, [(r["from"], r["to"]) for r in relations], widths, heights)
    for c in classes:
        c["_box"] = boxes[c["id"]]

    _route_box_relations(relations, boxes, layer)

    style_arrow = {
        "association": ("solid", "open"),
        "inheritance": ("solid", "triangle"),
        "realization": ("dashed", "triangle"),
        "dependency": ("dashed", "open"),
        "composition": ("solid", False),
        "aggregation": ("solid", False),
    }
    flow, edges, rels = [], [], []
    for i, r in enumerate(relations):
        r["_style"], r["_arrow"] = style_arrow[r["kind"]]
        r["_horiz_start"] = _is_horizontal(r["_points"], 0)
        rels.append(r)
        edges.append({"id": f"e.cls.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": r["label"], "style": r["_style"], "loop": r["from"] == r["to"]})
        flow.append({"points": [list(p) for p in r["_points"]],
                     "color": by_id[r["from"]]["_accent"],
                     "offset": round(i / max(1, len(relations)), 4)})

    nodes, pulses = [], []
    for c in classes:
        x, y, w, h = c["_box"]
        nodes.append(_node(c["id"], "card", x, y, w, h, label=c.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": c["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "class",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "class": {"classes": classes, "relations": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Activity (UML activity diagram: initial/final nodes, rounded actions,
# decision diamonds, fork/join synchronization bars, guarded flows)
# ---------------------------------------------------------------------------

ACTIVITY_NODE_KINDS = ("initial", "final", "action", "decision", "fork", "join")
ACTIVITY_ACTION_W = 190
ACTIVITY_ACTION_H = 56
ACTIVITY_DIAMOND = 104
ACTIVITY_DOT = 24
ACTIVITY_BAR = (150, 10)  # w, h for direction "down" (transposed for "right")


def _activity_box_size(node, direction):
    kind = node["kind"]
    if kind in ("initial", "final"):
        return ACTIVITY_DOT, ACTIVITY_DOT
    if kind == "decision":
        return ACTIVITY_DIAMOND, ACTIVITY_DIAMOND
    if kind in ("fork", "join"):
        w, h = ACTIVITY_BAR
        return (h, w) if direction == "right" else (w, h)
    return ACTIVITY_ACTION_W, ACTIVITY_ACTION_H


def plan_activity(spec):
    spec = spec or {}
    direction = spec.get("direction", "down")
    direction = "right" if direction == "right" else "down"
    nodes = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:24]
    if not nodes:
        nodes = [{"id": "start", "kind": "initial"}, {"id": "a1", "label": "", "kind": "action"},
                 {"id": "end", "kind": "final"}]
    by_id, order = _unique_ids(nodes, "n")
    initials = 0
    for i, n in enumerate(nodes):
        kind = n.get("kind", "action")
        n["kind"] = kind if kind in ACTIVITY_NODE_KINDS else "action"
        n["_accent"] = _box_accent(n, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        n["_auto_initial"] = False
        initials += n["kind"] == "initial"
    if initials == 0:
        # Prepend an implicit start node so the diagram reads top-down.
        start = {"id": "_start", "kind": "initial", "label": "", "_accent": "green", "_auto_initial": True}
        while start["id"] in by_id:
            start["id"] += "_"
        nodes.insert(0, start)
        by_id[start["id"]] = start
        order.insert(0, start["id"])
        first_action = next((n for n in nodes[1:] if n["kind"] not in ("final",)), None)
        if first_action is not None:
            spec_edges = list(spec.get("edges") or [])
            spec_edges.insert(0, {"from": start["id"], "to": first_action["id"]})
            spec = dict(spec, edges=spec_edges)

    edges = []
    for e in (spec.get("edges") or [])[:40]:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or ""), str(e.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        edges.append({"from": frm, "to": to, "label": str(e.get("label", ""))})

    widths, heights = {}, {}
    for n in nodes:
        w, h = _activity_box_size(n, direction)
        widths[n["id"]], heights[n["id"]] = w, h
    boxes, bottom, layer = _layered_boxes(order, [(e["from"], e["to"]) for e in edges],
                                          widths, heights, gap_v=64, direction=direction)
    for n in nodes:
        n["_box"] = boxes[n["id"]]

    # Back edges (layer[to] <= layer[from]) become dashed loop channels on the
    # left (down) or below (right); self edges loop off the right side.
    loop_i = 0
    flow, gedges, rels = [], [], []
    max_right = max(b[0] + b[2] for b in boxes.values())
    for i, e in enumerate(edges):
        a, b = boxes[e["from"]], boxes[e["to"]]
        back = e["from"] != e["to"] and layer.get(e["to"], 0) <= layer.get(e["from"], 0)
        if e["from"] == e["to"]:
            pts = _self_link(a)
            style = "dashed"
        elif back:
            style = "dashed"
            loop_i += 1
            if direction == "down":
                lane_x = 120 + (loop_i - 1) * 26
                p1 = (a[0], a[1] + a[3] / 2)
                p2 = (b[0], b[1] + b[3] / 2)
                pts = [p1, (lane_x, p1[1]), (lane_x, p2[1]), p2]
            else:
                lane_y = bottom + 40 + (loop_i - 1) * 30
                p1 = (a[0] + a[2] / 2, a[1] + a[3])
                p2 = (b[0] + b[2] / 2, b[1] + b[3])
                pts = [p1, (p1[0], lane_y), (p2[0], lane_y), p2]
        else:
            pts = _box_link(a, b)
            style = "solid"
        e["_points"] = [(round(px), round(py)) for px, py in pts]
        e["_style"] = style
        e["_back"] = back or e["from"] == e["to"]
        rels.append(e)
        gedges.append({"id": f"e.act.{i}", "from": e["from"], "to": e["to"], "points": e["_points"],
                       "color": "muted" if e["_back"] else "white", "label": e["label"],
                       "style": style, "loop": e["_back"]})
        flow.append({"points": [list(p) for p in e["_points"]],
                     "color": by_id[e["from"]]["_accent"] if not e["_back"] else "purple",
                     "offset": round(0.8 * i / max(1, len(edges)), 4)})

    gnodes, pulses = [], []
    for n in nodes:
        x, y, w, h = n["_box"]
        kind = n["kind"]
        gnodes.append(_node(n["id"], "terminal" if kind in ("initial", "final", "fork", "join") else
                            ("decision" if kind == "decision" else "card"),
                            x, y, w, h, label=n.get("label", "")))
        pulses.append({"box": [x - 6, y - 6, x + w + 6, y + h + 6], "color": n["_accent"]})

    height = int(bottom) + 110 + (40 if loop_i else 0) + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "activity",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "activity": {"nodes": nodes, "edges": rels, "direction": direction},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": gnodes,
        "edges": gedges,
    }


# ---------------------------------------------------------------------------
# State machine (UML state diagram: rounded states with optional entry/do
# bodies, initial pseudostate, final state, labeled transitions)
# ---------------------------------------------------------------------------

STATE_NODE_KINDS = ("state", "initial", "final")
STATE_BOX_W = 210
STATE_HEADER_H = 30
STATE_BODY_H = 20


def plan_state(spec):
    spec = spec or {}
    states = [dict(s) for s in (spec.get("states") or []) if isinstance(s, dict)][:20]
    while len(states) < 2:
        states.append({"id": f"s{len(states)}", "label": ""})
    by_id, order = _unique_ids(states, "s")
    for i, s in enumerate(states):
        kind = s.get("kind", "state")
        s["kind"] = kind if kind in STATE_NODE_KINDS else "state"
        s["_accent"] = _box_accent(s, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        s["_body"] = str(s.get("body", ""))

    transitions = []
    for t in (spec.get("transitions") or [])[:30]:
        if not isinstance(t, dict):
            continue
        frm, to = str(t.get("from") or ""), str(t.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        transitions.append({"from": frm, "to": to, "label": str(t.get("label", ""))})

    widths, heights = {}, {}
    for s in states:
        if s["kind"] in ("initial", "final"):
            widths[s["id"]], heights[s["id"]] = ACTIVITY_DOT, ACTIVITY_DOT
        else:
            body_rows = len([r for r in s["_body"].split("\n") if r.strip()]) if s["_body"] else 0
            widths[s["id"]] = STATE_BOX_W
            heights[s["id"]] = STATE_HEADER_H + (10 + STATE_BODY_H * body_rows if body_rows else 0) + 14
    boxes, bottom, layer = _layered_boxes(order, [(t["from"], t["to"]) for t in transitions],
                                          widths, heights, gap_v=60, direction="right")
    for s in states:
        s["_box"] = boxes[s["id"]]

    loop_i = 0
    skip_i = 0
    flow, edges, rels = [], [], []
    for i, t in enumerate(transitions):
        a, b = boxes[t["from"]], boxes[t["to"]]
        back = t["from"] != t["to"] and layer.get(t["to"], 0) <= layer.get(t["from"], 0)
        if t["from"] == t["to"]:
            pts = _self_link(a)
            style = "solid"
        elif back:
            style = "dashed"
            loop_i += 1
            lane_y = bottom + 44 + (loop_i - 1) * 30
            p1 = (a[0] + a[2] / 2, a[1] + a[3])
            p2 = (b[0] + b[2] / 2, b[1] + b[3])
            pts = [p1, (p1[0], lane_y), (p2[0], lane_y), p2]
        elif layer.get(t["to"], 0) - layer.get(t["from"], 0) >= 2:
            style = "solid"
            skip_i += 1
            lane = 158 + (skip_i - 1) * 26
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            p1 = (ax + aw / 2, ay)
            if bx >= ax:
                gap_x = bx - 36
                entry = (bx, by + bh / 2)
            else:
                gap_x = bx + bw + 36  # pragma: no cover - layered columns place skip targets right of the source
                entry = (bx + bw, by + bh / 2)  # pragma: no cover
            pts = [p1, (p1[0], lane), (gap_x, lane), (gap_x, entry[1]), entry]
        else:
            pts = _box_link(a, b)
            style = "solid"
        t["_points"] = [(round(px), round(py)) for px, py in pts]
        t["_style"] = style
        t["_back"] = back
        rels.append(t)
        edges.append({"id": f"e.st.{i}", "from": t["from"], "to": t["to"], "points": t["_points"],
                      "color": "muted" if back else "white", "label": t["label"],
                      "style": style, "loop": back})
        flow.append({"points": [list(p) for p in t["_points"]],
                     "color": by_id[t["from"]]["_accent"] if not back else "purple",
                     "offset": round(0.8 * i / max(1, len(transitions)), 4)})

    nodes, pulses = [], []
    for s in states:
        x, y, w, h = s["_box"]
        nodes.append(_node(s["id"], "terminal" if s["kind"] in ("initial", "final") else "card",
                           x, y, w, h, label=s.get("label", "")))
        pulses.append({"box": [x - 6, y - 6, x + w + 6, y + h + 6], "color": s["_accent"]})

    height = int(bottom) + 110 + (44 if loop_i else 0) + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "state",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "state": {"states": states, "transitions": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# DFD (data flow diagram, Gane-Sarson: external rectangles, process circles,
# open data stores, labeled data flows)
# ---------------------------------------------------------------------------

DFD_NODE_KINDS = ("external", "process", "store")
DFD_PROCESS_W = 150
DFD_PROCESS_H = 110
DFD_BOX_W = 170
DFD_BOX_H = 70
DFD_STORE_W = 190
DFD_STORE_H = 60


def plan_dfd(spec):
    spec = spec or {}
    nodes = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:20]
    while len(nodes) < 2:
        nodes.append({"id": f"d{len(nodes)}", "label": "", "kind": "process"})
    by_id, order = _unique_ids(nodes, "d")
    for i, n in enumerate(nodes):
        kind = n.get("kind", "process")
        n["kind"] = kind if kind in DFD_NODE_KINDS else "process"
        n["_accent"] = _box_accent(n, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        n["_number"] = str(n.get("number", ""))

    flows = []
    for f in (spec.get("flows") or [])[:30]:
        if not isinstance(f, dict):
            continue
        frm, to = str(f.get("from") or ""), str(f.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        flows.append({"from": frm, "to": to, "label": str(f.get("label", ""))})

    size_for = {"process": (DFD_PROCESS_W, DFD_PROCESS_H), "external": (DFD_BOX_W, DFD_BOX_H),
                "store": (DFD_STORE_W, DFD_STORE_H)}
    widths = {n["id"]: size_for[n["kind"]][0] for n in nodes}
    heights = {n["id"]: size_for[n["kind"]][1] for n in nodes}
    boxes, bottom, layer = _layered_boxes(order, [(f["from"], f["to"]) for f in flows],
                                          widths, heights, gap_v=56, direction="right")
    for n in nodes:
        n["_box"] = boxes[n["id"]]

    flow, edges, rels = [], [], []
    loop_i = 0
    skip_i = 0
    for i, f in enumerate(flows):
        a, b = boxes[f["from"]], boxes[f["to"]]
        back = f["from"] != f["to"] and layer.get(f["to"], 0) <= layer.get(f["from"], 0)
        if f["from"] == f["to"]:
            pts = _self_link(a)
            style = "dashed"
        elif back:
            style = "dashed"
            loop_i += 1
            lane_y = bottom + 44 + (loop_i - 1) * 30
            p1 = (a[0] + a[2] / 2, a[1] + a[3])
            p2 = (b[0] + b[2] / 2, b[1] + b[3])
            pts = [p1, (p1[0], lane_y), (p2[0], lane_y), p2]
        elif layer.get(f["to"], 0) - layer.get(f["from"], 0) >= 2:
            style = "solid"
            skip_i += 1
            lane = 158 + (skip_i - 1) * 26
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            p1 = (ax + aw / 2, ay)
            if bx >= ax:
                gap_x = bx - 36
                entry = (bx, by + bh / 2)
            else:
                gap_x = bx + bw + 36  # pragma: no cover - layered columns place skip targets right of the source
                entry = (bx + bw, by + bh / 2)  # pragma: no cover
            pts = [p1, (p1[0], lane), (gap_x, lane), (gap_x, entry[1]), entry]
        else:
            pts = _box_link(a, b)
            style = "solid"
        f["_points"] = [(round(px), round(py)) for px, py in pts]
        f["_style"] = style
        f["_back"] = back or f["from"] == f["to"]
        rels.append(f)
        edges.append({"id": f"e.dfd.{i}", "from": f["from"], "to": f["to"], "points": f["_points"],
                      "color": "muted" if f["_back"] else "white", "label": f["label"],
                      "style": style, "loop": f["_back"]})
        flow.append({"points": [list(p) for p in f["_points"]],
                     "color": by_id[f["from"]]["_accent"] if not f["_back"] else "purple",
                     "offset": round(0.8 * i / max(1, len(flows)), 4)})

    gnodes, pulses = [], []
    for n in nodes:
        x, y, w, h = n["_box"]
        gnodes.append(_node(n["id"], "terminal" if n["kind"] == "process" else "card",
                            x, y, w, h, label=n.get("label", "")))
        pulses.append({"box": [x - 6, y - 6, x + w + 6, y + h + 6], "color": n["_accent"]})

    height = int(bottom) + 110 + (44 if loop_i else 0) + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "dfd",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "dfd": {"nodes": nodes, "flows": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": gnodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Shared helper for 1-level nested container layouts (deployment / package):
# children declare `parent`, containers grow to fit, layering runs on roots.
# ---------------------------------------------------------------------------


def _container_boxes(items, by_id, rel_pairs, widths, heights, header_h, top=190, pad=14, gap=10):
    for it in items:
        p = str(it.get("parent") or "")
        it["_parent"] = p if p and p in by_id and p != it["id"] else None
    root_ids = {it["id"] for it in items if it["_parent"] is None}
    for it in items:
        if it["_parent"] and it["_parent"] not in root_ids:
            it["_parent"] = None  # only one nesting level renders
    roots = [it for it in items if it["_parent"] is None]
    children_of = {it["id"]: [] for it in items}
    for it in items:
        if it["_parent"]:
            children_of[it["_parent"]].append(it)

    def root_of(iid):
        return by_id[iid]["_parent"] or iid

    mapped, seen = [], set()
    for a, b in rel_pairs:
        if a not in by_id or b not in by_id:
            continue  # pragma: no cover - rel_pairs are filtered to known ids by callers
        ra, rb = root_of(a), root_of(b)
        if ra != rb and (ra, rb) not in seen:
            seen.add((ra, rb))
            mapped.append((ra, rb))
    order_r = [it["id"] for it in roots]
    boxes_r, bottom, layer_r = _layered_boxes(
        order_r, mapped, {i: widths[i] for i in order_r}, {i: heights[i] for i in order_r}, top=top)
    boxes = dict(boxes_r)
    for r in roots:
        bx, by, bw, _bh = boxes_r[r["id"]]
        y = by + header_h + 6
        for k in children_of[r["id"]]:
            kw, kh = widths[k["id"]], heights[k["id"]]
            boxes[k["id"]] = (round(bx + (bw - kw) / 2), round(y), round(kw), round(kh))
            y += kh + gap
    layer_all = {it["id"]: layer_r.get(root_of(it["id"]), 0) for it in items}
    return boxes, bottom, layer_all, children_of


def _container_grow(item, kids, widths, heights, base_w, base_h, header_h, pad=14, gap=10):
    """Container width/height so stacked children + header fit inside."""
    if not kids:
        return base_w, base_h
    w = max(base_w, max(widths[k["id"]] for k in kids) + 2 * pad)
    h = header_h + 6 + sum(heights[k["id"]] for k in kids) + gap * (len(kids) - 1) + pad
    return w, h


# ---------------------------------------------------------------------------
# Deployment (UML: 3D node/device/execution boxes, nested artifacts,
# communication paths between nodes)
# ---------------------------------------------------------------------------

DEPLOYMENT_NODE_KINDS = ("node", "device", "execution", "artifact")
DEPLOYMENT_CONN_KINDS = ("path", "dependency")
DEPLOYMENT_NODE_W = 230
DEPLOYMENT_NODE_H = 76
DEPLOYMENT_ARTIFACT_W = 200
DEPLOYMENT_ARTIFACT_H = 54
DEPLOYMENT_HEADER_H = 46


def plan_deployment(spec):
    spec = spec or {}
    items = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:16]
    while len(items) < 2:
        items.append({"id": f"n{len(items)}", "label": ""})
    by_id, order = _unique_ids(items, "n")
    for i, n in enumerate(items):
        kind = n.get("kind", "node")
        n["kind"] = kind if kind in DEPLOYMENT_NODE_KINDS else "node"
        n["_accent"] = _box_accent(n, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        default_stereo = {"device": "«device»", "execution": "«executionEnvironment»",
                          "artifact": "«artifact»"}.get(n["kind"], "")
        n["_stereo"] = str(n.get("stereotype", default_stereo))

    conns = []
    for c in (spec.get("connections") or [])[:20]:
        if not isinstance(c, dict):
            continue
        frm, to = str(c.get("from") or ""), str(c.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        kind = c.get("kind", "path")
        if kind not in DEPLOYMENT_CONN_KINDS:
            kind = "path"
        conns.append({"from": frm, "to": to, "kind": kind, "label": str(c.get("label", ""))})

    # Artifacts never act as containers; only node/device/execution do.
    for n in items:
        if n.get("parent") and str(n["parent"]) in by_id and by_id[str(n["parent"])]["kind"] == "artifact":
            n["parent"] = None
    widths, heights = {}, {}
    for n in items:
        if n["kind"] == "artifact":
            widths[n["id"]], heights[n["id"]] = DEPLOYMENT_ARTIFACT_W, DEPLOYMENT_ARTIFACT_H
        else:
            widths[n["id"]], heights[n["id"]] = DEPLOYMENT_NODE_W, DEPLOYMENT_NODE_H
    kids_of = {}
    for n in items:
        p = str(n.get("parent") or "")
        if p and p in by_id and p != n["id"]:
            kids_of.setdefault(p, []).append(n)
    for n in items:
        if n["id"] in kids_of:
            widths[n["id"]], heights[n["id"]] = _container_grow(
                n, kids_of[n["id"]], widths, heights, DEPLOYMENT_NODE_W, DEPLOYMENT_NODE_H + 20,
                DEPLOYMENT_HEADER_H)

    boxes, bottom, layer, children_of = _container_boxes(
        items, by_id, [(c["from"], c["to"]) for c in conns], widths, heights, DEPLOYMENT_HEADER_H)
    for n in items:
        n["_box"] = boxes[n["id"]]

    _route_box_relations(conns, boxes, layer)
    flow, edges = [], []
    for i, c in enumerate(conns):
        c["_style"] = "dashed" if c["kind"] == "dependency" else "solid"
        c["_arrow"] = "open" if c["kind"] == "dependency" else False
        edges.append({"id": f"e.dep.{i}", "from": c["from"], "to": c["to"], "points": c["_points"],
                      "color": "white", "label": c["label"], "style": c["_style"], "loop": c["from"] == c["to"]})
        flow.append({"points": [list(p) for p in c["_points"]],
                     "color": by_id[c["from"]]["_accent"],
                     "offset": round(i / max(1, len(conns)), 4)})

    nodes, pulses = [], []
    for n in items:
        x, y, w, h = n["_box"]
        nodes.append(_node(n["id"], "card", x, y, w, h, label=n.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": n["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "deployment",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "deployment": {"nodes": items, "connections": conns, "children": children_of},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Component (UML: «component» boxes, provided (ball) / required (socket)
# interfaces, dependency / realization / assembly connectors)
# ---------------------------------------------------------------------------

COMPONENT_REL_KINDS = ("dependency", "realization", "assembly")
COMPONENT_IF_KINDS = ("provided", "required")
COMPONENT_BOX_W = 230
COMPONENT_BOX_H = 84
COMPONENT_IF_R = 10


def plan_component(spec):
    spec = spec or {}
    comps = [dict(c) for c in (spec.get("components") or []) if isinstance(c, dict)][:12]
    while len(comps) < 2:
        comps.append({"id": f"c{len(comps)}", "label": ""})
    by_id, order = _unique_ids(comps, "c")
    for i, c in enumerate(comps):
        c["_accent"] = _box_accent(c, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        c["_stereo"] = str(c.get("stereotype", "«component»"))
        body_rows = len([r for r in str(c.get("body", "")).split("\n") if r.strip()])
        c["_h"] = COMPONENT_BOX_H + (18 * body_rows if body_rows else 0)

    interfaces = []
    for itf in (spec.get("interfaces") or [])[:12]:
        if not isinstance(itf, dict):
            continue
        owner = str(itf.get("component") or "")
        if owner not in by_id:
            continue
        kind = itf.get("kind", "provided")
        if kind not in COMPONENT_IF_KINDS:
            kind = "provided"
        iid = str(itf.get("id") or f"if{len(interfaces)}")
        while iid in {i["id"] for i in interfaces}:
            iid += "_"
        interfaces.append({"id": iid, "label": str(itf.get("label", "")), "kind": kind, "component": owner})
    if_ids = {i["id"] for i in interfaces}
    known = set(order) | if_ids

    rels = []
    for r in (spec.get("relations") or [])[:16]:
        if not isinstance(r, dict):
            continue
        frm, to = str(r.get("from") or ""), str(r.get("to") or "")
        if frm not in known or to not in known:
            continue
        kind = r.get("kind", "dependency")
        if kind not in COMPONENT_REL_KINDS:
            kind = "dependency"
        rels.append({"from": frm, "to": to, "kind": kind, "label": str(r.get("label", ""))})

    widths = {c["id"]: COMPONENT_BOX_W for c in comps}
    heights = {c["id"]: c["_h"] for c in comps}
    boxes, bottom, layer = _layered_boxes(
        order, [(r["from"], r["to"]) for r in rels if r["from"] in by_id and r["to"] in by_id],
        widths, heights)
    for c in comps:
        c["_box"] = boxes[c["id"]]

    # Interfaces hug the component edge: provided on the right, required left.
    per_comp = {}
    for itf in interfaces:
        per_comp.setdefault((itf["component"], itf["kind"]), []).append(itf)
    for itf in interfaces:
        cx, cy, cw, ch = boxes[itf["component"]]
        idx = per_comp[(itf["component"], itf["kind"])].index(itf)
        iy = cy + 26 + idx * 40
        ix = cx + cw if itf["kind"] == "provided" else cx
        itf["_cx"], itf["_cy"] = round(ix), round(min(iy, cy + ch - 16))
        boxes[itf["id"]] = (itf["_cx"] - COMPONENT_IF_R, itf["_cy"] - COMPONENT_IF_R,
                            2 * COMPONENT_IF_R, 2 * COMPONENT_IF_R)

    _route_box_relations(rels, boxes, layer)
    style_arrow = {"dependency": ("dashed", "open"), "realization": ("dashed", "triangle"),
                   "assembly": ("solid", False)}
    flow, edges = [], []
    for i, r in enumerate(rels):
        r["_style"], r["_arrow"] = style_arrow[r["kind"]]
        edges.append({"id": f"e.cmp.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": r["label"], "style": r["_style"], "loop": False})
        color = by_id[r["from"]]["_accent"] if r["from"] in by_id else "green"
        flow.append({"points": [list(p) for p in r["_points"]], "color": color,
                     "offset": round(i / max(1, len(rels)), 4)})

    nodes, pulses = [], []
    for c in comps:
        x, y, w, h = c["_box"]
        nodes.append(_node(c["id"], "card", x, y, w, h, label=c.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": c["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "component",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "component": {"components": comps, "interfaces": interfaces, "relations": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Package (UML: tabbed folder boxes with nesting + import/access dependencies)
# ---------------------------------------------------------------------------

PACKAGE_REL_KINDS = ("import", "access", "dependency")
PACKAGE_BOX_W = 210
PACKAGE_BOX_H = 66
PACKAGE_HEADER_H = 46


def plan_package(spec):
    spec = spec or {}
    pkgs = [dict(p) for p in (spec.get("packages") or []) if isinstance(p, dict)][:14]
    while len(pkgs) < 2:
        pkgs.append({"id": f"p{len(pkgs)}", "label": ""})
    by_id, order = _unique_ids(pkgs, "p")
    for i, p in enumerate(pkgs):
        p["_accent"] = _box_accent(p, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        p["_stereo"] = str(p.get("stereotype", ""))

    rels = []
    for r in (spec.get("relations") or [])[:16]:
        if not isinstance(r, dict):
            continue
        frm, to = str(r.get("from") or ""), str(r.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        kind = r.get("kind", "dependency")
        if kind not in PACKAGE_REL_KINDS:
            kind = "dependency"
        rels.append({"from": frm, "to": to, "kind": kind, "label": str(r.get("label", ""))})

    kids_of = {}
    for p in pkgs:
        par = str(p.get("parent") or "")
        if par and par in by_id and par != p["id"]:
            kids_of.setdefault(par, []).append(p)
    widths, heights = {}, {}
    for p in pkgs:
        widths[p["id"]], heights[p["id"]] = _container_grow(
            p, kids_of.get(p["id"], []),
            {k["id"]: PACKAGE_BOX_W for k in pkgs}, {k["id"]: PACKAGE_BOX_H for k in pkgs},
            PACKAGE_BOX_W, PACKAGE_BOX_H, PACKAGE_HEADER_H)
    boxes, bottom, layer, children_of = _container_boxes(
        pkgs, by_id, [(r["from"], r["to"]) for r in rels], widths, heights, PACKAGE_HEADER_H)
    for p in pkgs:
        p["_box"] = boxes[p["id"]]

    _route_box_relations(rels, boxes, layer)
    flow, edges = [], []
    for i, r in enumerate(rels):
        r["_style"], r["_arrow"] = "dashed", "open"
        label = r["label"] or (f"«{r['kind']}»" if r["kind"] != "dependency" else "")
        edges.append({"id": f"e.pkg.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": label, "style": "dashed", "loop": False})
        flow.append({"points": [list(p) for p in r["_points"]],
                     "color": by_id[r["from"]]["_accent"],
                     "offset": round(i / max(1, len(rels)), 4)})

    nodes, pulses = [], []
    for p in pkgs:
        x, y, w, h = p["_box"]
        nodes.append(_node(p["id"], "card", x, y, w, h, label=p.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": p["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "package",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "package": {"packages": pkgs, "relations": rels, "children": children_of},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Object (UML: instance boxes "name: Class" with attribute = value rows,
# plain links between instances)
# ---------------------------------------------------------------------------

OBJECT_BOX_W = 230
OBJECT_HEADER_H = 32
OBJECT_ROW_H = 20


def plan_object(spec):
    spec = spec or {}
    objects = [dict(o) for o in (spec.get("objects") or []) if isinstance(o, dict)][:12]
    while len(objects) < 2:
        objects.append({"id": f"o{len(objects)}", "name": ""})
    by_id, order = _unique_ids(objects, "o")
    for i, o in enumerate(objects):
        o["_accent"] = _box_accent(o, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        o["_title"] = str(o.get("name", "")) + (f": {o['class']}" if o.get("class") else "")
        attrs = []
        for a in (o.get("attributes") or [])[:8]:
            if isinstance(a, dict) and a.get("name"):
                attrs.append({"name": str(a.get("name")), "value": str(a.get("value", ""))})
            elif isinstance(a, str) and a.strip():
                attrs.append({"name": a.strip(), "value": ""})
        o["_attrs"] = attrs
        o["_h"] = OBJECT_HEADER_H + 10 + OBJECT_ROW_H * max(1, len(attrs)) + 10

    links = []
    for l in (spec.get("links") or [])[:16]:
        if not isinstance(l, dict):
            continue
        frm, to = str(l.get("from") or ""), str(l.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        links.append({"from": frm, "to": to, "label": str(l.get("label", ""))})

    widths = {o["id"]: OBJECT_BOX_W for o in objects}
    heights = {o["id"]: o["_h"] for o in objects}
    boxes, bottom, layer = _layered_boxes(order, [(l["from"], l["to"]) for l in links], widths, heights)
    for o in objects:
        o["_box"] = boxes[o["id"]]

    _route_box_relations(links, boxes, layer)
    flow, edges = [], []
    for i, l in enumerate(links):
        edges.append({"id": f"e.obj.{i}", "from": l["from"], "to": l["to"], "points": l["_points"],
                      "color": "white", "label": l["label"], "style": "solid", "loop": l["from"] == l["to"]})
        flow.append({"points": [list(p) for p in l["_points"]],
                     "color": by_id[l["from"]]["_accent"],
                     "offset": round(i / max(1, len(links)), 4)})

    nodes, pulses = [], []
    for o in objects:
        x, y, w, h = o["_box"]
        nodes.append(_node(o["id"], "card", x, y, w, h, label=o["_title"]))
        pulses.append({"box": [x, y, x + w, y + h], "color": o["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "object",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "object": {"objects": objects, "links": links},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Composite structure (UML: classifier boundary, internal part boxes, small
# square ports on part edges, connectors between parts/ports)
# ---------------------------------------------------------------------------

COMPOSITE_PART_W = 210
COMPOSITE_PART_H = 84
COMPOSITE_PORT = 18


def plan_composite(spec):
    spec = spec or {}
    parts = [dict(p) for p in (spec.get("parts") or []) if isinstance(p, dict)][:10]
    while len(parts) < 2:
        parts.append({"id": f"pt{len(parts)}", "label": ""})
    by_id, order = _unique_ids(parts, "pt")
    for i, p in enumerate(parts):
        p["_accent"] = _box_accent(p, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        p["_type"] = str(p.get("type", ""))

    ports = []
    for po in (spec.get("ports") or [])[:12]:
        if not isinstance(po, dict):
            continue
        owner = str(po.get("part") or "")
        if owner not in by_id:
            continue
        side = po.get("side", "right")
        pid = str(po.get("id") or f"po{len(ports)}")
        while pid in {q["id"] for q in ports}:
            pid += "_"
        ports.append({"id": pid, "part": owner, "label": str(po.get("label", "")),
                      "side": side if side in ("left", "right", "top", "bottom") else "right"})
    port_ids = {p["id"] for p in ports}

    conns = []
    known = set(order) | port_ids
    for c in (spec.get("connectors") or [])[:16]:
        if not isinstance(c, dict):
            continue
        frm, to = str(c.get("from") or ""), str(c.get("to") or "")
        if frm not in known or to not in known:
            continue
        conns.append({"from": frm, "to": to, "label": str(c.get("label", ""))})

    widths = {p["id"]: COMPOSITE_PART_W for p in parts}
    heights = {p["id"]: COMPOSITE_PART_H for p in parts}
    boxes, bottom, layer = _layered_boxes(
        order, [(c["from"], c["to"]) for c in conns if c["from"] in by_id and c["to"] in by_id],
        widths, heights, top=260, x_lo=180.0, x_hi=1030.0)
    for p in parts:
        p["_box"] = boxes[p["id"]]

    for po in ports:
        px, py, pw, ph = boxes[po["part"]]
        side = po["side"]
        if side == "left":
            cx, cy = px, py + ph / 2
        elif side == "top":
            cx, cy = px + pw / 2, py
        elif side == "bottom":
            cx, cy = px + pw / 2, py + ph
        else:
            cx, cy = px + pw, py + ph / 2
        s = COMPOSITE_PORT
        po["_box"] = (round(cx - s / 2), round(cy - s / 2), s, s)
        boxes[po["id"]] = po["_box"]

    _route_box_relations(conns, boxes, layer)
    flow, edges = [], []
    for i, c in enumerate(conns):
        edges.append({"id": f"e.cst.{i}", "from": c["from"], "to": c["to"], "points": c["_points"],
                      "color": "white", "label": c["label"], "style": "solid", "loop": False})
        flow.append({"points": [list(p) for p in c["_points"]], "color": "cyan",
                     "offset": round(i / max(1, len(conns)), 4)})

    xs = [b[0] for b in (p["_box"] for p in parts)]
    ys = [b[1] for b in (p["_box"] for p in parts)]
    xr = [b[0] + b[2] for b in (p["_box"] for p in parts)]
    yb = [b[1] + b[3] for b in (p["_box"] for p in parts)]
    boundary = {"x": min(xs) - 60, "y": min(ys) - 90, "w": max(xr) - min(xs) + 120,
                "h": max(yb) - min(ys) + 150, "label": str(spec.get("classifier", ""))}

    nodes, pulses = [], []
    for p in parts:
        x, y, w, h = p["_box"]
        nodes.append(_node(p["id"], "card", x, y, w, h, label=p.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": p["_accent"]})

    height = int(boundary["y"] + boundary["h"]) + 90 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "composite",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "composite": {"parts": parts, "ports": ports, "connectors": conns, "boundary": boundary},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Profile (UML: «stereotype» / «metaclass» boxes, extension arrows with a
# filled head, dashed dependencies)
# ---------------------------------------------------------------------------

PROFILE_BOX_W = 230
PROFILE_HEADER_H = 32
PROFILE_STEREO_H = 16
PROFILE_ROW_H = 20


def plan_profile(spec):
    spec = spec or {}
    items = []
    for s in (spec.get("stereotypes") or [])[:8]:
        if isinstance(s, dict):
            items.append({**s, "kind": "stereotype"})
    for m in (spec.get("metaclasses") or [])[:6]:
        if isinstance(m, dict):
            items.append({**m, "kind": "metaclass"})
    while len(items) < 2:
        items.append({"id": f"pf{len(items)}", "label": "", "kind": "stereotype"})
    by_id, order = _unique_ids(items, "pf")
    for i, it in enumerate(items):
        it["_accent"] = _box_accent(it, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        it["_stereo"] = f"«{it['kind']}»"
        attrs = [str(a) for a in (it.get("attributes") or [])[:6] if str(a).strip()]
        it["_attrs"] = attrs
        it["_h"] = (PROFILE_HEADER_H + PROFILE_STEREO_H + 10
                    + PROFILE_ROW_H * len(attrs) + (10 if attrs else 4))

    exts, deps = [], []
    for e in (spec.get("extensions") or [])[:12]:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or ""), str(e.get("to") or "")
        if frm in by_id and to in by_id:
            exts.append({"from": frm, "to": to, "kind": "extension", "label": ""})
    for d in (spec.get("relations") or [])[:8]:
        if not isinstance(d, dict):
            continue
        frm, to = str(d.get("from") or ""), str(d.get("to") or "")
        if frm in by_id and to in by_id:
            deps.append({"from": frm, "to": to, "kind": "dependency", "label": str(d.get("label", ""))})
    rels = exts + deps

    widths = {it["id"]: PROFILE_BOX_W for it in items}
    heights = {it["id"]: it["_h"] for it in items}
    boxes, bottom, layer = _layered_boxes(order, [(r["from"], r["to"]) for r in rels], widths, heights)
    for it in items:
        it["_box"] = boxes[it["id"]]

    _route_box_relations(rels, boxes, layer)
    flow, edges = [], []
    for i, r in enumerate(rels):
        r["_style"] = "solid" if r["kind"] == "extension" else "dashed"
        r["_arrow"] = "filled" if r["kind"] == "extension" else "open"
        edges.append({"id": f"e.prf.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": r["label"], "style": r["_style"], "loop": False})
        flow.append({"points": [list(p) for p in r["_points"]],
                     "color": by_id[r["from"]]["_accent"],
                     "offset": round(i / max(1, len(rels)), 4)})

    nodes, pulses = [], []
    for it in items:
        x, y, w, h = it["_box"]
        nodes.append(_node(it["id"], "card", x, y, w, h, label=it.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": it["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "profile",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "profile": {"items": items, "relations": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Communication (UML: object boxes + links carrying numbered messages)
# ---------------------------------------------------------------------------

COMMUNICATION_BOX_W = 190
COMMUNICATION_BOX_H = 64


def plan_communication(spec):
    spec = spec or {}
    objects = [dict(o) for o in (spec.get("objects") or []) if isinstance(o, dict)][:12]
    while len(objects) < 2:
        objects.append({"id": f"o{len(objects)}", "label": ""})
    by_id, order = _unique_ids(objects, "o")
    for i, o in enumerate(objects):
        o["_accent"] = _box_accent(o, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])

    links = []
    for l in (spec.get("links") or [])[:20]:
        if not isinstance(l, dict):
            continue
        frm, to = str(l.get("from") or ""), str(l.get("to") or "")
        if frm not in by_id or to not in by_id or frm == to:
            continue
        msgs = []
        for m in (l.get("messages") or [])[:6]:
            if isinstance(m, dict) and m.get("label"):
                direction = m.get("dir", "forward")
                msgs.append({"num": str(m.get("num", len(msgs) + 1)),
                             "label": str(m.get("label"))[:24],
                             "dir": "back" if direction == "back" else "forward"})
            elif isinstance(m, str) and m.strip():
                msgs.append({"num": str(len(msgs) + 1), "label": m.strip()[:24], "dir": "forward"})
        links.append({"from": frm, "to": to, "messages": msgs})

    widths = {o["id"]: COMMUNICATION_BOX_W for o in objects}
    heights = {o["id"]: COMMUNICATION_BOX_H for o in objects}
    boxes, bottom, layer = _layered_boxes(order, [(l["from"], l["to"]) for l in links],
                                          widths, heights, gap_v=90)
    for o in objects:
        o["_box"] = boxes[o["id"]]

    _route_box_relations(links, boxes, layer)
    flow, edges = [], []
    for i, l in enumerate(links):
        edges.append({"id": f"e.com.{i}", "from": l["from"], "to": l["to"], "points": l["_points"],
                      "color": "white", "label": "", "style": "solid", "loop": False})
        flow.append({"points": [list(p) for p in l["_points"]],
                     "color": by_id[l["from"]]["_accent"],
                     "offset": round(i / max(1, len(links)), 4)})

    nodes, pulses = [], []
    for o in objects:
        x, y, w, h = o["_box"]
        nodes.append(_node(o["id"], "card", x, y, w, h, label=o.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": o["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "communication",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "communication": {"objects": objects, "links": links},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Timing (UML: horizontal lifelines with step-shaped state levels over a
# shared time axis, optional dashed messages between lifelines)
# ---------------------------------------------------------------------------

TIMING_LABEL_X = 90
TIMING_CHART_X0 = 270.0
TIMING_CHART_X1 = 1150.0
TIMING_STATE_PITCH = 34
TIMING_BAND_PAD = 26


def _timing_state_at(events, t):
    """State name active at time t (last event at or before t)."""
    state = None
    for e in events:
        if e["t"] <= t:
            state = e["state"]
        else:
            break
    return state


def plan_timing(spec):
    spec = spec or {}
    lifelines = [dict(l) for l in (spec.get("lifelines") or []) if isinstance(l, dict)][:5]
    while len(lifelines) < 1:
        lifelines.append({"id": "l0", "label": "", "states": ["on", "off"],
                          "events": [{"t": 0, "state": "off"}, {"t": 5, "state": "on"}]})
    by_id, order = _unique_ids(lifelines, "l")

    t_min, t_max = None, None
    for i, l in enumerate(lifelines):
        l["_accent"] = _box_accent(l, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        states = []
        for s in (l.get("states") or [])[:5]:
            s = str(s).strip()
            if s and s not in states:
                states.append(s)
        events = []
        for e in (l.get("events") or [])[:12]:
            if not isinstance(e, dict):
                continue
            try:
                t = float(e.get("t"))
            except (TypeError, ValueError):
                continue
            st = str(e.get("state", "")).strip()
            if st and st not in states:
                states.append(st)
            if st:
                events.append({"t": t, "state": st})
        events.sort(key=lambda e: e["t"])
        while len(states) < 2:
            states.append(["off", "on"][len(states)])
        l["_states"] = states
        l["_events"] = events
        if events:
            t_min = events[0]["t"] if t_min is None else min(t_min, events[0]["t"])
            t_max = events[-1]["t"] if t_max is None else max(t_max, events[-1]["t"])
    if t_min is None:
        t_min, t_max = 0.0, 10.0
    if t_max <= t_min:
        t_max = t_min + 10.0

    def x_at(t):
        return TIMING_CHART_X0 + (t - t_min) / (t_max - t_min) * (TIMING_CHART_X1 - TIMING_CHART_X0)

    # Bands stack top-down; each lifeline gets one row per state + padding.
    y = 210.0
    for l in lifelines:
        n_states = len(l["_states"])
        band_h = TIMING_BAND_PAD * 2 + (n_states - 1) * TIMING_STATE_PITCH
        l["_band"] = (round(y), round(band_h))
        level_y = {s: y + TIMING_BAND_PAD + (n_states - 1 - j) * TIMING_STATE_PITCH
                   for j, s in enumerate(l["_states"])}
        l["_level_y"] = level_y
        # Step polyline across the band.
        events = l["_events"]
        pts = []
        if events:
            first_state = events[0]["state"]
            pts.append((x_at(t_min), level_y[first_state]))
            for k, e in enumerate(events):
                ey = level_y[e["state"]]
                px, py = pts[-1]
                if abs(py - ey) > 1:
                    pts.append((x_at(e["t"]), py))   # horizontal to the change
                    pts.append((x_at(e["t"]), ey))   # vertical transition
                else:
                    pts.append((x_at(e["t"]), ey))
            pts.append((x_at(t_max), pts[-1][1]))
        else:
            mid = level_y[l["_states"][0]]
            pts = [(x_at(t_min), mid), (x_at(t_max), mid)]
        l["_points"] = [(round(px, 1), round(py, 1)) for px, py in pts]
        y += band_h + 26
    axis_y = y + 6

    # Time ticks: up to 8 evenly spaced values.
    n_ticks = min(8, int(t_max - t_min) + 1 if (t_max - t_min) <= 8 else 8)
    ticks = []
    for k in range(max(2, n_ticks)):
        t = t_min + (t_max - t_min) * k / (max(2, n_ticks) - 1)
        tv = int(t) if float(t).is_integer() else round(t, 1)
        ticks.append({"t": tv, "x": round(x_at(t))})

    messages = []
    for m in (spec.get("messages") or [])[:10]:
        if not isinstance(m, dict):
            continue
        frm, to = str(m.get("from") or ""), str(m.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        try:
            t = float(m.get("t", t_min))
        except (TypeError, ValueError):
            continue
        t = min(max(t, t_min), t_max)
        fl, tl = by_id[frm], by_id[to]
        fs = _timing_state_at(fl["_events"], t) or fl["_states"][0]
        ts = _timing_state_at(tl["_events"], t) or tl["_states"][0]
        x = x_at(t)
        p1 = (round(x), round(fl["_level_y"][fs]))
        p2 = (round(x), round(tl["_level_y"][ts]))
        messages.append({"from": frm, "to": to, "t": t, "label": str(m.get("label", "")),
                         "_points": [p1, p2]})

    flow = [{"points": [list(p) for p in l["_points"]], "color": l["_accent"],
             "offset": round(i / max(1, len(lifelines)), 4)} for i, l in enumerate(lifelines)]
    nodes, pulses, edges = [], [], []
    for l in lifelines:
        bx, by = l["_band"][0] - 8, l["_band"][0]
        bw = TIMING_CHART_X1 - TIMING_LABEL_X + 16
        nodes.append(_node(l["id"], "card", TIMING_LABEL_X, by, bw, l["_band"][1], label=l.get("label", "")))
        pulses.append({"box": [TIMING_LABEL_X, by, TIMING_CHART_X1 + 8, by + l["_band"][1]],
                       "color": l["_accent"]})
    for i, m in enumerate(messages):
        edges.append({"id": f"e.tim.{i}", "from": m["from"], "to": m["to"], "points": m["_points"],
                      "color": "muted", "label": m["label"], "style": "dashed", "loop": False})

    height = int(axis_y) + 74 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "timing",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "timing": {"lifelines": lifelines, "messages": messages, "ticks": ticks,
                   "axis": {"y": round(axis_y), "x0": round(TIMING_CHART_X0), "x1": round(TIMING_CHART_X1),
                            "t_min": t_min, "t_max": t_max}},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Interaction overview (UML: activity-shaped flow whose nodes are framed
# references ("sd <name>") to other interaction diagrams)
# ---------------------------------------------------------------------------

INTERACTION_NODE_KINDS = ("initial", "final", "interaction", "decision")
INTERACTION_FRAME_W = 220
INTERACTION_FRAME_H = 92


def plan_interaction(spec):
    spec = spec or {}
    nodes = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:16]
    if not nodes:
        nodes = [{"id": "start", "kind": "initial"},
                 {"id": "f1", "label": "", "kind": "interaction"},
                 {"id": "end", "kind": "final"}]
    by_id, order = _unique_ids(nodes, "n")
    initials = 0
    for i, n in enumerate(nodes):
        kind = n.get("kind", "interaction")
        n["kind"] = kind if kind in INTERACTION_NODE_KINDS else "interaction"
        n["_accent"] = _box_accent(n, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        n["_ref_kind"] = str(n.get("ref", "sd")) if n["kind"] == "interaction" else ""
        initials += n["kind"] == "initial"
    if initials == 0:
        start = {"id": "_start", "kind": "initial", "label": "", "_accent": "green", "_ref_kind": ""}
        while start["id"] in by_id:
            start["id"] += "_"
        nodes.insert(0, start)
        by_id[start["id"]] = start
        order.insert(0, start["id"])
        first_frame = next((n for n in nodes[1:] if n["kind"] != "final"), None)
        if first_frame is not None:
            spec_edges = list(spec.get("edges") or [])
            spec_edges.insert(0, {"from": start["id"], "to": first_frame["id"]})
            spec = dict(spec, edges=spec_edges)

    edges = []
    for e in (spec.get("edges") or [])[:24]:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or ""), str(e.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        edges.append({"from": frm, "to": to, "label": str(e.get("label", ""))})

    widths, heights = {}, {}
    for n in nodes:
        if n["kind"] in ("initial", "final"):
            widths[n["id"]] = heights[n["id"]] = ACTIVITY_DOT
        elif n["kind"] == "decision":
            widths[n["id"]] = heights[n["id"]] = ACTIVITY_DIAMOND
        else:
            widths[n["id"]], heights[n["id"]] = INTERACTION_FRAME_W, INTERACTION_FRAME_H
    boxes, bottom, layer = _layered_boxes(order, [(e["from"], e["to"]) for e in edges],
                                          widths, heights, gap_v=64, direction="down")
    for n in nodes:
        n["_box"] = boxes[n["id"]]

    flow, gedges, rels = [], [], []
    max_right = max(b[0] + b[2] for b in boxes.values())
    skip_i = 0
    for i, e in enumerate(edges):
        a, b = boxes[e["from"]], boxes[e["to"]]
        back = e["from"] != e["to"] and layer.get(e["to"], 0) <= layer.get(e["from"], 0)
        if e["from"] == e["to"]:
            pts = _self_link(a)
            style = "dashed"
        elif back:
            style = "dashed"
            lane_x = 120
            p1 = (a[0], a[1] + a[3] / 2)
            p2 = (b[0], b[1] + b[3] / 2)
            pts = [p1, (lane_x, p1[1]), (lane_x, p2[1]), p2]
        elif layer.get(e["to"], 0) - layer.get(e["from"], 0) >= 2:
            # Forward skip: swing around intervening frames via a right lane.
            style = "solid"
            skip_i += 1
            lane_x = min(1130, max_right + 36 + (skip_i - 1) * 30)
            p1 = (a[0] + a[2], a[1] + a[3] / 2)
            p2 = (b[0] + b[2], b[1] + b[3] / 2)
            pts = [p1, (lane_x, p1[1]), (lane_x, p2[1]), p2]
        else:
            pts = _box_link(a, b)
            style = "solid"
        e["_points"] = [(round(px), round(py)) for px, py in pts]
        e["_style"] = style
        e["_back"] = back or e["from"] == e["to"]
        rels.append(e)
        gedges.append({"id": f"e.io.{i}", "from": e["from"], "to": e["to"], "points": e["_points"],
                       "color": "muted" if e["_back"] else "white", "label": e["label"],
                       "style": style, "loop": e["_back"]})
        flow.append({"points": [list(p) for p in e["_points"]],
                     "color": by_id[e["from"]]["_accent"] if not e["_back"] else "purple",
                     "offset": round(0.8 * i / max(1, len(edges)), 4)})

    gnodes, pulses = [], []
    for n in nodes:
        x, y, w, h = n["_box"]
        kind = n["kind"]
        gnodes.append(_node(n["id"], "terminal" if kind in ("initial", "final") else
                            ("decision" if kind == "decision" else "card"),
                            x, y, w, h, label=n.get("label", "")))
        pulses.append({"box": [x - 6, y - 6, x + w + 6, y + h + 6], "color": n["_accent"]})

    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "interaction",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "interaction": {"nodes": nodes, "edges": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": gnodes,
        "edges": gedges,
    }


# ---------------------------------------------------------------------------
# C4 (Context/Container style: person/system/container/database boxes grouped
# by dashed boundary rectangles, labeled relationships)
# ---------------------------------------------------------------------------

C4_KINDS = ("person", "system", "ext_system", "container", "database", "queue")
C4_BOX_W = 200
C4_BOX_H = 92
C4_PERSON_W = 170


def plan_c4(spec):
    spec = spec or {}
    elements = [dict(e) for e in (spec.get("elements") or []) if isinstance(e, dict)][:16]
    while len(elements) < 2:
        elements.append({"id": f"e{len(elements)}", "label": "", "kind": "system"})
    by_id, order = _unique_ids(elements, "e")
    for i, e in enumerate(elements):
        kind = e.get("kind", "system")
        e["kind"] = kind if kind in C4_KINDS else "system"
        e["_accent"] = _box_accent(e, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        e["_tech"] = str(e.get("technology", ""))
        e["_desc"] = str(e.get("description", ""))
        e["_boundary"] = str(e.get("boundary") or "")

    boundaries = []
    for b in (spec.get("boundaries") or [])[:4]:
        if isinstance(b, dict) and b.get("id"):
            boundaries.append({"id": str(b["id"]), "label": str(b.get("label", ""))})
    bound_ids = {b["id"] for b in boundaries}
    for e in elements:
        if e["_boundary"] not in bound_ids:
            e["_boundary"] = ""

    rels = []
    for r in (spec.get("relations") or [])[:20]:
        if not isinstance(r, dict):
            continue
        frm, to = str(r.get("from") or ""), str(r.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        rels.append({"from": frm, "to": to, "label": str(r.get("label", "")),
                     "technology": str(r.get("technology", "")),
                     "_style": "dashed" if r.get("style") == "dashed" else "solid"})

    widths = {e["id"]: (C4_PERSON_W if e["kind"] == "person" else C4_BOX_W) for e in elements}
    heights = {e["id"]: C4_BOX_H for e in elements}
    boxes, bottom, layer = _layered_boxes(order, [(r["from"], r["to"]) for r in rels],
                                          widths, heights, gap_v=70)
    for e in elements:
        e["_box"] = boxes[e["id"]]

    # Boundary = dashed rectangle around its members' bounding box + padding.
    for b in boundaries:
        members = [e["_box"] for e in elements if e["_boundary"] == b["id"]]
        if not members:
            b["_box"] = None
            continue
        x0 = min(m[0] for m in members) - 30
        y0 = min(m[1] for m in members) - 52
        x1 = max(m[0] + m[2] for m in members) + 30
        y1 = max(m[1] + m[3] for m in members) + 30
        b["_box"] = (round(x0), round(y0), round(x1 - x0), round(y1 - y0))

    _route_box_relations(rels, boxes, layer)
    flow, edges = [], []
    for i, r in enumerate(rels):
        edges.append({"id": f"e.c4.{i}", "from": r["from"], "to": r["to"], "points": r["_points"],
                      "color": "white", "label": r["label"], "style": r["_style"], "loop": False})
        flow.append({"points": [list(p) for p in r["_points"]],
                     "color": by_id[r["from"]]["_accent"],
                     "offset": round(i / max(1, len(rels)), 4)})

    nodes, pulses = [], []
    for e in elements:
        x, y, w, h = e["_box"]
        nodes.append(_node(e["id"], "card", x, y, w, h, label=e.get("label", "")))
        pulses.append({"box": [x, y, x + w, y + h], "color": e["_accent"]})

    bottom = max([bottom] + [b["_box"][1] + b["_box"][3] for b in boundaries if b["_box"]])
    height = int(bottom) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "c4",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "c4": {"elements": elements, "boundaries": boundaries, "relations": rels},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Gantt (sections of task bars over a date axis; done/active/crit bars +
# milestone diamonds)
# ---------------------------------------------------------------------------

GANTT_TASK_KINDS = ("task", "done", "active", "crit", "milestone")
GANTT_LABEL_X = 70
GANTT_LABEL_W = 210
GANTT_CHART_X0 = 300.0
GANTT_CHART_X1 = 1150.0
GANTT_ROW_H = 38
GANTT_SECTION_H = 40


def _gantt_day(value):
    """Parse 'YYYY-MM-DD' or a plain day number into an ordinal float."""
    from datetime import date as _date
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None
    try:
        d = _date.fromisoformat(str(value)[:10])
        return float(d.toordinal()), d.isoformat()
    except ValueError:
        return None, None


def plan_gantt(spec):
    spec = spec or {}
    sections = []
    for s in (spec.get("sections") or [])[:8]:
        if not isinstance(s, dict):
            continue
        tasks = []
        for t in (s.get("tasks") or [])[:10]:
            if not isinstance(t, dict):
                continue
            kind = t.get("kind", "task")
            if kind not in GANTT_TASK_KINDS:
                kind = "task"
            start, start_label = _gantt_day(t.get("start"))
            end, end_label = _gantt_day(t.get("end")) if t.get("end") is not None else (None, None)
            if start is None:
                continue
            if end is None:
                dur = t.get("duration", 3)
                try:
                    dur = float(str(dur).rstrip("d"))
                except (TypeError, ValueError):
                    dur = 3.0
                end = start + max(1.0, dur)
            if end <= start:
                end = start + 1.0
            tasks.append({"label": str(t.get("label", "")), "kind": kind,
                          "_start": start, "_end": end, "_when": start_label or str(t.get("start"))})
        sections.append({"label": str(s.get("label", "")), "tasks": tasks})
    if not sections:
        sections = [{"label": "", "tasks": [{"label": "", "kind": "task", "_start": 0.0,
                                             "_end": 3.0, "_when": "0"}]}]
    total = sum(len(s["tasks"]) for s in sections)
    while total < 1:
        sections[0]["tasks"].append({"label": "", "kind": "task", "_start": 0.0, "_end": 3.0, "_when": "0"})
        total += 1

    d_min = min(t["_start"] for s in sections for t in s["tasks"])
    d_max = max(t["_end"] for s in sections for t in s["tasks"])
    if d_max <= d_min:
        d_max = d_min + 1.0  # pragma: no cover - _end is always > _start (clamped above)

    def x_at(d):
        return GANTT_CHART_X0 + (d - d_min) / (d_max - d_min) * (GANTT_CHART_X1 - GANTT_CHART_X0)

    y = 220.0
    for s in sections:
        s["_y"] = round(y)
        y += GANTT_SECTION_H
        for t in s["tasks"]:
            t["_y"] = round(y)
            t["_x0"] = round(x_at(t["_start"]))
            t["_x1"] = round(x_at(t["_end"] if t["kind"] != "milestone" else t["_start"]))
            y += GANTT_ROW_H
        s["_y1"] = round(y)
    axis_y = y + 14

    # Date ticks: at most 8, evenly spaced, formatted from real dates if used.
    from datetime import date as _date
    n_ticks = 8
    ticks = []
    for k in range(n_ticks):
        d = d_min + (d_max - d_min) * k / (n_ticks - 1)
        try:
            label = _date.fromordinal(int(round(d))).isoformat()[5:] if d > 700000 else str(int(d))
        except ValueError:
            label = str(int(d))
        ticks.append({"label": label, "x": round(x_at(d))})

    all_tasks = [t for s in sections for t in s["tasks"]]
    flow = [{"points": [[t["_x0"], t["_y"] + 12], [max(t["_x0"], t["_x1"]), t["_y"] + 12]],
             "color": _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)], "offset": round(i / 8, 4)}
            for i, t in enumerate(all_tasks)]
    nodes, pulses, edges = [], [], []
    i = 0
    for s in sections:
        for t in s["tasks"]:
            x0 = t["_x0"]
            w = max(20, t["_x1"] - t["_x0"])
            nodes.append(_node(f"t{i}", "card", x0, t["_y"], w, GANTT_ROW_H - 8, label=t["label"]))
            pulses.append({"box": [x0, t["_y"], x0 + w, t["_y"] + GANTT_ROW_H - 8], "color": "green"})
            i += 1

    height = int(axis_y) + 80 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "gantt",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "gantt": {"sections": sections, "ticks": ticks,
                  "axis": {"y": round(axis_y), "x0": round(GANTT_CHART_X0), "x1": round(GANTT_CHART_X1)}},
        "glow_rects": glow,
        "flow_paths": flow,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# BPMN (core subset: pools/lanes as bands, start/intermediate/end events,
# tasks, exclusive/parallel gateways, sequence + message flows)
# ---------------------------------------------------------------------------

BPMN_ELEMENT_KINDS = ("start", "intermediate", "end", "task", "gateway", "gateway_parallel")
BPMN_FLOW_KINDS = ("sequence", "message")
BPMN_LANE_H = 130
BPMN_TASK_W = 150
BPMN_TASK_H = 62
BPMN_EVENT_R = 15
BPMN_GATEWAY = 58


def plan_bpmn(spec):
    spec = spec or {}
    lanes = []
    pools = spec.get("pools")
    if isinstance(pools, list):
        for pool in pools[:3]:
            if not isinstance(pool, dict):
                continue
            pool_lanes = pool.get("lanes") or []
            for ln in pool_lanes[:4]:
                if isinstance(ln, dict):
                    lanes.append({"id": str(ln.get("id") or f"lane{len(lanes)}"),
                                  "label": str(ln.get("label", "")),
                                  "pool": str(pool.get("label", ""))})
            if not pool_lanes:
                lanes.append({"id": str(pool.get("id") or f"lane{len(lanes)}"),
                              "label": str(pool.get("label", "")), "pool": ""})
    if not lanes:
        lanes = [{"id": "lane0", "label": str(spec.get("lane_label", "")), "pool": ""}]
    lane_ids = {l["id"] for l in lanes}

    elements = [dict(e) for e in (spec.get("elements") or []) if isinstance(e, dict)][:24]
    while len(elements) < 2:
        elements.append({"id": f"el{len(elements)}", "label": "", "kind": "task"})
    by_id, order = _unique_ids(elements, "el")
    for i, e in enumerate(elements):
        kind = e.get("kind", "task")
        e["kind"] = kind if kind in BPMN_ELEMENT_KINDS else "task"
        e["_accent"] = _box_accent(e, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        lane = str(e.get("lane") or "")
        e["_lane"] = lane if lane in lane_ids else lanes[0]["id"]

    flows = []
    for f in (spec.get("flows") or [])[:30]:
        if not isinstance(f, dict):
            continue
        frm, to = str(f.get("from") or ""), str(f.get("to") or "")
        if frm not in by_id or to not in by_id:
            continue
        kind = f.get("kind", "sequence")
        if kind not in BPMN_FLOW_KINDS:
            kind = "sequence"
        flows.append({"from": frm, "to": to, "kind": kind, "label": str(f.get("label", ""))})

    # Lane bands stack vertically, full chart width.
    y = 200.0
    for l in lanes:
        l["_y"] = round(y)
        l["_h"] = BPMN_LANE_H
        y += BPMN_LANE_H
    lane_band = {l["id"]: (l["_y"], l["_h"]) for l in lanes}

    # Columns from sequence-flow layering; elements share x per layer.
    size_for = {"start": (2 * BPMN_EVENT_R, 2 * BPMN_EVENT_R),
                "intermediate": (2 * BPMN_EVENT_R, 2 * BPMN_EVENT_R),
                "end": (2 * BPMN_EVENT_R, 2 * BPMN_EVENT_R),
                "gateway": (BPMN_GATEWAY, BPMN_GATEWAY),
                "gateway_parallel": (BPMN_GATEWAY, BPMN_GATEWAY),
                "task": (BPMN_TASK_W, BPMN_TASK_H)}
    widths = {e["id"]: size_for[e["kind"]][0] for e in elements}
    heights = {e["id"]: size_for[e["kind"]][1] for e in elements}
    fake = {"nodes": [{"id": i} for i in order],
            "edges": [{"from": f["from"], "to": f["to"]} for f in flows if f["from"] != f["to"]]}
    raw_nodes, raw_edges, _by = _graph_prepare(fake)
    layer_map, cols, _manual = _graph_layers(raw_nodes, raw_edges, _by)
    n_layers = (max(cols) + 1) if cols else 1
    col_w = {l: max(widths[i] for i in cols[l]) for l in cols}
    x_lo, x_hi = 150.0, 1100.0
    sum_w = sum(col_w.values())
    gap_u = min(120.0, max(40.0, (x_hi - x_lo - sum_w) / max(1, n_layers - 1)))
    x = x_lo
    col_x = {}
    for l in sorted(col_w):
        col_x[l] = x
        x += col_w[l] + gap_u
    # Stack elements that share (lane, layer) vertically inside the band.
    slot_count = {}
    for e in elements:
        lay = layer_map.get(e["id"], 0)
        band_y, band_h = lane_band[e["_lane"]]
        key = (e["_lane"], lay)
        slot = slot_count.get(key, 0)
        slot_count[key] = slot + 1
        w, h = widths[e["id"]], heights[e["id"]]
        ex = col_x[lay] + (col_w[lay] - w) / 2
        ey = band_y + band_h / 2 - h / 2 + slot * (h + 18)
        if slot:
            ey = min(ey, band_y + band_h - h - 8)
        e["_box"] = (round(ex), round(ey), w, h)

    boxes = {e["id"]: e["_box"] for e in elements}
    flow_paths, edges = [], []
    for i, f in enumerate(flows):
        a, b = boxes[f["from"]], boxes[f["to"]]
        pts = [(round(px), round(py)) for px, py in (_self_link(a) if f["from"] == f["to"]
                                                     else _box_link(a, b))]
        f["_points"] = pts
        f["_style"] = "dashed" if f["kind"] == "message" else "solid"
        edges.append({"id": f"e.bpmn.{i}", "from": f["from"], "to": f["to"], "points": pts,
                      "color": "muted" if f["kind"] == "message" else "white", "label": f["label"],
                      "style": f["_style"], "loop": False})
        flow_paths.append({"points": [list(p) for p in pts],
                           "color": by_id[f["from"]]["_accent"],
                           "offset": round(i / max(1, len(flows)), 4)})

    nodes, pulses = [], []
    for e in elements:
        x, y0, w, h = e["_box"]
        nodes.append(_node(e["id"], "card", x, y0, w, h, label=e.get("label", "")))
        pulses.append({"box": [x - 4, y0 - 4, x + w + 4, y0 + h + 4], "color": e["_accent"]})

    height = int(y) + 100 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "bpmn",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "bpmn": {"lanes": lanes, "elements": elements, "flows": flows},
        "glow_rects": glow,
        "flow_paths": flow_paths,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Org chart (top-down tree with elbow connectors; forest allowed)
# ---------------------------------------------------------------------------

ORGCHART_NODE_W = 176
ORGCHART_NODE_H = 62
ORGCHART_LEVEL_H = 108
ORGCHART_GAP = 26


def plan_orgchart(spec):
    spec = spec or {}
    nodes = [dict(n) for n in (spec.get("nodes") or []) if isinstance(n, dict)][:24]
    while len(nodes) < 2:
        nodes.append({"id": f"o{len(nodes)}", "label": ""})
    by_id, order = _unique_ids(nodes, "o")
    children = {n["id"]: [] for n in nodes}
    roots = []
    for n in nodes:
        p = str(n.get("parent") or "")
        if p and p in by_id and p != n["id"]:
            children[p].append(n["id"])
        else:
            roots.append(n["id"])
    # Cycle guard: a node whose ancestor chain loops becomes a root.
    for n in nodes:
        seen, cur = set(), n["id"]
        chain_ok = True
        while by_id[cur].get("parent") and str(by_id[cur]["parent"]) in by_id:
            cur = str(by_id[cur]["parent"])
            if cur in seen:
                chain_ok = False
                break
            seen.add(cur)
        if not chain_ok:
            n["parent"] = None
            if n["id"] not in roots:
                roots.append(n["id"])
    for i, n in enumerate(nodes):
        n["_accent"] = _box_accent(n, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        n["_role"] = str(n.get("role", ""))

    subtree_w = {}

    def measure(nid, depth=0):
        if depth > 8:
            # Depth-capped nodes still need a recorded width: parents sum
            # subtree_w over all children and place() indexes it directly.
            subtree_w[nid] = ORGCHART_NODE_W
            return ORGCHART_NODE_W
        kids = children.get(nid, [])
        if not kids:
            subtree_w[nid] = ORGCHART_NODE_W
        else:
            total = sum(measure(k, depth + 1) for k in kids) + ORGCHART_GAP * (len(kids) - 1)
            subtree_w[nid] = max(ORGCHART_NODE_W, total)
        return subtree_w[nid]

    for r in roots:
        measure(r)

    positions = {}

    def place(nid, x_center, level, depth=0):
        if depth > 8:
            return
        w = subtree_w[nid]
        positions[nid] = (round(x_center - ORGCHART_NODE_W / 2), 210 + level * ORGCHART_LEVEL_H,
                          ORGCHART_NODE_W, ORGCHART_NODE_H)
        kids = children.get(nid, [])
        if not kids:
            return
        total = sum(subtree_w[k] for k in kids) + ORGCHART_GAP * (len(kids) - 1)
        x = x_center - total / 2
        for k in kids:
            place(k, x + subtree_w[k] / 2, level + 1, depth + 1)
            x += subtree_w[k] + ORGCHART_GAP

    total_w = sum(subtree_w[r] for r in roots) + ORGCHART_GAP * (len(roots) - 1)
    x = CANVAS_W / 2 - total_w / 2
    depth_max = 0
    for r in roots:
        place(r, x + subtree_w[r] / 2, 0)
        x += subtree_w[r] + ORGCHART_GAP

    def depth_of(nid, d=0):
        if not children.get(nid) or d > 8:
            return d
        return max(depth_of(k, d + 1) for k in children[nid])

    for r in roots:
        depth_max = max(depth_max, depth_of(r))

    flow_paths, edges = [], []
    i = 0
    for n in nodes:
        for k in children.get(n["id"], []):
            if n["id"] not in positions or k not in positions:
                continue  # child sits beyond the depth cap and is not drawn
            pa, pb = positions[n["id"]], positions[k]
            p1 = (pa[0] + pa[2] / 2, pa[1] + pa[3])
            p2 = (pb[0] + pb[2] / 2, pb[1])
            mid = (p1[1] + p2[1]) / 2
            pts = [p1, (p1[0], mid), (p2[0], mid), p2]
            pts = [(round(px), round(py)) for px, py in pts]
            edges.append({"id": f"e.org.{i}", "from": n["id"], "to": k, "points": pts,
                          "color": "white", "label": "", "style": "solid", "loop": False})
            flow_paths.append({"points": [list(p) for p in pts], "color": n["_accent"],
                               "offset": round(i / 24, 4)})
            i += 1

    gnodes, pulses = [], []
    for n in nodes:
        if n["id"] not in positions:
            continue  # beyond the depth cap; not drawn
        x0, y0, w, h = positions[n["id"]]
        n["_box"] = (x0, y0, w, h)
        gnodes.append(_node(n["id"], "card", x0, y0, w, h, label=n.get("label", "")))
        pulses.append({"box": [x0, y0, x0 + w, y0 + h], "color": n["_accent"]})

    height = 210 + (depth_max + 1) * ORGCHART_LEVEL_H + 60 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "orgchart",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "orgchart": {"nodes": nodes},
        "glow_rects": glow,
        "flow_paths": flow_paths,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": gnodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Mindmap (radial tree: root in the center, first-level topics on a ring by
# leaf-share sectors, leaves one ring further out)
# ---------------------------------------------------------------------------

MINDMAP_ROOT_W = 180
MINDMAP_ROOT_H = 62
MINDMAP_TOPIC_W = 158
MINDMAP_TOPIC_H = 46
MINDMAP_LEAF_W = 140
MINDMAP_LEAF_H = 40
MINDMAP_R1 = 300.0
MINDMAP_R2 = 520.0


def plan_mindmap(spec):
    spec = spec or {}
    root = spec.get("root") if isinstance(spec.get("root"), dict) else {}
    topics = [dict(t) for t in (root.get("children") or []) if isinstance(t, dict)][:10]
    while len(topics) < 2:
        topics.append({"label": ""})
    for t in topics:
        t["_leaves"] = [dict(l) for l in (t.get("children") or []) if isinstance(l, dict)][:5]

    def leaf_count(t):
        return max(1, len(t["_leaves"]))

    total_leaves = sum(leaf_count(t) for t in topics)
    height = int(2 * MINDMAP_R2 + 250 + (30 if spec.get("footer") else 0))
    cx, cy = CANVAS_W / 2, height / 2 + 40

    nodes, edges, flow_paths, pulses = [], [], [], []
    root_box = (round(cx - MINDMAP_ROOT_W / 2), round(cy - MINDMAP_ROOT_H / 2),
                MINDMAP_ROOT_W, MINDMAP_ROOT_H)
    nodes.append(_node("root", "card", *root_box, label=str(root.get("label", ""))))
    pulses.append({"box": [root_box[0], root_box[1], root_box[0] + root_box[2], root_box[1] + root_box[3]],
                   "color": "green"})

    angle = -math.pi / 2
    ti = 0
    for t in topics:
        share = leaf_count(t) / total_leaves
        sweep = share * 2 * math.pi
        mid = angle + sweep / 2
        tx = cx + MINDMAP_R1 * math.cos(mid)
        ty = cy + MINDMAP_R1 * 0.72 * math.sin(mid)
        t_box = (round(tx - MINDMAP_TOPIC_W / 2), round(ty - MINDMAP_TOPIC_H / 2),
                 MINDMAP_TOPIC_W, MINDMAP_TOPIC_H)
        t["_box"] = t_box
        t["_accent"] = _SEQUENCE_ACCENT_CYCLE[ti % len(_SEQUENCE_ACCENT_CYCLE)]
        tid = f"t{ti}"
        pts = [(round(cx), round(cy)), (round(tx), round(ty))]
        edges.append({"id": f"e.mm.{ti}", "from": "root", "to": tid, "points": pts,
                      "color": "white", "label": "", "style": "solid", "loop": False})
        flow_paths.append({"points": [list(p) for p in pts], "color": t["_accent"],
                           "offset": round(ti / max(1, len(topics)), 4)})
        nodes.append(_node(tid, "card", *t_box, label=str(t.get("label", ""))))
        pulses.append({"box": [t_box[0], t_box[1], t_box[0] + t_box[2], t_box[1] + t_box[3]],
                       "color": t["_accent"]})
        # Leaves fan across the topic's own sector on the outer ring.
        leaves = t["_leaves"]
        for li, l in enumerate(leaves):
            frac = (li + 1) / (len(leaves) + 1)
            la = angle + sweep * frac
            lx = cx + MINDMAP_R2 * math.cos(la)
            ly = cy + MINDMAP_R2 * 0.72 * math.sin(la)
            l_box = (round(lx - MINDMAP_LEAF_W / 2), round(ly - MINDMAP_LEAF_H / 2),
                     MINDMAP_LEAF_W, MINDMAP_LEAF_H)
            lid = f"t{ti}l{li}"
            pts = [(round(tx), round(ty)), (round(lx), round(ly))]
            edges.append({"id": f"e.mm.{ti}.{li}", "from": tid, "to": lid, "points": pts,
                          "color": "muted", "label": "", "style": "solid", "loop": False})
            nodes.append(_node(lid, "terminal", *l_box, label=str(l.get("label", ""))))
        angle += sweep
        ti += 1

    frame, glow = _box_frame_glow(height)
    return {
        "layout": "mindmap",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "mindmap": {"root": {"label": str(root.get("label", "")), "_box": root_box}, "topics": topics},
        "glow_rects": glow,
        "flow_paths": flow_paths,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Timeline (horizontal axis with event cards alternating above/below)
# ---------------------------------------------------------------------------

TIMELINE_CARD_W = 190
TIMELINE_CARD_H = 64


def plan_timeline(spec):
    spec = spec or {}
    entries = [dict(e) for e in (spec.get("events") or []) if isinstance(e, dict)][:12]
    while len(entries) < 2:
        entries.append({"label": "", "time": ""})
    axis_y = 420.0
    top_y, bot_y = 240.0, 480.0
    n = len(entries)
    x_lo, x_hi = 110.0, 1100.0
    step = (x_hi - x_lo) / max(1, n - 1)

    nodes, edges, flow_paths, pulses = [], [], [], []
    for i, e in enumerate(entries):
        e["_accent"] = _box_accent(e, _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)])
        side = e.get("side")
        above = (i % 2 == 0) if side not in ("above", "below") else (side == "above")
        ex = x_lo + i * step
        ey = top_y if above else bot_y
        e["_dot"] = (round(ex), round(axis_y))
        e["_box"] = (round(ex - TIMELINE_CARD_W / 2), round(ey), TIMELINE_CARD_W, TIMELINE_CARD_H)
        e["_above"] = above
        pts = [e["_dot"], (round(ex), round(ey + (TIMELINE_CARD_H if above else 0)))]
        e["_stem"] = pts
        edges.append({"id": f"e.tl.{i}", "from": f"v{i}", "to": f"v{i}", "points": pts,
                      "color": "muted", "label": "", "style": "solid", "loop": False})
        x0, y0, w, h = e["_box"]
        nodes.append(_node(f"v{i}", "card", x0, y0, w, h, label=e.get("label", "")))
        pulses.append({"box": [x0, y0, x0 + w, y0 + h], "color": e["_accent"]})

    flow_paths.append({"points": [[x_lo, axis_y], [x_hi, axis_y]], "color": "green", "offset": 0.0})
    height = int(bot_y + TIMELINE_CARD_H) + 110 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "timeline",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "timeline": {"events": entries, "axis": {"y": round(axis_y), "x0": round(x_lo), "x1": round(x_hi)}},
        "glow_rects": glow,
        "flow_paths": flow_paths,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Fishbone / Ishikawa (horizontal spine into a problem head; category bones
# at a 55° angle alternating above/below, causes as ticks along each bone)
# ---------------------------------------------------------------------------

FISHBONE_BONE_LEN = 300.0
FISHBONE_ANGLE = math.radians(55)


def plan_fishbone(spec):
    spec = spec or {}
    problem = str(spec.get("problem", ""))
    categories = [dict(c) for c in (spec.get("categories") or []) if isinstance(c, dict)][:6]
    while len(categories) < 2:
        categories.append({"label": "", "causes": []})
    for c in categories:
        c["_causes"] = [str(x)[:28] for x in (c.get("causes") or [])[:5] if str(x).strip()]

    spine_y = 470.0
    spine_x0, spine_x1 = 130.0, 950.0
    head = {"x": round(spine_x1 + 18), "y": round(spine_y - 55), "w": 190, "h": 110}
    n = len(categories)
    dx = FISHBONE_BONE_LEN * math.cos(FISHBONE_ANGLE)
    dy = FISHBONE_BONE_LEN * math.sin(FISHBONE_ANGLE)

    nodes, edges, flow_paths, pulses = [], [], [], []
    flow_paths.append({"points": [[spine_x0, spine_y], [spine_x1, spine_y]], "color": "green", "offset": 0.0})
    for i, c in enumerate(categories):
        above = i % 2 == 0
        base_x = spine_x0 + (i + 1) / (n + 1) * (spine_x1 - spine_x0)
        tip = (base_x - dx, spine_y - dy if above else spine_y + dy)
        c["_base"] = (round(base_x), round(spine_y))
        c["_tip"] = (round(tip[0]), round(tip[1]))
        c["_above"] = above
        c["_accent"] = _SEQUENCE_ACCENT_CYCLE[i % len(_SEQUENCE_ACCENT_CYCLE)]
        edges.append({"id": f"e.fb.{i}", "from": f"c{i}", "to": "head", "points": [c["_base"], c["_tip"]],
                      "color": "white", "label": "", "style": "solid", "loop": False})
        flow_paths.append({"points": [list(c["_tip"]), list(c["_base"])], "color": c["_accent"],
                           "offset": round(i / max(1, n), 4)})
        # Category label sits beyond the bone tip.
        ly = c["_tip"][1] - 44 if above else c["_tip"][1] + 12
        c["_label_box"] = (round(c["_tip"][0] - 40), round(ly), 190, 34)
        # Causes: short horizontal ticks crossing the bone.
        ticks = []
        for k, cause in enumerate(c["_causes"]):
            t = 0.28 + 0.6 * k / max(1, len(c["_causes"]) - 1) if len(c["_causes"]) > 1 else 0.5
            bx = base_x - dx * t
            by = spine_y - dy * t if above else spine_y + dy * t
            tick = {"points": [(round(bx), round(by)), (round(bx + 96), round(by))], "text": cause}
            ticks.append(tick)
        c["_ticks"] = ticks
        lx, ly2, lw, lh = c["_label_box"]
        nodes.append(_node(f"c{i}", "card", lx, ly2, lw, lh, label=c.get("label", "")))
        pulses.append({"box": [lx, ly2, lx + lw, ly2 + lh], "color": c["_accent"]})

    nodes.append(_node("head", "card", head["x"], head["y"], head["w"], head["h"], label=problem))
    pulses.append({"box": [head["x"], head["y"], head["x"] + head["w"], head["y"] + head["h"]], "color": "pink"})

    height = int(spine_y + dy) + 120 + (30 if spec.get("footer") else 0)
    frame, glow = _box_frame_glow(height)
    return {
        "layout": "fishbone",
        "canvas": {"width": CANVAS_W, "height": height},
        "frame": frame,
        "fishbone": {"problem": problem, "categories": categories, "head": head,
                     "spine": {"y": round(spine_y), "x0": round(spine_x0), "x1": round(spine_x1)}},
        "glow_rects": glow,
        "flow_paths": flow_paths,
        "pulse_targets": pulses,
        "icons": [],
        "nodes": nodes,
        "edges": edges,
    }
