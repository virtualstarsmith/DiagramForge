#!/usr/bin/env python3
"""Structural analysis for DiagramForge specs -- the diagram as a knowledge graph.

Treats any spec (panorama, swimlane, or graph) as a directed graph and answers
agent/actionable questions about it: 

    lint       cycles, single points of failure, orphans, disconnected parts,
               and node-count guidance -- objective structure quality signals
    neighbors  what's connected to node X (blast radius / impact analysis)
    around     extract the N-hop neighborhood of X as a focused graph spec
    diff       added/removed/changed nodes and edges between two specs
    export     spec -> Mermaid flowchart or Graphviz DOT (diffable, embeddable)

All commands read specs with the same layout planner the renderer uses, so the
analyzed graph matches what the interactive HTML shows. stdlib-only.

Examples:
    python -X utf8 scripts/spec_graph.py lint --spec spec.json
    python -X utf8 scripts/spec_graph.py neighbors --spec spec.json --node gate
    python -X utf8 scripts/spec_graph.py around --spec spec.json --node gate --hops 1 --out sub.json
    python -X utf8 scripts/spec_graph.py diff --spec v1.json --other v2.json
    python -X utf8 scripts/spec_graph.py export --spec spec.json --format mermaid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph_model  # noqa: E402

# Comfortable element budgets per layout (see references/design-system.md).
BUDGETS = {
    "panorama": {"comfortable": 15, "label": "panorama elements"},
    "swimlane": {"comfortable": 40, "label": "swimlane steps"},
    "grid": {"comfortable": 36, "label": "grid steps"},
    "graph": {"comfortable": 15, "label": "graph nodes"},
    "sequence": {"comfortable": 20, "label": "sequence messages"},
    "er": {"comfortable": 8, "label": "er entities"},
    "usecase": {"comfortable": 12, "label": "usecase items"},
    "class": {"comfortable": 8, "label": "class boxes"},
    "activity": {"comfortable": 15, "label": "activity nodes"},
    "state": {"comfortable": 10, "label": "state nodes"},
    "dfd": {"comfortable": 12, "label": "dfd nodes"},
    "deployment": {"comfortable": 10, "label": "deployment nodes"},
    "component": {"comfortable": 10, "label": "component items"},
    "package": {"comfortable": 10, "label": "packages"},
    "object": {"comfortable": 8, "label": "object boxes"},
    "composite": {"comfortable": 10, "label": "composite parts"},
    "profile": {"comfortable": 10, "label": "profile items"},
    "communication": {"comfortable": 10, "label": "communication objects"},
    "timing": {"comfortable": 12, "label": "timing lifelines/events"},
    "interaction": {"comfortable": 12, "label": "interaction frames"},
    "c4": {"comfortable": 12, "label": "c4 elements"},
    "gantt": {"comfortable": 20, "label": "gantt tasks"},
    "bpmn": {"comfortable": 15, "label": "bpmn elements"},
    "orgchart": {"comfortable": 15, "label": "orgchart nodes"},
    "mindmap": {"comfortable": 16, "label": "mindmap topics"},
    "timeline": {"comfortable": 10, "label": "timeline events"},
    "fishbone": {"comfortable": 16, "label": "fishbone categories/causes"},
}


# ---------------------------------------------------------------------------
# Graph normalization
# ---------------------------------------------------------------------------

def load_spec_graph(spec):
    """Spec -> normalized directed graph.

    For ``graph`` specs the author's declared nodes/edges are used directly,
    so lint sees cycles exactly as written (the layout planner silently
    converts back edges into loop channels, which would hide them). For
    ``panorama``/``swimlane`` the renderer's layout planner derives the graph.

    Returns {"nodes": {id: {...}}, "edges": [{"from","to","label","kind"}],
    "membership": [(leaf, container)]}. Edges referencing non-node ids
    synthesize placeholder nodes so connectivity analysis stays intact.
    """
    if graph_model.get_layout(spec) == "graph" and isinstance(spec.get("nodes"), list):
        nodes = {}
        for node in spec["nodes"]:
            if not isinstance(node, dict) or not node.get("id"):
                continue
            nodes[node["id"]] = {
                "label": node.get("label", node["id"]),
                "kind": node.get("kind", "card"),
                "icon": node.get("icon"),
                "group": None,
            }
        edges = []
        for edge in spec.get("edges", []):
            if not isinstance(edge, dict):
                continue
            src, dst = edge.get("from"), edge.get("to")
            if not src or not dst:
                continue
            for nid in (src, dst):
                if nid not in nodes:
                    nodes[nid] = {"label": nid, "kind": "card", "icon": None, "group": None}
            edges.append({
                "from": src,
                "to": dst,
                "label": edge.get("label", "") or "",
                "kind": "loop" if edge.get("kind") == "loop" else "flow",
            })
        return {"nodes": nodes, "edges": edges, "membership": []}

    built = graph_model.build_graph(spec)
    nodes = {}
    for node in built["nodes"]:
        nodes[node["id"]] = {
            "label": node.get("label", node["id"]),
            "kind": node.get("kind", "card"),
            "icon": node.get("icon"),
            "group": node.get("group"),
        }
    edges = []
    for edge in built["edges"]:
        src, dst = edge.get("from"), edge.get("to")
        if not src or not dst:
            continue  # pragma: no cover - build_graph normalizes endpoints
        for nid in (src, dst):
            if nid not in nodes:
                nodes[nid] = {"label": nid, "kind": "group", "icon": None, "group": None}  # pragma: no cover - built graphs always reference known nodes
        edges.append({
            "from": src,
            "to": dst,
            "label": edge.get("label", "") or "",
            "kind": edge.get("kind") or ("loop" if edge.get("loop") else "flow"),
        })
    # Leaf cards that live inside a group container (panorama input strip,
    # panel cards) have no individual edges; membership links let connectivity
    # analysis (orphans / SPOFs / components) see them as attached, without
    # polluting directed analyses (cycles, exports, diffs).
    membership = [
        (nid, info["group"])
        for nid, info in nodes.items()
        if info.get("group") and info["group"] in nodes
    ]
    return {"nodes": nodes, "edges": edges, "membership": membership}


def directed_adjacency(graph):
    out = {nid: set() for nid in graph["nodes"]}
    for edge in graph["edges"]:
        out[edge["from"]].add(edge["to"])
    return out


def undirected_adjacency(graph):
    neighbors = {nid: set() for nid in graph["nodes"]}
    for edge in graph["edges"]:
        neighbors[edge["from"]].add(edge["to"])
        neighbors[edge["to"]].add(edge["from"])
    for member, group in graph.get("membership", []):
        neighbors[member].add(group)
        neighbors[group].add(member)
    return neighbors


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def find_cycles(graph):
    """Directed cycles as node-id paths (declared `loop` edges excluded: they
    are intentional feedback channels, not accidental cycles)."""
    out = directed_adjacency(graph)
    for edge in graph["edges"]:
        if edge["kind"] == "loop":
            out[edge["from"]].discard(edge["to"])
    color = {nid: 0 for nid in graph["nodes"]}
    cycles, stack = [], []

    def visit(nid):
        color[nid] = 1
        stack.append(nid)
        for nxt in out[nid]:
            if color[nxt] == 0:
                visit(nxt)
            elif color[nxt] == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
        stack.pop()
        color[nid] = 2

    for nid in graph["nodes"]:
        if color[nid] == 0:
            visit(nid)
    return cycles


def find_articulation_points(graph):
    """Undirected articulation points = single points of failure: removing one
    disconnects the diagram."""
    neighbors = undirected_adjacency(graph)
    index, low, ap = {}, {}, set()
    counter = [0]

    def dfs(nid, parent):
        index[nid] = low[nid] = counter[0]
        counter[0] += 1
        children = 0
        for nxt in neighbors[nid]:
            if nxt not in index:
                children += 1
                dfs(nxt, nid)
                low[nid] = min(low[nid], low[nxt])
                if parent is not None and low[nxt] >= index[nid]:
                    ap.add(nid)
            elif nxt != parent:
                low[nid] = min(low[nid], index[nxt])
        if parent is None and children > 1:
            ap.add(nid)

    for nid in graph["nodes"]:
        if nid not in index:
            dfs(nid, None)
    return sorted(ap)


def find_components(graph):
    neighbors = undirected_adjacency(graph)
    seen, components = set(), []
    for nid in graph["nodes"]:
        if nid in seen:
            continue
        group, queue = [], deque([nid])
        seen.add(nid)
        while queue:
            cur = queue.popleft()
            group.append(cur)
            for nxt in neighbors[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        components.append(sorted(group))
    return components


def lint(spec):
    graph = load_spec_graph(spec)
    layout = graph_model.get_layout(spec)
    issues = []

    def issue(severity, kind, message, fix, nodes=None):
        entry = {"severity": severity, "kind": kind, "message": message, "fix": fix}
        if nodes:
            entry["nodes"] = nodes
        issues.append(entry)

    # Panorama is a fixed art-directed template (its retry/return loops and
    # junction nodes are by design), so cycle/SPOF checks only apply to the
    # free-form layouts where the author owns the topology.
    if layout in ("graph", "swimlane"):
        cycles = find_cycles(graph)
        for cycle in cycles:
            labels = " -> ".join(graph["nodes"][n]["label"] or n for n in cycle)
            issue("warning", "cycle", f"undeclared cycle: {labels}",
                  "if intentional, mark the return edge kind:'loop' so it renders as a dashed feedback channel",
                  nodes=cycle)

        # Only branching junctions (degree >= 3) are meaningful SPOF signals;
        # every middle node of a plain chain is an articulation point.
        neighbors = undirected_adjacency(graph)
        spofs = [nid for nid in find_articulation_points(graph) if len(neighbors[nid]) >= 3]
        for nid in spofs:
            label = graph["nodes"][nid]["label"] or nid
            issue("warning", "single_point_of_failure", f"'{label}' ({nid}) disconnects the diagram if removed",
                  "consider a redundant path, or make the bottleneck explicit in the narrative",
                  nodes=[nid])

        orphans = sorted(nid for nid, adj in neighbors.items() if not adj)
        for nid in orphans:
            label = graph["nodes"][nid]["label"] or nid
            issue("warning", "orphan_node", f"'{label}' ({nid}) has no connections",
                  "connect it to the flow or remove it", nodes=[nid])

        components = find_components(graph)
        # A swimlane whose connections never cross lane boundaries is a
        # comparison chart — its lanes are independent flows by design.
        lane_of = {}
        for lane in spec.get("lanes", []) if isinstance(spec.get("lanes"), list) else []:
            for step in lane.get("steps", []):
                if isinstance(step, dict) and step.get("id"):
                    lane_of[step["id"]] = lane.get("title")
        cross_lane = any(
            lane_of.get(c.get("from")) != lane_of.get(c.get("to"))
            for c in spec.get("connections", []) if isinstance(c, dict)
        ) if layout == "swimlane" else False
        intended_flow = layout == "graph" or cross_lane
        if len(components) > 1 and intended_flow:
            issue("warning", "disconnected", f"graph has {len(components)} disconnected parts",
                  "connect the parts or split into separate diagrams",
                  nodes=[nid for group in components[1:] for nid in group])

        budget = BUDGETS.get(layout, BUDGETS["graph"])
        n_nodes = len(graph["nodes"])
        if n_nodes > budget["comfortable"]:
            issue("info", "over_budget",
                  f"{n_nodes} {budget['label']} exceeds the comfortable {budget['comfortable']}",
                  "split into focused views; use `spec_graph.py around --node X --hops N` to render a neighborhood")

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "layout": layout,
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "issues": issues,
    }


def neighbors_of(spec, node_id):
    graph = load_spec_graph(spec)
    if node_id not in graph["nodes"]:
        known = ", ".join(sorted(graph["nodes"]))
        raise SystemExit(f"unknown node '{node_id}'. nodes: {known}")
    predecessors = sorted({e["from"] for e in graph["edges"] if e["to"] == node_id})
    successors = sorted({e["to"] for e in graph["edges"] if e["from"] == node_id})

    def describe(nid):
        return {"id": nid, "label": graph["nodes"][nid]["label"], "kind": graph["nodes"][nid]["kind"]}

    return {
        "ok": True,
        "node": describe(node_id),
        "depends_on": [describe(n) for n in predecessors],
        "affects": [describe(n) for n in successors],
        "degree": len(set(predecessors) | set(successors)),
    }


def neighborhood(spec, node_id, hops):
    graph = load_spec_graph(spec)
    if node_id not in graph["nodes"]:
        known = ", ".join(sorted(graph["nodes"]))
        raise SystemExit(f"unknown node '{node_id}'. nodes: {known}")
    neighbors = undirected_adjacency(graph)
    keep = {node_id}
    frontier = {node_id}
    for _ in range(max(1, hops)):
        frontier = {nxt for nid in frontier for nxt in neighbors[nid]} - keep
        keep |= frontier

    kind_map = {"decision": "decision", "terminal": "terminal"}
    nodes = []
    for nid in sorted(keep):
        info = graph["nodes"][nid]
        node = {"id": nid, "label": info["label"] or nid}
        if info["kind"] in kind_map:
            node["kind"] = kind_map[info["kind"]]
        if info.get("icon"):
            node["icon"] = info["icon"]
        nodes.append(node)
    edges = [
        {k: v for k, v in {
            "from": e["from"], "to": e["to"],
            "label": e["label"] or None, "kind": "loop" if e["kind"] == "loop" else None,
        }.items() if v is not None}
        for e in graph["edges"] if e["from"] in keep and e["to"] in keep
    ]
    title = spec.get("title", {}) if isinstance(spec.get("title"), dict) else {}
    highlight = title.get("highlight") or graph["nodes"][node_id]["label"] or node_id
    return {
        "layout": "graph",
        "style": spec.get("style", "slate"),
        "animation": spec.get("animation", "flow"),
        "title": {"prefix": title.get("prefix", "Around"), "highlight": highlight,
                  "subtitle": f"{hops}-hop neighborhood of {node_id}"},
        "direction": spec.get("direction", "right"),
        "nodes": nodes,
        "edges": edges,
    }


def diff_specs(spec_a, spec_b):
    ga, gb = load_spec_graph(spec_a), load_spec_graph(spec_b)

    def node_view(graph):
        return {nid: info["label"] for nid, info in graph["nodes"].items()}

    def edge_view(graph):
        return {(e["from"], e["to"], e["label"], e["kind"]) for e in graph["edges"]}

    na, nb = node_view(ga), node_view(gb)
    ea, eb = edge_view(ga), edge_view(gb)

    def edge_dicts(edge_set):
        rows = ({"from": f, "to": t, "label": l, "kind": k} for f, t, l, k in edge_set)
        return sorted(rows, key=lambda r: (r["from"], r["to"], r["label"], r["kind"]))

    return {
        "ok": True,
        "nodes": {
            "added": sorted(set(nb) - set(na)),
            "removed": sorted(set(na) - set(nb)),
            "label_changed": sorted(nid for nid in set(na) & set(nb) if na[nid] != nb[nid]),
        },
        "edges": {
            "added": edge_dicts(eb - ea),
            "removed": edge_dicts(ea - eb),
        },
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _mermaid_id(raw, used):
    mid = re.sub(r"[^0-9A-Za-z_]", "_", raw) or "node"
    if mid[0].isdigit():
        mid = f"n_{mid}"
    base, i = mid, 2
    while mid in used:
        mid = f"{base}_{i}"
        i += 1
    used.add(mid)
    return mid


def export_mermaid(spec):
    graph = load_spec_graph(spec)
    direction = "TD" if spec.get("direction") == "down" else "LR"
    lines = [f"graph {direction}"]
    used, ids = set(), {}
    for nid, info in graph["nodes"].items():
        ids[nid] = _mermaid_id(nid, used)
        label = (info["label"] or nid).replace('"', "'")
        if info["kind"] == "decision":
            lines.append(f'    {ids[nid]}{{"{label}"}}')
        elif info["kind"] == "terminal":
            lines.append(f'    {ids[nid]}(["{label}"])')
        else:
            lines.append(f'    {ids[nid]}["{label}"]')
    for edge in graph["edges"]:
        src, dst = ids[edge["from"]], ids[edge["to"]]
        label = edge["label"].replace('"', "'")
        if edge["kind"] == "loop":
            arrow = f'-. "{label}" .->' if label else "-.->"
        else:
            arrow = f'-- "{label}" -->' if label else "-->"
        lines.append(f"    {src} {arrow} {dst}")
    return "\n".join(lines)


def export_dot(spec):
    graph = load_spec_graph(spec)
    rankdir = "TB" if spec.get("direction") == "down" else "LR"
    lines = ["digraph diagramforge {", f"    rankdir={rankdir};"]
    for nid, info in graph["nodes"].items():
        shape = {"decision": "diamond", "terminal": "oval"}.get(info["kind"], "box")
        label = (info["label"] or nid).replace('"', "'")
        lines.append(f'    "{nid}" [label="{label}", shape={shape}];')
    for edge in graph["edges"]:
        attrs = []
        if edge["label"]:
            attrs.append(f'label="{edge["label"]}"')
        if edge["kind"] == "loop":
            attrs.append("style=dashed")
        suffix = f" [{', '.join(attrs)}]" if attrs else ""
        lines.append(f'    "{edge["from"]}" -> "{edge["to"]}"{suffix};')
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_spec(p, name="--spec"):
        p.add_argument(name, required=True, help="Path to spec JSON.")

    p_lint = sub.add_parser("lint", help="Structural quality report (cycles, SPOFs, orphans, ...).")
    add_spec(p_lint)

    p_nb = sub.add_parser("neighbors", help="What's connected to a node (blast radius).")
    add_spec(p_nb)
    p_nb.add_argument("--node", required=True, help="Node id to inspect.")

    p_around = sub.add_parser("around", help="Extract an N-hop neighborhood as a focused graph spec.")
    add_spec(p_around)
    p_around.add_argument("--node", required=True, help="Center node id.")
    p_around.add_argument("--hops", type=int, default=1, help="Neighborhood radius (default 1).")
    p_around.add_argument("--out", default=None, help="Write the spec here instead of stdout.")

    p_diff = sub.add_parser("diff", help="Node/edge diff between two spec versions.")
    add_spec(p_diff)
    p_diff.add_argument("--other", required=True, help="Path to the other spec JSON.")

    p_export = sub.add_parser("export", help="Export the spec graph as Mermaid or Graphviz DOT.")
    add_spec(p_export)
    p_export.add_argument("--format", choices=["mermaid", "dot"], default="mermaid")

    args = parser.parse_args()
    spec = _load(args.spec)

    if args.command == "lint":
        _print_json(lint(spec))
        return 0
    if args.command == "neighbors":
        _print_json(neighbors_of(spec, args.node))
        return 0
    if args.command == "around":
        result = neighborhood(spec, args.node, args.hops)
        if args.out:
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            _print_json({"ok": True, "out": args.out, "nodes": len(result["nodes"]), "edges": len(result["edges"])})
        else:
            _print_json(result)
        return 0
    if args.command == "diff":
        _print_json(diff_specs(spec, _load(args.other)))
        return 0
    if args.command == "export":
        print(export_mermaid(spec) if args.format == "mermaid" else export_dot(spec))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
