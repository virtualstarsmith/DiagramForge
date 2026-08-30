#!/usr/bin/env python3
"""Export a DiagramForge ops document as an editable draw.io (mxfile) diagram.

Closes the loop opened by scripts/drawio_import.py: a diagram that came in
from draw.io — or was authored from scratch — can now be handed back as a
draw.io file users keep editing in diagrams.net.

Mirrors the import philosophy ("redraws, never converts"): the export is a
faithful picture of what DiagramForge rendered, rebuilt from the primitive-op
stream that is the single source of layout truth:

- rect / ellipse / diamond ops -> vertices (rounded corners, dashes, fills)
- line ops                     -> edges, bound to the shapes their endpoints
                                  touch so dragging a node keeps its connectors
- text ops                     -> the value of the shape they sit inside, the
                                  label of the nearest edge (role=edge-label),
                                  or a standalone text vertex
- icon / image / signature ops -> skipped (icons are not portable vector
                                  assets); counted in the export report
- edge-label masks             -> skipped (draw.io knocks labels out of lines
                                  itself, no mask chip needed)

Edges may be painted before the nodes they attach to (the two-pass z-order),
so shape ids are assigned before any edge cell is serialized.

The output is plain uncompressed mxfile XML on a 4px grid — the same grid
DiagramForge snaps every op to.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

NODE_MIN_SIDE = 12
BORDER_TOL = 6          # endpoints sit on the shape border; snap within this
LABEL_CAPTURE = 60      # max distance from an edge polyline to claim a label


# ---------------------------------------------------------------------------
# op classification
# ---------------------------------------------------------------------------

def _is_node(op, bg):
    """Filled solid shapes count as bindable nodes (lint_geometry's rule,
    extended with ellipse so terminal ovals and pill shapes bind too)."""
    if op.get("op") not in ("rect", "diamond", "ellipse"):
        return False
    if op.get("role") == "edge-label-mask":
        return False
    if op.get("fill") is None or op.get("fill") == bg:
        return False
    if op.get("style", "solid") != "solid":
        return False
    return op.get("w", 0) >= NODE_MIN_SIDE and op.get("h", 0) >= NODE_MIN_SIDE


def _contains(box, px, py, tol=0.0):
    x, y, w, h = box
    return (x - tol) <= px <= (x + w + tol) and (y - tol) <= py <= (y + h + tol)


def _box_area(box):
    return box[2] * box[3]


def _box(op):
    return (op["x"], op["y"], op["w"], op["h"])


def _pt_poly_dist(px, py, points):
    best = float("inf")
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        vx, vy = bx - ax, by - ay
        seg = vx * vx + vy * vy
        if seg == 0:
            best = min(best, ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5)
            continue
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / seg))
        best = min(best, ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5)
    return best


def _edge_style(op):
    parts = ["rounded=1", "html=1"]
    parts.append(f"strokeColor={op.get('stroke', '#000000')}")
    parts.append(f"strokeWidth={max(1, int(op.get('width', 2)))}")
    if op.get("style", "solid") != "solid":
        parts.append("dashed=1")
    arrow = op.get("arrow")
    parts.append(f"endArrow={'block' if arrow == 'filled' else 'open' if arrow else 'none'}")
    parts.append("startArrow=none")
    return ";".join(parts) + ";"


def _shape_style(op):
    kind = op["op"]
    if kind == "ellipse":
        base = "ellipse"
    elif kind == "diamond":
        base = "rhombus"
    elif op.get("radius"):
        base = f"rounded=1;absoluteArcSize=1;arcSize={int(round(op['radius']))}"
    else:
        base = "rounded=0"
    parts = [base, "whiteSpace=wrap", "html=1"]
    fill = op.get("fill")
    parts.append(f"fillColor={fill}" if fill else "fillColor=none")
    parts.append(f"strokeColor={op.get('stroke', '#000000')}")
    parts.append(f"strokeWidth={max(1, int(op.get('width', 2)))}")
    if op.get("style", "solid") != "solid":
        parts.append("dashed=1")
    return ";".join(parts) + ";"


def _text_style(op):
    parts = ["text", "html=1"]
    parts.append(f"fontSize={int(round(op.get('size', 12)))}")
    parts.append(f"fontColor={op.get('color', '#000000')}")
    if op.get("bold"):
        parts.append("fontStyle=1")
    align = op.get("align", "center")
    if align in ("left", "right", "center"):
        parts.append(f"align={align}")
    return ";".join(parts) + ";"


# ---------------------------------------------------------------------------
# ops -> mxfile XML
# ---------------------------------------------------------------------------

def build_drawio(doc):
    """ops document -> (mxfile XML string, report dict)."""
    bg = doc.get("bg", "#ffffff")
    canvas = doc.get("canvas", {})
    ops = doc.get("ops", [])

    node_indexes = [i for i, op in enumerate(ops) if _is_node(op, bg)]
    line_indexes = [i for i, op in enumerate(ops)
                    if op.get("op") == "line" and len(op.get("points", [])) >= 2]
    text_indexes = [i for i, op in enumerate(ops) if op.get("op") == "text"]

    def bind(point):
        """Smallest filled shape whose box (inflated by BORDER_TOL) holds the
        endpoint — the node that endpoint visually attaches to."""
        px, py = point
        best = None
        for i in node_indexes:
            op = ops[i]
            box = _box(op)
            if _contains(box, px, py, tol=BORDER_TOL):
                if best is None or _box_area(box) < _box_area(_box(ops[best])):
                    best = i
        return best

    # Claim texts: inside a node -> node value; near an edge -> edge label;
    # otherwise standalone.
    values = {i: [] for i in node_indexes}
    edge_labels = {i: [] for i in line_indexes}
    claimed = set()
    for i in text_indexes:
        op = ops[i]
        cx, cy = op["x"] + op["w"] / 2, op["y"] + op["h"] / 2
        holder = None
        for j in node_indexes:
            if _contains(_box(ops[j]), cx, cy):
                if holder is None or _box_area(_box(ops[j])) < _box_area(_box(ops[holder])):
                    holder = j
        if holder is not None:
            values[holder].append(str(op.get("text", "")))
            claimed.add(i)
            continue
        if op.get("role") == "edge-label":
            best, best_d = None, LABEL_CAPTURE
            for j in line_indexes:
                d = _pt_poly_dist(cx, cy, ops[j]["points"])
                if d < best_d:
                    best, best_d = j, d
            if best is not None:
                edge_labels[best].append(str(op.get("text", "")))
                claimed.add(i)

    # Ids first: edges can appear before the nodes they attach to.
    id_by_op = {}
    seq = 0
    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind in ("rect", "ellipse", "diamond") and op.get("role") != "edge-label-mask" \
                and not (op.get("fill") == bg and op.get("stroke") == bg):
            seq += 1
            id_by_op[i] = f"df{seq}"
        elif kind == "line":
            seq += 1
            id_by_op[i] = f"df{seq}"
        elif kind == "text" and i not in claimed:
            seq += 1
            id_by_op[i] = f"df{seq}"

    root = ET.Element("mxfile", {"host": "diagramforge", "agent": "DiagramForge", "type": "device"})
    diagram = ET.SubElement(root, "diagram", {"id": "diagramforge-1", "name": str(doc.get("layout", "diagram"))})
    model = ET.SubElement(diagram, "mxGraphModel", {
        "dx": "0", "dy": "0", "grid": "1", "gridSize": "4", "guides": "1",
        "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1",
        "page": "1", "pageScale": "1",
        "pageWidth": str(int(canvas.get("width", 1600))),
        "pageHeight": str(int(canvas.get("height", 900))),
    })
    cell_root = ET.SubElement(model, "root")
    ET.SubElement(cell_root, "mxCell", {"id": "0"})
    ET.SubElement(cell_root, "mxCell", {"id": "1", "parent": "0"})

    for i, op in enumerate(ops):
        kind = op.get("op")
        cid = id_by_op.get(i)
        if cid is None:
            continue  # masks, invisible paper patches, claimed texts, icon/image/signature
        if kind in ("rect", "ellipse", "diamond"):
            # ET escapes attribute values itself; labels may carry live <br>
            # markup (html=1 styles), which draw.io unescapes on load.
            label = "\n".join(values.get(i, [])).replace("\n", "<br>")
            cell = ET.SubElement(cell_root, "mxCell", {
                "id": cid, "value": label, "style": _shape_style(op), "vertex": "1", "parent": "1",
            })
            ET.SubElement(cell, "mxGeometry", {
                "x": str(op["x"]), "y": str(op["y"]),
                "width": str(op["w"]), "height": str(op["h"]), "as": "geometry",
            })
        elif kind == "line":
            pts = op["points"]
            src, dst = bind(pts[0]), bind(pts[-1])
            attrs = {"id": cid, "edge": "1", "parent": "1", "style": _edge_style(op),
                     "value": "\n".join(edge_labels.get(i, [])).replace("\n", "<br>")}
            if src is not None:
                attrs["source"] = id_by_op[src]
            if dst is not None:
                attrs["target"] = id_by_op[dst]
            cell = ET.SubElement(cell_root, "mxCell", attrs)
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
            if src is None:
                ET.SubElement(geo, "mxPoint", {"x": str(pts[0][0]), "y": str(pts[0][1]), "as": "sourcePoint"})
            if dst is None:
                ET.SubElement(geo, "mxPoint", {"x": str(pts[-1][0]), "y": str(pts[-1][1]), "as": "targetPoint"})
            waypoints = pts[1:-1]
            if waypoints:
                arr = ET.SubElement(geo, "Array", {"as": "points"})
                for wp in waypoints:
                    ET.SubElement(arr, "mxPoint", {"x": str(wp[0]), "y": str(wp[1])})
        elif kind == "text":
            cell = ET.SubElement(cell_root, "mxCell", {
                "id": cid, "value": str(op.get("text", "")), "style": _text_style(op),
                "vertex": "1", "parent": "1",
            })
            ET.SubElement(cell, "mxGeometry", {
                "x": str(op["x"]), "y": str(op["y"]),
                "width": str(max(4, op.get("w", 40))), "height": str(max(4, op.get("h", 20))),
                "as": "geometry",
            })

    skipped = sum(1 for op in ops if op.get("op") in ("icon", "image", "signature"))
    bound = sum(1 for i in line_indexes
                if bind(ops[i]["points"][0]) is not None and bind(ops[i]["points"][-1]) is not None)
    report = {
        "vertices": sum(1 for c in cell_root if c.get("vertex") == "1"),
        "edges": sum(1 for c in cell_root if c.get("edge") == "1"),
        "edges_bound": bound,
        "skipped_ops": skipped,
    }
    xml_text = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_text, report


def export_drawio(doc, path):
    """Write the ops document as a .drawio file; returns the report dict."""
    xml_text, report = build_drawio(doc)
    Path(path).write_text(xml_text, encoding="utf-8")
    return report
