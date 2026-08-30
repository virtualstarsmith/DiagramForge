#!/usr/bin/env python3
"""Structural analysis for DiagramForge specs -- the diagram as a knowledge graph.

Treats any spec (panorama, swimlane, or graph) as a directed graph and answers
agent/actionable questions about it: 

    lint       cycles, single points of failure, orphans, disconnected parts,
               and node-count guidance -- objective structure quality signals
    neighbors  what's connected to node X (blast radius / impact analysis)
    around     extract the N-hop neighborhood of X as a focused graph spec
    diff       added/removed/changed nodes and edges between two specs
    export     spec -> Mermaid (flowchart, or native sequenceDiagram /
               erDiagram / classDiagram / stateDiagram-v2 for typed layouts)
               or Graphviz DOT (diffable, embeddable)

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
    # "comfortable" matches design-system.md §5 (info-level nudge); "hard" is
    # the SKILL.md §2 capacity ceiling — exceeding it renders an unreadable
    # diagram and is an error-level lint issue. Edge caps apply where the
    # SKILL.md table publishes one.
    "panorama": {"comfortable": 15, "label": "panorama elements"},
    "swimlane": {"comfortable": 40, "hard": 64, "label": "swimlane steps"},
    "grid": {"comfortable": 36, "hard": 54, "label": "grid steps"},
    "graph": {"comfortable": 15, "hard": 24, "hard_edges": 40, "label": "graph nodes"},
    "sequence": {"comfortable": 20, "hard": 30, "label": "sequence messages"},
    "er": {"comfortable": 8, "hard": 12, "hard_edges": 16, "label": "er entities"},
    "usecase": {"comfortable": 12, "hard": 22, "hard_edges": 24, "label": "usecase items"},
    "class": {"comfortable": 8, "hard": 10, "hard_edges": 16, "label": "class boxes"},
    "activity": {"comfortable": 15, "hard": 24, "hard_edges": 40, "label": "activity nodes"},
    "state": {"comfortable": 10, "hard": 20, "hard_edges": 30, "label": "state nodes"},
    "dfd": {"comfortable": 12, "hard": 20, "hard_edges": 30, "label": "dfd nodes"},
    "deployment": {"comfortable": 10, "hard": 16, "hard_edges": 20, "label": "deployment nodes"},
    "component": {"comfortable": 10, "hard": 12, "hard_edges": 16, "label": "component items"},
    "package": {"comfortable": 10, "hard": 14, "hard_edges": 16, "label": "packages"},
    "object": {"comfortable": 8, "hard": 12, "hard_edges": 16, "label": "object boxes"},
    "composite": {"comfortable": 10, "hard": 10, "hard_edges": 16, "label": "composite parts"},
    "profile": {"comfortable": 10, "hard": 14, "hard_edges": 20, "label": "profile items"},
    "communication": {"comfortable": 10, "hard": 12, "hard_edges": 20, "label": "communication objects"},
    "timing": {"comfortable": 12, "hard": 17, "hard_edges": 10, "label": "timing lifelines/events"},
    "interaction": {"comfortable": 12, "hard": 16, "hard_edges": 24, "label": "interaction frames"},
    "c4": {"comfortable": 12, "hard": 16, "hard_edges": 20, "label": "c4 elements"},
    "gantt": {"comfortable": 20, "hard": 80, "label": "gantt tasks"},
    "bpmn": {"comfortable": 15, "hard": 24, "hard_edges": 30, "label": "bpmn elements"},
    "orgchart": {"comfortable": 15, "hard": 24, "label": "orgchart nodes"},
    "mindmap": {"comfortable": 16, "hard": 50, "label": "mindmap topics"},
    "timeline": {"comfortable": 10, "hard": 12, "label": "timeline events"},
    "fishbone": {"comfortable": 16, "hard": 24, "label": "fishbone categories/causes"},
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

    # Complexity budget applies to every layout: "comfortable" is an
    # info-level nudge, the SKILL.md §2 "hard" ceiling is an error.
    # Panorama is a fixed art-directed template — the author doesn't control
    # element counts, so budget guidance is meaningless there (same precedent
    # as its topology-check exemption above).
    budget = None if layout == "panorama" else BUDGETS.get(layout)
    if budget:
        n_nodes = len(graph["nodes"])
        n_edges = len(graph["edges"])
        if budget.get("hard") and n_nodes > budget["hard"]:
            issue("error", "over_hard_budget",
                  f"{n_nodes} {budget['label']} exceeds the {budget['hard']} ceiling",
                  "split into an overview plus detail diagrams; never shrink the type to fit")
        elif n_nodes > budget["comfortable"]:
            issue("info", "over_budget",
                  f"{n_nodes} {budget['label']} exceeds the comfortable {budget['comfortable']}",
                  "split into focused views; use `spec_graph.py around --node X --hops N` to render a neighborhood")
        if budget.get("hard_edges") and n_edges > budget["hard_edges"]:
            issue("error", "over_hard_budget",
                  f"{n_edges} edges exceeds the {budget['hard_edges']} ceiling for {layout}",
                  "split into an overview plus detail diagrams; never shrink the type to fit")

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


def _export_mermaid_graph(spec):
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


def export_mermaid(spec):
    """Dispatch by layout: typed layouts get their native Mermaid syntax
    (sequenceDiagram / erDiagram / classDiagram / stateDiagram-v2); everything
    else falls back to the flowchart form."""
    exporter = MERMAID_LAYOUT_EXPORTERS.get(str(spec.get("layout", "graph")))
    if exporter is not None:
        return exporter(spec)
    return _export_mermaid_graph(spec)


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
# Mermaid exports for typed layouts (sequence / er / class / state).
# Same contract as the importers: a notated subset, with what is skipped said
# plainly in the notes comment — lossless round-trips are not the goal.
# ---------------------------------------------------------------------------

def _mm_id(value):
    """Mermaid identifiers must be alphanumeric/underscore."""
    clean = re.sub(r"[^0-9A-Za-z_]", "_", str(value))
    if not clean or clean[0].isdigit():
        clean = f"n_{clean}"
    return clean


def _mm_text(value):
    """One-line label text: statement separators and newlines flattened."""
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace(";", ",").replace('"', "'")
    return text.strip()


def export_mermaid_sequence(spec):
    participants = [p["id"] for p in spec.get("participants", [])]
    messages = spec.get("messages", [])
    lines = ["sequenceDiagram"]
    for p in spec.get("participants", []):
        label = _mm_text(p.get("label") or p["id"])
        head = "actor" if p.get("kind") == "actor" else "participant"
        if label and label != p["id"]:
            lines.append(f'    {head} {_mm_id(p["id"])} as {label}')
        else:
            lines.append(f'    {head} {_mm_id(p["id"])}')
    notes = []

    fragments = sorted(spec.get("fragments", []), key=lambda f: (f.get("range", [0, 0])[0], -f.get("range", [0, 0])[1]))
    open_stack = []  # fragments currently open, innermost last

    def close_due(index):
        while open_stack and open_stack[-1].get("range", [0, 0])[1] < index:
            open_stack.pop()
            lines.append("    end")

    for i, msg in enumerate(messages, start=1):
        close_due(i)
        for fragment in fragments:
            if fragment.get("range", [0, 0])[0] == i and fragment not in open_stack:
                kind = fragment.get("kind", "opt")
                if kind in ("alt", "opt", "loop", "par", "critical"):
                    lines.append(f"    {kind} {_mm_text(fragment.get('label', ''))}")
                    open_stack.append(fragment)
        for divider in fragment_dividers_at(spec, i):
            if open_stack:
                lines.append(f"    else {_mm_text(divider.get('label', ''))}")
        kind = msg.get("kind", "sync")
        label = _mm_text(msg.get("label", ""))
        colon = f": {label}" if label else ""
        if kind == "note":
            targets = msg.get("target") or []
            over = ", ".join(_mm_id(t) for t in targets[:2])
            lines.append(f"    Note over {over or _mm_id(participants[0])}{colon}")
        else:
            src, dst = _mm_id(msg.get("from", "")), _mm_id(msg.get("to", ""))
            arrow = {"sync": "->>", "async": "-)", "return": "-->>", "self": "->>"}.get(kind, "->>")
            if kind == "async" and not label:
                notes.append(f"async message {i} has no label")
            lines.append(f"    {src} {arrow}{dst}{colon}")
    close_due(len(messages) + 1)
    if notes:
        lines.append("    %% notes: " + "; ".join(notes))
    return "\n".join(lines)


def fragment_dividers_at(spec, index):
    for fragment in spec.get("fragments", []):
        for divider in fragment.get("dividers", []):
            if divider.get("at") == index:
                yield divider


ER_CARDINALITY = {
    "1:1": "||--||",
    "1:N": "||--o{",
    "N:1": "}o--||",
    "M:N": "}o--o{",
}


def export_mermaid_er(spec):
    lines = ["erDiagram"]
    for entity in spec.get("entities", []):
        eid = _mm_id(entity["id"])
        attrs = entity.get("attributes", [])
        if not attrs:
            lines.append(f"    {eid} {{")
            lines.append("    }")
            continue
        lines.append(f"    {eid} {{")
        for attr in attrs:
            key = str(attr.get("key", "")).lower()
            suffix = {"pk": " PK", "fk": " FK"}.get(key, "")
            name = _mm_text(attr.get("name", ""))
            atype = _mm_text(attr.get("type", "")) or "string"
            lines.append(f"        {atype} {name}{suffix}")
        lines.append("    }")
    for rel in spec.get("relations", []):
        crow = ER_CARDINALITY.get(str(rel.get("cardinality", "1:N")), "||--o{")
        label = _mm_text(rel.get("label", "")) or "relates"
        lines.append(f"    {_mm_id(rel['from'])} {crow} {_mm_id(rel['to'])} : {label}")
    return "\n".join(lines)


CLASS_ARROW = {
    "association": "--",
    "inheritance": "--|>",
    "composition": "*--",
    "aggregation": "o--",
    "dependency": "..>",
    "realization": "..|>",
}


def export_mermaid_class(spec):
    lines = ["classDiagram"]
    for klass in spec.get("classes", []):
        cid = _mm_id(klass["id"])
        attrs = klass.get("attributes", [])
        methods = klass.get("methods", [])
        if not attrs and not methods and not klass.get("kind"):
            lines.append(f"    class {cid}")
            continue
        lines.append(f"    class {cid} {{")
        if klass.get("kind") in ("interface", "enum", "abstract"):
            lines.append(f"        <<{klass['kind']}>>")
        for attr in attrs:
            vis = str(attr.get("visibility", "") or "")
            atype = _mm_text(attr.get("type", ""))
            name = _mm_text(attr.get("name", ""))
            lines.append(f"        {vis}{atype} {name}".rstrip())
        for method in methods:
            vis = str(method.get("visibility", "") or "")
            mtype = _mm_text(method.get("type", ""))
            name = _mm_text(method.get("name", ""))
            suffix = f" {mtype}" if mtype else ""
            lines.append(f"        {vis}{name}{suffix}".rstrip())
        lines.append("    }")
    for rel in spec.get("relations", []):
        arrow = CLASS_ARROW.get(str(rel.get("kind", "association")), "--")
        parts = [f"    {_mm_id(rel['from'])}"]
        if rel.get("from_card"):
            parts.append(f'"{_mm_text(rel["from_card"])}"')
        parts.append(arrow)
        if rel.get("to_card"):
            parts.append(f'"{_mm_text(rel["to_card"])}"')
        parts.append(_mm_id(rel["to"]))
        line = " ".join(parts)
        label = _mm_text(rel.get("label", ""))
        if label:
            line += f" : {label}"
        lines.append(line)
    return "\n".join(lines)


def export_mermaid_state(spec):
    states = {s["id"]: s for s in spec.get("states", [])}
    lines = ["stateDiagram-v2"]
    bodies = [str(s.get("body") or s.get("description") or "") for s in states.values()]
    bodies = [b for b in bodies if b]
    for transition in spec.get("transitions", []):
        src = states.get(transition.get("from"), {})
        dst = states.get(transition.get("to"), {})
        a = "[*]" if src.get("kind") == "initial" else _mm_id(transition["from"])
        b = "[*]" if dst.get("kind") == "final" else _mm_id(transition["to"])
        label = _mm_text(transition.get("label", ""))
        lines.append(f"    {a} --> {b}" + (f": {label}" if label else ""))
    if bodies:
        # Mermaid has no entry/do action syntax; `state "x" as id` would turn
        # the action body into a display name, so it is dropped, not mangled.
        lines.append("    %% notes: state entry/do bodies are not representable in mermaid")
    return "\n".join(lines)


MERMAID_LAYOUT_EXPORTERS = {
    "sequence": export_mermaid_sequence,
    "er": export_mermaid_er,
    "class": export_mermaid_class,
    "state": export_mermaid_state,
}


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

    p_export = sub.add_parser("export", help="Export the spec as Mermaid (graph/sequence/er/class/state) or Graphviz DOT.")
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
        if args.format == "dot" and str(spec.get("layout", "graph")) in MERMAID_LAYOUT_EXPORTERS:
            raise SystemExit(
                f"dot export covers flowchart-family layouts; a '{spec.get('layout')}' spec "
                f"exports natively via --format mermaid"
            )
        print(export_mermaid(spec) if args.format == "mermaid" else export_dot(spec))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
