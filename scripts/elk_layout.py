#!/usr/bin/env python3
"""ELK.js layered-layout bridge for DiagramForge.

Runs the Eclipse Layout Kernel's Layered algorithm inside headless Chromium
(via the bundled ``assets/vendor/elk.min.js``) and returns node positions plus
orthogonal edge routes. The Layered algorithm (Coffman-Graham layering +
crossing minimization sweeps + network-simplex node placement) produces
near-optimal layouts for directed graphs that the legacy longest-path +
barycenter heuristic cannot match once node count climbs past ~12.

The bridge is **optional**: returns ``None`` when ELK, Playwright, or Chromium
is unavailable, so ``graph_model.plan_graph`` falls back to the stdlib legacy
layout transparently. This keeps ``graph_model`` importable without any
browser dependency — ELK is imported lazily inside the layout call.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELK_JS = ROOT / "assets" / "vendor" / "elk.min.js"

# Loaded once per process; the ELK bundle is ~1.6 MB so caching matters.
_ELK_SRC_CACHE = None


def is_available() -> bool:
    """True when the bundled ELK script is present on disk."""
    return ELK_JS.is_file()


def _elk_source() -> str:
    global _ELK_SRC_CACHE
    if _ELK_SRC_CACHE is None:
        _ELK_SRC_CACHE = ELK_JS.read_text(encoding="utf-8")
    return _ELK_SRC_CACHE


# Evaluate this inside the page; Playwright auto-awaits the async elk.layout().
_LAYOUT_JS = """
async ([graph]) => {
    const elk = new ELK();
    return await elk.layout(graph);
}
"""


def layout_graph(node_specs, edge_specs, direction="right", spacing=50):
    """Run ELK Layered and return coordinates.

    Parameters
    ----------
    node_specs : list of {id, w, h}
        Nodes with their fixed sizes (ELK does not size them).
    edge_specs : list of {id, from, to}
        Directed edges with stable ids (used to map results back).
    direction : "right" | "down"
        Primary flow axis.
    spacing : int
        Base node-to-node spacing (cross-axis); between-layer spacing is 1.2x.

    Returns
    -------
    dict | None
        ``{"nodes": {id: (x, y, w, h)}, "edges": {id: [[x, y], ...]},
        "width": int, "height": int}`` in ELK's local coordinate space
        (origin top-left, content starting near 0,0), or ``None`` on failure.
    """
    if not ELK_JS.is_file():
        return None
    elk_direction = "DOWN" if direction == "down" else "RIGHT"
    graph = {
        "id": "root",
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": elk_direction,
            "elk.layered.spacing.nodeNodeBetweenLayers": str(int(spacing * 1.2)),
            "elk.spacing.nodeNode": str(spacing),
            "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
            "elk.layered.nodePlacement.favorStraightEdges": "true",
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
            "elk.layered.crossingMinimization.nofCrossings": "true",
        },
        "children": [
            {"id": n["id"], "width": n["w"], "height": n["h"]} for n in node_specs
        ],
        "edges": [  # pragma: no cover
            {"id": e["id"], "sources": [e["from"]], "targets": [e["to"]]}  # pragma: no cover
            for e in edge_specs  # pragma: no cover
        ],
    }
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(
                "<html><body><script>" + _elk_source() + "</script></body></html>"
            )
            result = page.evaluate(_LAYOUT_JS, [graph])
            browser.close()
    except Exception:
        return None

    nodes = {}
    for child in result.get("children", []):
        nodes[child["id"]] = (
            child.get("x", 0), child.get("y", 0),
            child.get("width", 0), child.get("height", 0),
        )
    edges = {}
    for edge in result.get("edges", []):
        pts = []
        for section in edge.get("sections", []):
            sp = section.get("startPoint", {})
            pts.append([sp.get("x", 0), sp.get("y", 0)])
            for bp in section.get("bendPoints", []):
                pts.append([bp.get("x", 0), bp.get("y", 0)])
            ep = section.get("endPoint", {})
            pts.append([ep.get("x", 0), ep.get("y", 0)])
        edges[edge["id"]] = pts
    return {
        "nodes": nodes, "edges": edges,
        "width": result.get("width", 0), "height": result.get("height", 0),
    }
