#!/usr/bin/env python3
"""Lint a DiagramForge op stream against the connector-geometry contract.

The op stream (``scripts/render_animated_diagram.py: render_static_with_ops``)
is the single source of layout truth for both renderers (Pillow raster and
rough.js SVG), so checking it once covers every output format. Categories:

- ``diagonal-connector``  a connector segment that is neither horizontal nor
                          vertical (rounded right-angle elbows are mandatory).
                          Segments shorter than ``GLYPH_SEG_MAX`` are glyphs
                          and ticks (actor limbs, direction ticks), exempt.
                          Radial/diagonal-by-design layouts (fishbone,
                          mindmap, timeline, panorama) are exempt.
- ``label-mask-covered``  an edge-label mask chip that a node shape painted
                          AFTER it overlaps — the node fill clips the label
                          text into a fragment on the border
- ``attach-point-fan``    two connectors attach the same edge of the same
                          node closer than ``ATTACH_MIN_GAP`` px — each
                          connector must have its own distinct attach point
- ``connector-through-node``  a connector passes through the interior of a
                          node that is neither its source nor its destination
                          (dashed strokes are exempt: they signal transit)
- ``label-line-gap``      an edge-label mask closer than ``LABEL_LINE_GAP``
                          px to any connector segment — the line must stay
                          visible right up to the label
- ``off-grid``            a structural coordinate or size that is not a
                          multiple of 4 (the 4px grid is a hard rule).
                          Label-mask chips hug measured glyphs and icon/image
                          internals are exempt.

CLI: ``python -X utf8 scripts/lint_geometry.py <ops.json...>`` prints a JSON
report; exit 0 when clean, 1 on violations, 2 on usage errors. ``--spec``
renders the op stream from a spec file in-process instead.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

GLYPH_SEG_MAX = 40          # shorter diagonal segments are glyphs/ticks, not connectors
ATTACH_MIN_GAP = 12         # min px between attach points on the same node edge
ATTACH_BORDER_TOL = 4       # endpoint this close to a node border counts as attached
LABEL_LINE_GAP = 5.5        # 6px contract, 0.5 float slack
NODE_MIN_SIDE = 12          # smaller filled shapes are glyph chips, not nodes

DIAGONAL_EXEMPT_LAYOUTS = {"fishbone", "mindmap", "timeline", "panorama", "usecase"}
# ^ usecase: UML actor→ellipse associations are canonically straight solid
#   lines (PlantUML/UML-spec notation), not elbows.


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _seg_len(a, b):
    return math.dist(a, b)


def _pt_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _rect(r):
    x, y, w, h = r
    return x, y, x + w, y + h


def _rects_intersect(a, b):
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def _pt_in_rect(p, r, margin=0.0):
    x0, y0, x1, y1 = _rect(r)
    return x0 + margin < p[0] < x1 - margin and y0 + margin < p[1] < y1 - margin


def _pt_on_border(p, r, tol):
    """Which rect edge the point sits on (within tol), else None."""
    x, y, w, h = r
    x0, y0, x1, y1 = x, y, x + w, y + h
    if not (x0 - tol <= p[0] <= x1 + tol and y0 - tol <= p[1] <= y1 + tol):
        return None
    if abs(p[1] - y0) <= tol:
        return ("top", p[0])
    if abs(p[1] - y1) <= tol:
        return ("bottom", p[0])
    if abs(p[0] - x0) <= tol:
        return ("left", p[1])
    if abs(p[0] - x1) <= tol:
        return ("right", p[1])
    return None


def _segs_intersect(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 != o2 and o3 != o4


def _seg_crosses_rect(a, b, r, margin=2.0):
    """True when segment ab passes through the (shrunk) rect interior."""
    if _pt_in_rect(a, r, margin) or _pt_in_rect(b, r, margin):
        return True
    x0, y0, x1, y1 = _rect(r)
    x0 += margin
    y0 += margin
    x1 -= margin
    y1 -= margin
    if x0 >= x1 or y0 >= y1:
        return False
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for c1, c2 in zip(corners, corners[1:] + corners[:1]):
        if _segs_intersect(a, b, c1, c2):
            return True
    return False


def _seg_rect_dist(a, b, r):
    if _seg_crosses_rect(a, b, r, margin=0.0):
        return 0.0
    x0, y0, x1, y1 = _rect(r)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    dists = [_pt_seg_dist(c, a, b) for c in corners]
    dists += [_pt_seg_dist(a, c1, c2) for c1, c2 in edges]
    dists += [_pt_seg_dist(b, c1, c2) for c1, c2 in edges]
    return min(dists)


# ---------------------------------------------------------------------------
# Op-stream model
# ---------------------------------------------------------------------------

def _is_node(op, bg):
    """Filled shape ops count as nodes; masks, hollow containers, dashed
    zone frames, glyph chips, and paper-filled patches (socket covers,
    hollow aggregation diamonds, ports) do not."""
    if op.get("op") not in ("rect", "diamond"):
        return False
    if op.get("role") == "edge-label-mask":
        return False
    if op.get("fill") is None or op.get("fill") == bg:
        return False
    if op.get("style", "solid") != "solid":
        return False
    if op.get("w", 0) < NODE_MIN_SIDE or op.get("h", 0) < NODE_MIN_SIDE:
        return False
    return True


def _node_box(op):
    return (op["x"], op["y"], op["w"], op["h"])


def _is_container(op, nodes):
    """A node rect that fully contains another node is a zone container
    (swimlane band, layer panel) — connectors may cross it freely."""
    box = _node_box(op)
    for _idx, other in nodes:
        if other is op:
            continue
        o = _node_box(other)
        if (box[0] <= o[0] and box[1] <= o[1]
                and box[0] + box[2] >= o[0] + o[2] and box[1] + box[3] >= o[1] + o[3]):
            return True
    return False


def _fmt_pt(p):
    return f"({round(p[0])},{round(p[1])})"


def _fmt_box(b):
    return f"[{round(b[0])},{round(b[1])} {round(b[2])}x{round(b[3])}]"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_diagonal(ops, layout):
    if layout in DIAGONAL_EXEMPT_LAYOUTS:
        return []
    violations = []
    for i, op in enumerate(ops):
        if op.get("op") != "line":
            continue
        pts = op.get("points", [])
        for a, b in zip(pts, pts[1:]):
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if dx > 1 and dy > 1 and _seg_len(a, b) >= GLYPH_SEG_MAX:
                violations.append({
                    "category": "diagonal-connector",
                    "message": f"op#{i} line has a diagonal segment {_fmt_pt(a)} -> {_fmt_pt(b)} "
                               f"({round(_seg_len(a, b))}px); route it as a rounded right-angle elbow",
                    "op": i,
                })
    return violations


def _check_mask_covered(ops, nodes):
    violations = []
    for i, op in enumerate(ops):
        if op.get("op") != "rect" or op.get("role") != "edge-label-mask":
            continue
        mask = _node_box(op)
        for j, n in nodes:
            if j > i and _rects_intersect(mask, _node_box(n)):
                violations.append({
                    "category": "label-mask-covered",
                    "message": f"op#{i} edge-label mask at {_fmt_box(mask)} is overlapped by node op#{j} "
                               f"painted after it; draw edge labels after nodes",
                    "op": i,
                })
                break
    return violations


def _check_attach_fan(ops, nodes):
    violations = []
    attaches = {}  # (node_ops_index, side) -> [(along, line_op_idx)]
    for i, op in enumerate(ops):
        if op.get("op") != "line":
            continue
        pts = op.get("points", [])
        if len(pts) < 2:
            continue
        for endpoint in (pts[0], pts[-1]):
            for j, n in nodes:
                hit = _pt_on_border(endpoint, _node_box(n), ATTACH_BORDER_TOL)
                if hit:
                    side, along = hit
                    attaches.setdefault((j, side), []).append((along, i, n))
                    break
    for (j, side), points in attaches.items():
        if len(points) < 2:
            continue
        points.sort()
        for (a1, i1, n), (a2, i2, _n2) in zip(points, points[1:]):
            if a2 - a1 < 2:
                continue  # shared bus origin (orgchart/tree routing), one fan by design
            if a2 - a1 < ATTACH_MIN_GAP:
                violations.append({
                    "category": "attach-point-fan",
                    "message": f"line ops #{i1} and #{i2} attach the {side} edge of node "
                               f"{_fmt_box(_node_box(n))} only {round(a2 - a1, 1)}px apart "
                               f"(min {ATTACH_MIN_GAP}px); fan the attach points",
                    "op": i2,
                })
    return violations


def _check_through_node(ops, nodes):
    violations = []
    containers = {j for j, n in nodes if _is_container(n, nodes)}
    for i, op in enumerate(ops):
        if op.get("op") != "line" or op.get("style", "solid") != "solid":
            continue  # dashed strokes signal transit, not interaction
        pts = op.get("points", [])
        if len(pts) < 2:
            continue
        for j, n in nodes:
            if j in containers:
                continue
            box = _node_box(n)
            if (_pt_in_rect(pts[0], box, margin=-ATTACH_BORDER_TOL)
                    or _pt_in_rect(pts[-1], box, margin=-ATTACH_BORDER_TOL)):
                continue  # source or destination node
            for a, b in zip(pts, pts[1:]):
                if _seg_crosses_rect(a, b, box):
                    violations.append({
                        "category": "connector-through-node",
                        "message": f"op#{i} connector passes through node {_fmt_box(box)} that is not an "
                                   f"endpoint; reroute around it (or dash the stroke if transit is unavoidable)",
                        "op": i,
                    })
                    break
            else:
                continue
            break
    return violations


def _check_label_line_gap(ops):
    violations = []
    # Only solid lines count: dashed lines are background by design (sequence
    # lifelines, return channels, fragment dividers, transit strokes) and are
    # meant to run behind content — a mask crossing one hides nothing.
    lines = [(i, op) for i, op in enumerate(ops)
             if op.get("op") == "line" and op.get("style", "solid") == "solid"]
    for i, op in enumerate(ops):
        if op.get("op") != "rect" or op.get("role") != "edge-label-mask":
            continue
        mask = _node_box(op)
        best = None
        for j, line in lines:
            pts = line.get("points", [])
            for a, b in zip(pts, pts[1:]):
                d = _seg_rect_dist(a, b, mask)
                if best is None or d < best[0]:
                    best = (d, j)
        if best and best[0] < LABEL_LINE_GAP:
            violations.append({
                "category": "label-line-gap",
                "message": f"op#{i} edge-label mask sits {round(best[0], 1)}px from line op#{best[1]} "
                           f"(min 6px); keep the connector visible up to the label",
                "op": i,
            })
    return violations


def _check_off_grid(ops):
    violations = []
    exempt_ops = {"icon", "image", "signature"}

    def bad(v):
        return abs(v % 4) > 1e-6

    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind in exempt_ops or op.get("role") == "edge-label-mask":
            continue
        if kind in ("rect", "ellipse", "diamond", "text"):
            fields = [k for k in ("x", "y", "w", "h") if bad(op.get(k, 0))]
            if fields:
                violations.append({
                    "category": "off-grid",
                    "message": f"op#{i} {kind} has non-multiple-of-4 {','.join(fields)} "
                               f"in {_fmt_box((op.get('x', 0), op.get('y', 0), op.get('w', 0), op.get('h', 0)))}; "
                               f"snap to the 4px grid",
                    "op": i,
                })
        elif kind == "line":
            bad_pts = [p for p in op.get("points", []) if bad(p[0]) or bad(p[1])]
            if bad_pts:
                violations.append({
                    "category": "off-grid",
                    "message": f"op#{i} line has {len(bad_pts)} point(s) off the 4px grid "
                               f"(first at {_fmt_pt(bad_pts[0])}); snap to the 4px grid",
                    "op": i,
                })
    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint_ops(ops, layout=None, bg=None):
    """Run every geometry check over one op stream. Returns violation dicts."""
    bg = bg or ""
    nodes = [(i, op) for i, op in enumerate(ops) if _is_node(op, bg)]
    violations = []
    violations += _check_diagonal(ops, layout)
    violations += _check_mask_covered(ops, nodes)
    violations += _check_attach_fan(ops, nodes)
    violations += _check_through_node(ops, nodes)
    violations += _check_label_line_gap(ops)
    violations += _check_off_grid(ops)
    return violations


def lint_doc(doc):
    """Lint a full ops document (dict with ``ops``, ``layout``, ``bg``)."""
    return lint_ops(doc.get("ops", []), layout=doc.get("layout"), bg=doc.get("bg"))


def lint_file(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if isinstance(doc, list):
        doc = {"ops": doc}
    return lint_doc(doc), None


def _doc_from_spec(spec_path):
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import render_animated_diagram as rad  # noqa: PLC0415 - deferred: heavy module

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    _ex, _img, doc = rad.render_static_with_ops(spec)
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lint DiagramForge op streams against the connector-geometry contract.")
    parser.add_argument("files", nargs="*", help="ops document JSON files (as produced by render_static_with_ops)")
    parser.add_argument("--spec", action="append", default=[], help="render the op stream from a spec JSON and lint it")
    args = parser.parse_args(argv)

    if not args.files and not args.spec:
        parser.print_help()
        return 2

    report = {"ok": True, "files": []}
    had_error = False
    inputs = [(f, "ops") for f in args.files] + [(s, "spec") for s in args.spec]
    for name, kind in inputs:
        if kind == "spec":
            try:
                violations = lint_doc(_doc_from_spec(name))
                error = None
            except Exception as exc:  # spec render failures are usage errors here
                violations, error = None, str(exc)
        else:
            violations, error = lint_file(name)
        if error is not None:
            had_error = True
            report["files"].append({"file": name, "error": error})
            continue
        report["files"].append({"file": name, "violations": violations, "ok": not violations})
        if violations:
            report["ok"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if had_error:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
