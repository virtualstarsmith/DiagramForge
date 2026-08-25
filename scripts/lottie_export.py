#!/usr/bin/env python3
"""Export a DiagramForge ops document as a Lottie (Bodymovin) animation.

Lottie is the JSON vector-animation format consumed by lottie-web, the
lottiefiles player, After Effects (via Bodymovin), and native iOS/Android
renderers. This gives DiagramForge a resolution-independent animation
output alongside the raster GIF/MP4 — useful for embedding crisp looping
motion in web pages, apps, and design tools.

The export reconstructs the diagram from the primitive-op stream that is
the single source of layout truth:

- rect / ellipse ops  -> shape layers (rectangle / ellipse path + stroke + fill)
- line ops            -> shape layers (polyline path + stroke, arrowheads)
- text ops            -> text layers (font, size, alignment)
- icon ops            -> accent-colored disc placeholder with a gentle breathe
- flow_paths          -> glowing dots travelling each edge polyline, looped
- pulse_targets       -> soft breathing halos behind nodes

Everything stays in DiagramForge's canvas coordinate system (origin
top-left, y down) which matches Lottie's pre-comp space.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

LOTTIE_VERSION = "5.7.6"


# ---------------------------------------------------------------------------
# color + transform helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(value):
    """Convert a #rrggbb / #rgb CSS hex string (or rgba(...) fallback) into the
    [r, g, b] 0-1 list Lottie expects. Unknown values fall back to white."""
    if not value or value in ("none", "transparent"):
        return None
    v = value.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            n = int(h, 16)
        except ValueError:
            return [1.0, 1.0, 1.0]
        return [(n >> 16 & 255) / 255.0, (n >> 8 & 255) / 255.0, (n & 255) / 255.0]
    if v.startswith("rgba") or v.startswith("rgb"):
        inner = v[v.index("(") + 1:v.rindex(")")]
        parts = [float(p) for p in inner.split(",")]
        return [parts[i] / 255.0 for i in range(3)]
    return [1.0, 1.0, 1.0]


def _color_kv(value):
    """Lottie animated-color value holder. Color channels are always animated
    containers in Bodymovin, even when static."""
    rgb = _hex_to_rgb(value)
    if rgb is None:
        rgb = [1.0, 1.0, 1.0]
    return {"a": 0, "k": [rgb[0], rgb[1], rgb[2], 1.0]}


def _val(v):
    """Static (non-animated) value holder."""
    return {"a": 0, "k": v}


def _group_transform():
    """The trailing 'tr' item every shape group requires."""
    return {
        "ty": "tr",
        "p": _val([0, 0]), "a": _val([0, 0]),
        "s": _val([100, 100]), "r": _val(0), "o": _val(100),
    }


def _layer_transform(position=(0, 0), opacity=100, scale=(100, 100), rotation=0):
    return {
        "o": _val(opacity), "r": _val(rotation),
        "p": _val([position[0], position[1]]),
        "a": _val([0, 0]), "s": _val([scale[0], scale[1]]),
    }


def _new_layer(ind, ty, nm, frames):
    return {
        "ddd": 0, "ind": ind, "ty": ty, "nm": nm,
        "ks": {}, "ip": 0, "op": frames, "st": 0, "sr": 1,
    }


# ---------------------------------------------------------------------------
# op -> layer converters
# ---------------------------------------------------------------------------

def _stroke_item(color_hex, width):
    return {
        "ty": "st", "c": _color_kv(color_hex), "o": _val(100),
        "w": _val(max(1.0, width)), "lc": 2, "lj": 2,
        "ml": 1, "nm": "Stroke",
    }


def _fill_item(color_hex, opacity=100):
    return {"ty": "fl", "c": _color_kv(color_hex), "o": _val(opacity), "nm": "Fill"}


def _rect_layer(ind, op, frames):
    cx, cy = op["x"] + op["w"] / 2, op["y"] + op["h"] / 2
    radius = op.get("radius", 0) if op.get("style") != "solid" or op.get("radius") else 0
    items = [{
        "ty": "rc", "p": _val([cx, cy]), "s": _val([op["w"], op["h"]]),
        "r": _val(min(radius or 0, min(op["w"], op["h"]) / 2)), "nm": "Rect",
    }]
    if op.get("stroke"):
        items.append(_stroke_item(op["stroke"], op.get("width", 2)))
    if op.get("fill"):
        items.append(_fill_item(op["fill"]))
    items.append(_group_transform())
    layer = _new_layer(ind, 4, "rect", frames)
    layer["ks"] = _layer_transform()
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "RectGroup"}]
    return layer


def _ellipse_layer(ind, op, frames):
    cx, cy = op["x"] + op["w"] / 2, op["y"] + op["h"] / 2
    items = [{
        "ty": "el", "p": _val([cx, cy]),
        "s": _val([op["w"], op["h"]]), "d": 1, "nm": "Ellipse",
    }]
    if op.get("stroke"):
        items.append(_stroke_item(op["stroke"], op.get("width", 2)))
    if op.get("fill"):
        items.append(_fill_item(op["fill"]))
    items.append(_group_transform())
    layer = _new_layer(ind, 4, "ellipse", frames)
    layer["ks"] = _layer_transform()
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "EllipseGroup"}]
    return layer


def _line_layer(ind, op, frames):
    pts = op.get("points", [])
    if len(pts) < 2:
        return None
    verts = [[p[0], p[1]] for p in pts]
    n = len(verts)
    shape = {
        "ty": "sh", "nm": "Path",
        "ks": _val({
            "i": [[0, 0]] * n, "o": [[0, 0]] * n,
            "v": verts, "c": False,
        }),
    }
    items = [shape, _stroke_item(op.get("stroke", "#ffffff"), op.get("width", 2))]
    # arrowhead as a small filled triangle at the last segment
    arrow = op.get("arrow")
    if arrow and len(verts) >= 2:
        items.append(_arrowhead_item(verts))
    items.append(_group_transform())
    layer = _new_layer(ind, 4, "line", frames)
    layer["ks"] = _layer_transform()
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "LineGroup"}]
    return layer


def _arrowhead_item(verts):
    """A filled triangle path anchored at the line's last vertex."""
    (ax, ay), (bx, by) = verts[-2], verts[-1]
    angle = math.atan2(by - ay, bx - ax)
    length = 12
    spread = 0.5
    p1 = [bx - length * math.cos(angle - spread), by - length * math.sin(angle - spread)]
    p2 = [bx - length * math.cos(angle + spread), by - length * math.sin(angle + spread)]
    v = [[bx, by], p1, p2]
    shape = {
        "ty": "sh", "nm": "Arrow",
        "ks": _val({"i": [[0, 0]] * 3, "o": [[0, 0]] * 3, "v": v, "c": True}),
    }
    return {"ty": "gr", "it": [shape, _fill_item("#ffffff"), _group_transform()], "nm": "ArrowGroup"}


def _text_layer(ind, op, frames):
    layer = _new_layer(ind, 5, "text", frames)
    layer["ks"] = _layer_transform(position=(op["x"], op["y"] + op.get("size", 14)))
    justify = {"left": 0, "center": 1, "right": 2}.get(op.get("align", "center"), 1)
    size = op.get("size", 14)
    layer["t"] = {
        "d": {
            "k": [{
                "s": {
                    "s": size, "f": "Excalifont", "t": op.get("text", ""),
                    "j": justify, "tr": 0, "lh": size * 1.25, "ls": 0,
                    "fc": _hex_to_rgb(op.get("color", "#ffffff")) or [1, 1, 1],
                },
                "t": 0,
            }],
        },
        "p": {}, "m": {"g": 1, "a": {"a": 0, "k": [0, 0]}},
        "a": [],
    }
    return layer


def _icon_layer(ind, op, frames):
    """Accent-colored disc placeholder with a soft breathing scale loop."""
    tile = op.get("tile") or op.get("w") or op.get("h") or 50
    x = op.get("x", 0)
    y = op.get("y", 0)
    cx = x + tile / 2
    cy = y + tile / 2
    r = tile / 4
    accent = op.get("accent") or op.get("color") or "#86b300"
    items = [
        {"ty": "el", "p": _val([cx, cy]), "s": _val([r * 2, r * 2]), "d": 1, "nm": "IconDot"},
        _fill_item(accent, opacity=70),
        _stroke_item(accent, 2),
        _group_transform(),
    ]
    layer = _new_layer(ind, 4, "icon", frames)
    # breathing scale loop: 92% -> 108% -> 92% over the timeline
    kf = [
        {"t": 0, "s": [92, 92], "i": {"x": [0.5], "y": [1]}, "o": {"x": [0.5], "y": [0]}},
        {"t": frames // 2, "s": [108, 108], "i": {"x": [0.5], "y": [1]}, "o": {"x": [0.5], "y": [0]}},
        {"t": frames, "s": [92, 92]},
    ]
    layer["ks"] = _layer_transform()
    layer["ks"]["s"] = {"a": 1, "k": kf}
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "IconGroup"}]
    return layer


def _diamond_layer(ind, op, frames):
    """A four-point diamond path (decision node)."""
    x, y, w, h = op["x"], op["y"], op["w"], op["h"]
    cx, cy = x + w / 2, y + h / 2
    verts = [[cx, y], [x + w, cy], [cx, y + h], [x, cy]]
    shape = {
        "ty": "sh", "nm": "Diamond",
        "ks": _val({"i": [[0, 0]] * 4, "o": [[0, 0]] * 4, "v": verts, "c": True}),
    }
    items = [shape]
    if op.get("stroke"):
        items.append(_stroke_item(op["stroke"], op.get("width", 2)))
    if op.get("fill"):
        items.append(_fill_item(op["fill"]))
    items.append(_group_transform())
    layer = _new_layer(ind, 4, "diamond", frames)
    layer["ks"] = _layer_transform()
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "DiamondGroup"}]
    return layer


# ---------------------------------------------------------------------------
# flow animation: a glowing dot travels each edge polyline, looping
# ---------------------------------------------------------------------------

def _polyline_length(points):
    total = 0.0
    for i in range(len(points) - 1):
        total += math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
    return total


def _sample_polyline(points, n):
    """Sample n evenly-spaced points along a polyline (closed loop)."""
    if len(points) < 2:
        return [list(points[0])] * max(n, 1)
    total = _polyline_length(points) or 1.0
    out = []
    for i in range(n):
        target = (i / n) * total
        dist = 0.0
        for j in range(len(points) - 1):
            seg = math.hypot(points[j + 1][0] - points[j][0], points[j + 1][1] - points[j][1])
            if dist + seg >= target:
                frac = (target - dist) / seg if seg else 0
                out.append([
                    points[j][0] + (points[j + 1][0] - points[j][0]) * frac,
                    points[j][1] + (points[j + 1][1] - points[j][1]) * frac,
                ])
                break
            dist += seg
        else:
            out.append([points[-1][0], points[-1][1]])
    return out


def _flow_dot_layer(ind, path, theme, frames):
    """A small accent disc travelling the flow path's polyline, looping
    seamlessly (last keyframe position == first)."""
    pts = path.get("points", [])
    if len(pts) < 2:
        return None
    color_key = path.get("color", "core_stroke")
    color_hex = theme.get(color_key, "#86b300")
    offset = path.get("offset", 0.0)
    samples = max(16, frames)
    sampled = _sample_polyline(pts, samples)
    n = len(sampled)
    # phase-shift the start so parallel edges are not in lockstep
    shift = int((offset % 1.0) * n)
    sampled = sampled[shift:] + sampled[:shift]
    # ease each segment a touch so the dot reads as organic, not mechanical
    pos_kf = []
    for i, pt in enumerate(sampled):
        pos_kf.append({
            "t": int(i * frames / n),
            "s": [pt[0], pt[1]],
            "i": {"x": 0.42, "y": 1}, "o": {"x": 0.58, "y": 0},
        })
    pos_kf.append({"t": frames, "s": [sampled[0][0], sampled[0][1]]})
    r = 6.0
    items = [
        {"ty": "el", "p": _val([0, 0]), "s": _val([r * 2, r * 2]), "d": 1, "nm": "Dot"},
        _fill_item(color_hex, opacity=95),
        _group_transform(),
    ]
    layer = _new_layer(ind, 4, "flow", frames)
    layer["ks"] = _layer_transform()
    layer["ks"]["p"] = {"a": 1, "k": pos_kf}
    layer["ks"]["o"] = {"a": 1, "k": [  # fade in/out at loop seam
        {"t": 0, "s": [0], "i": {"x": [1], "y": [1]}, "o": {"x": [0], "y": [0]}},
        {"t": max(1, frames // 8), "s": [100]},
        {"t": frames - max(1, frames // 8), "s": [100]},
        {"t": frames, "s": [0]},
    ]}
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "FlowGroup"}]
    return layer


def _pulse_layer(ind, pulse, theme, frames):
    """A soft breathing halo behind a node box."""
    box = pulse.get("box") or pulse.get("rect")
    if not box or len(box) < 4:
        return None
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    color_hex = theme.get(pulse.get("color", "core_stroke"), "#3b82f6")
    items = [
        {"ty": "el", "p": _val([cx, cy]), "s": _val([rx * 2, ry * 2]), "d": 1, "nm": "Halo"},
        _fill_item(color_hex, opacity=25),
        _group_transform(),
    ]
    layer = _new_layer(ind, 4, "pulse", frames)
    kf = [
        {"t": 0, "s": [96, 96], "i": {"x": [0.5], "y": [1]}, "o": {"x": [0.5], "y": [0]}},
        {"t": frames // 2, "s": [106, 106], "i": {"x": [0.5], "y": [1]}, "o": {"x": [0.5], "y": [0]}},
        {"t": frames, "s": [96, 96]},
    ]
    layer["ks"] = _layer_transform()
    layer["ks"]["s"] = {"a": 1, "k": kf}
    layer["shapes"] = [{"ty": "gr", "it": items, "nm": "PulseGroup"}]
    return layer


# ---------------------------------------------------------------------------
# main export
# ---------------------------------------------------------------------------

def build_lottie(doc):
    """Build the Lottie animation dict from a DiagramForge ops document."""
    canvas = doc.get("canvas", {})
    width = canvas.get("width", 1210)
    height = canvas.get("height", 1138)
    fps = canvas.get("fps", 20)
    frames = canvas.get("frames", 41)
    theme = doc.get("theme", {})
    bg = doc.get("bg", "#0f172a")

    layers = []
    ind = 1

    # Background plate
    bg_rgb = _hex_to_rgb(bg) or [0.06, 0.09, 0.16]
    bg_items = [
        {"ty": "rc", "p": _val([width / 2, height / 2]),
         "s": _val([width, height]), "r": _val(0), "nm": "Bg"},
        {"ty": "fl", "c": _val([bg_rgb[0], bg_rgb[1], bg_rgb[2], 1.0]), "o": _val(100)},
        _group_transform(),
    ]
    bg_layer = _new_layer(ind, 4, "background", frames)
    bg_layer["ks"] = _layer_transform()
    bg_layer["shapes"] = [{"ty": "gr", "it": bg_items, "nm": "BgGroup"}]
    layers.append(bg_layer)
    ind += 1

    # Pulse halos sit beneath the structure
    for pulse in doc.get("animation", {}).get("pulse_targets", []):
        layer = _pulse_layer(ind, pulse, theme, frames)
        if layer:
            layers.append(layer)
            ind += 1

    # Static structure from op stream (oldest op first -> bottom layer)
    for op in doc.get("ops", []):
        kind = op.get("op")
        layer = None
        if kind == "rect":
            layer = _rect_layer(ind, op, frames)
        elif kind == "ellipse":
            layer = _ellipse_layer(ind, op, frames)
        elif kind == "diamond":
            layer = _diamond_layer(ind, op, frames)
        elif kind == "line":
            layer = _line_layer(ind, op, frames)
        elif kind == "text":
            layer = _text_layer(ind, op, frames)
        elif kind == "icon":
            layer = _icon_layer(ind, op, frames)
        # 'image' ops need raster asset embedding (skipped to keep the file
        # vector-only); 'signature' is a decorative watermark (skipped).
        if layer is not None:
            layers.append(layer)
            ind += 1

    # Flow dots travel on top of the structure
    for path in doc.get("animation", {}).get("flow_paths", []):
        layer = _flow_dot_layer(ind, path, theme, frames)
        if layer:
            layers.append(layer)
            ind += 1

    # Lottie stacks layers top-down by ind; reverse so later ops paint above
    layers.reverse()
    for i, layer in enumerate(layers, 1):
        layer["ind"] = i

    return {
        "v": LOTTIE_VERSION,
        "fr": fps,
        "ip": 0,
        "op": frames,
        "w": width,
        "h": height,
        "nm": "diagram",
        "ddd": 0,
        "assets": [],
        "layers": layers,
        "meta": {"g": "diagramforge", "a": "", "d": "", "tc": ""},
    }


def export_lottie(doc, out_path):
    """Write the Lottie JSON to *out_path*. Returns the serialized dict."""
    data = build_lottie(doc)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data
