#!/usr/bin/env python3
"""Notation lint for the typed layouts -- the UML-semantics layer.

`spec_graph.py lint` judges structure (cycles, SPOFs, orphans, budgets) on
flowchart-family specs; this module judges *notation* on the typed ones —
the deterministic semantics an experienced reviewer checks by eye, in the
spirit of PlantUML's rigor:

- class       inheritance must be acyclic
- state       needs an initial state; every state reachable from initial
- activity    every node reachable from initial; a final node exists
- sequence    activations pair up (sync opens, return closes); message
              endpoints name declared participants
- er          relation endpoints name declared entities
- dfd         processes connect to at least one flow

Advisory by design: the report is JSON the agent reads before rendering;
`--check` remains the blocking gate. stdlib-only.

Usage:
    python -X utf8 scripts/lint_notation.py --spec spec.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _issue(issues, severity, kind, message, fix):
    issues.append({"severity": severity, "kind": kind, "message": message, "fix": fix})


def _ids(items):
    return {str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")}


def _neighbors(edges):
    adjacency = {}
    for e in edges:
        if isinstance(e, dict) and e.get("from") and e.get("to"):
            adjacency.setdefault(str(e["from"]), []).append(str(e["to"]))
    return adjacency


def lint_class(spec, issues):
    classes = _ids(spec.get("classes", []))
    inherit = [(str(r.get("from")), str(r.get("to"))) for r in spec.get("relations", [])
               if isinstance(r, dict) and r.get("kind") == "inheritance"
               and r.get("from") in classes and r.get("to") in classes]
    # DFS for a cycle in the inheritance graph (child -> parent edges).
    state = {}  # node -> "open" | "done"

    def walk(node, trail):
        state[node] = "open"
        for child_parent in inherit:
            if child_parent[0] != node:
                continue
            parent = child_parent[1]
            if state.get(parent) == "open":
                cycle = trail[trail.index(parent):] + [parent]
                _issue(issues, "error", "inheritance-cycle",
                       f"inheritance cycle: {' -> '.join(cycle)}",
                       "inheritance must form a tree/DAG; break the cycle by promoting the shared behavior")
            elif parent not in state:
                walk(parent, trail + [parent])
        state[node] = "done"

    for cid in classes:
        if cid not in state:
            walk(cid, [cid])


def lint_state(spec, issues):
    states = spec.get("states", [])
    node_ids = _ids(states)
    if not node_ids:
        return
    if not any(isinstance(s, dict) and s.get("kind") == "initial" for s in states):
        _issue(issues, "warning", "no-initial",
               "state machine declares no initial state",
               'add {"id": "start", "kind": "initial"} and a transition out of it')
    transitions = spec.get("transitions", [])
    initials = [str(s["id"]) for s in states if isinstance(s, dict) and s.get("kind") == "initial" and s.get("id")]
    adjacency = _neighbors(transitions)
    seen = set()
    stack = list(initials)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    if initials:
        unreachable = sorted(n for n in node_ids if n not in seen)
        if unreachable:
            _issue(issues, "warning", "unreachable-state",
                   f"unreachable from initial: {', '.join(unreachable[:8])}",
                   "add a transition into them or remove the dead states")


def lint_sequence(spec, issues):
    participants = _ids(spec.get("participants", []))
    depth = {p: 0 for p in participants}
    ever_open = set()
    for i, msg in enumerate(spec.get("messages", [])):
        if not isinstance(msg, dict):
            continue
        kind = msg.get("kind", "sync")
        src, dst = msg.get("from"), msg.get("to")
        if kind == "note":
            continue
        for role, endpoint in (("from", src), ("to", dst)):
            if endpoint is not None and str(endpoint) not in participants:
                _issue(issues, "error", "unknown-participant",
                       f"message {i + 1} {role}='{endpoint}' is not a declared participant",
                       "add the participant or fix the id")
                break
        if dst in depth and kind == "sync" and msg.get("activate", True) is not False:
            depth[str(dst)] += 1
            ever_open.add(str(dst))
        if src in depth and kind == "return":
            if depth[str(src)] == 0:
                # Retry loops legally send several returns per activation, so
                # only a reply from a never-activated participant is a smell.
                if str(src) not in ever_open:
                    _issue(issues, "warning", "return-without-activation",
                           f"message {i + 1}: return from '{src}' but no sync ever opened its activation",
                           f"drop the message, or precede it with a sync call into '{src}'")
            else:
                depth[str(src)] -= 1
    dangling = sorted(p for p, d in depth.items() if d > 0)
    if dangling:
        _issue(issues, "warning", "unbalanced-activation",
               f"activation never closed for: {', '.join(dangling)}",
               "close each sync with a matching return, or set \"activate\": false on fire-and-forget calls")


def lint_er(spec, issues):
    entities = _ids(spec.get("entities", []))
    for i, rel in enumerate(spec.get("relations", [])):
        if not isinstance(rel, dict):
            continue
        for role in ("from", "to"):
            endpoint = rel.get(role)
            if endpoint is not None and str(endpoint) not in entities:
                _issue(issues, "error", "unknown-entity",
                       f"relation {i + 1} {role}='{endpoint}' is not a declared entity",
                       "add the entity or fix the id")


def lint_activity(spec, issues):
    nodes = spec.get("nodes", [])
    node_ids = _ids(nodes)
    if not node_ids:
        return
    if not any(isinstance(n, dict) and n.get("kind") == "final" for n in nodes):
        _issue(issues, "warning", "no-final",
               "activity flow declares no final node",
               'add {"id": "done", "kind": "final"} so the flow has a defined end')
    initials = [str(n["id"]) for n in nodes if isinstance(n, dict) and n.get("kind") == "initial" and n.get("id")]
    adjacency = _neighbors(spec.get("edges", []))
    seen = set()
    stack = list(initials)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    if not initials:
        _issue(issues, "warning", "no-initial",
               "activity flow has no initial node; reachability is not defined",
               'add {"id": "start", "kind": "initial"} and an edge into the flow')
    else:
        unreachable = sorted(n for n in node_ids if n not in seen)
        if unreachable:
            _issue(issues, "warning", "unreachable-node",
                   f"unreachable from initial: {', '.join(unreachable[:8])}",
                   "connect them into the flow, or drop them — dead boxes read as mistakes")


def lint_dfd(spec, issues):
    flows = spec.get("flows", [])
    connected = set()
    for f in flows:
        if isinstance(f, dict):
            connected.add(str(f.get("from")))
            connected.add(str(f.get("to")))
    for i, node in enumerate(spec.get("nodes", [])):
        if isinstance(node, dict) and node.get("kind", "process") == "process" \
                and str(node.get("id")) not in connected:
            _issue(issues, "warning", "flowless-process",
                   f"process '{node.get('id')}' has no flows",
                   "processes transform data — connect it with flows or restate it as an external/store")


LINTERS = {
    "class": lint_class,
    "state": lint_state,
    "sequence": lint_sequence,
    "er": lint_er,
    "activity": lint_activity,
    "dfd": lint_dfd,
}


def lint(spec):
    layout = str(spec.get("layout", "panorama"))
    issues = []
    linter = LINTERS.get(layout)
    if linter is not None:
        linter(spec, issues)
    severities = [i["severity"] for i in issues]
    return {
        "ok": "error" not in severities,
        "layout": layout,
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", required=True, help="Path to spec JSON.")
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    print(json.dumps(lint(spec), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
