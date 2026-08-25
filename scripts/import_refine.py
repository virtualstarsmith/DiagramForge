#!/usr/bin/env python3
"""Shared import refinement dials for draw.io / Mermaid imports.

Four dials shape every imported diagram before it is redrawn:

- **detail** — how much of the source survives: ``faithful`` (<=24 nodes,
  only unconnected ornaments are dropped), ``balanced`` (<=12), or
  ``simplified`` (<=7). Reduction follows a fixed degrade ladder: orphans,
  then duplicate-label merges, then degree-2 chain collapses, then
  infrastructure leaves.
- **audience** — wording, not count: ``engineer`` keeps everything,
  ``mixed`` strips ports/schemes, ``executive`` also drops protocol jargon
  and caps label length. Anything beyond these mechanical rewrites is the
  agent's job (see SKILL.md).
- **size** — handled by callers via canvas presets.
- **format** — handled by the renderer's ``--formats``.

Every reduction lands in a **fidelity ledger** — merged, collapsed, or
dropped entries with reasons — because the user knows the source and would
notice a silent omission anyway.
"""
from __future__ import annotations

import re

DETAIL_BUDGETS = {"faithful": 24, "balanced": 12, "simplified": 7}
DETAIL_CHOICES = tuple(DETAIL_BUDGETS)
AUDIENCE_CHOICES = ("engineer", "mixed", "executive")

INFRA_KEYWORDS = (
    "db", "database", "cache", "redis", "postgres", "mysql", "kafka", "queue",
    "s3", "storage", "elasticsearch", "mongo", "数据库", "缓存", "存储", "队列",
)
_PORT_RE = re.compile(r":[0-9]{2,5}\b")
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_PROTOCOL_RE = re.compile(
    r"\b(jwt|rs256|hs256|oauth2?|grpc|graphql|rest|tcp|udp|tls|ssl|http2?)\b", re.IGNORECASE
)
_WS_RE = re.compile(r"\s+")


def new_ledger(detail, audience, source_nodes):
    return {
        "detail": detail,
        "audience": audience,
        "source_nodes": source_nodes,
        "drawn_nodes": source_nodes,
        "merged": [],
        "collapsed": [],
        "dropped": [],
        "reworded": 0,
        "over_budget": False,
    }


def format_ledger(ledger):
    """Human-readable fidelity ledger for CLI output."""
    lines = [
        f"Detail: {ledger['detail']} · {ledger['source_nodes']} source nodes → {ledger['drawn_nodes']} drawn"
    ]
    for entry in ledger["collapsed"]:
        lines.append(f"Collapsed: {entry}")
    for entry in ledger["merged"]:
        lines.append(f"Merged: {entry}")
    for entry in ledger["dropped"]:
        lines.append(f"Dropped: {entry}")
    if ledger["reworded"]:
        lines.append(f"Reworded: {ledger['reworded']} labels for {ledger['audience']} audience")
    if ledger["over_budget"]:
        lines.append("Over budget: source still exceeds the detail budget after all reductions — consider splitting into overview + detail")
    return lines


# --------------------------------------------------------------------------
# Audience dial — mechanical wording only
# --------------------------------------------------------------------------

def _reword_label(label, audience):
    text = _WS_RE.sub(" ", str(label)).strip()
    if audience == "engineer":
        return text, text != str(label).strip()
    out = _PORT_RE.sub("", text)
    out = _SCHEME_RE.sub("", out)
    if audience == "executive":
        out = _PROTOCOL_RE.sub("", out)
        out = _WS_RE.sub(" ", out).strip(" ·-—")
        if " " in out:
            words = out.split()
            if len(words) > 3:
                out = " ".join(words[:3])
        elif len(out) > 12:  # unspaced (e.g. CJK): cap characters
            out = out[:12]
    return out, out != text


def apply_audience(spec, audience, ledger):
    """Rewrite label-ish fields in place; count changes in the ledger."""
    if audience == "engineer":
        return spec

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("label"), str):
                new, changed = _reword_label(value["label"], audience)
                if changed:
                    value["label"] = new
                    ledger["reworded"] += 1
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(spec)
    return spec


# --------------------------------------------------------------------------
# Detail dial — fixed degrade ladder for graph specs (nodes + edges)
# --------------------------------------------------------------------------

def _degree_maps(nodes, edges):
    node_ids = {n["id"] for n in nodes}
    out_map = {nid: [] for nid in node_ids}
    in_map = {nid: [] for nid in node_ids}
    for edge in edges:
        if edge.get("to") in node_ids and edge.get("from") in node_ids:
            out_map[edge["from"]].append(edge)
            in_map[edge["to"]].append(edge)
    return in_map, out_map


def _drop_orphans(nodes, edges, ledger):
    connected = {e["from"] for e in edges} | {e["to"] for e in edges}
    kept = [n for n in nodes if n["id"] in connected]
    for node in nodes:
        if node["id"] not in connected:
            ledger["dropped"].append(f'orphan "{node.get("label", node["id"])}" — unconnected in source')
    return kept, list(edges)


def _merge_duplicates(nodes, edges, ledger):
    by_label = {}
    alias = {}
    kept = []
    for node in nodes:
        key = _WS_RE.sub(" ", str(node.get("label", "")).strip().lower())
        if key and key in by_label:
            alias[node["id"]] = by_label[key]
            ledger["merged"].append(f'"{node.get("label")}" merged into duplicate "{by_label[key]}"')
        else:
            if key:
                by_label[key] = node["id"]
            kept.append(node)
    if not alias:
        return nodes, edges
    remap = lambda nid: alias.get(nid, nid)
    new_edges = []
    seen = set()
    for edge in edges:
        pair = (remap(edge["from"]), remap(edge["to"]))
        if pair[0] == pair[1] or (pair, edge.get("label", "")) in seen:
            continue
        seen.add((pair, edge.get("label", "")))
        new_edges.append(dict(edge, **{"from": pair[0], "to": pair[1]}))
    return kept, new_edges


def _collapse_chains(nodes, edges, budget, ledger):
    """Fold degree-2 middle nodes (one in, one out, no group) into edge labels."""
    nodes = list(nodes)
    edges = list(edges)
    while len(nodes) > budget:
        in_map, out_map = _degree_maps(nodes, edges)
        grouped = {n["id"] for n in nodes if n.get("parent")}
        victim = next(
            (n for n in nodes
             if n["id"] not in grouped
             and len(in_map.get(n["id"], [])) == 1
             and len(out_map.get(n["id"], [])) == 1
             # collapsing a node whose in/out edges share an endpoint would
             # produce a self-loop
             and in_map[n["id"]][0]["from"] != out_map[n["id"]][0]["to"]),
            None,
        )
        if victim is None:
            break
        vid = victim["id"]
        src, dst = in_map[vid][0], out_map[vid][0]
        label = victim.get("label", vid)
        if src.get("label"):
            label = f'{src["label"]} → {label}'
        edges = [e for e in edges if e is not src and e is not dst]
        edges.append({"from": src["from"], "to": dst["to"], "label": label, "style": dst.get("style", "solid")})
        nodes = [n for n in nodes if n["id"] != vid]
        ledger["collapsed"].append(f'"{victim.get("label", vid)}" → edge label on {src["from"]} → {dst["to"]}')
    return nodes, edges


def _drop_infra_leaves(nodes, edges, budget, ledger):
    nodes = list(nodes)
    edges = list(edges)
    while len(nodes) > budget:
        in_map, out_map = _degree_maps(nodes, edges)
        victim = next(
            (n for n in nodes
             if len(in_map.get(n["id"], [])) + len(out_map.get(n["id"], [])) == 1
             and any(kw in str(n.get("label", "")).lower() for kw in INFRA_KEYWORDS)),
            None,
        )
        if victim is None:
            break
        vid = victim["id"]
        nodes = [n for n in nodes if n["id"] != vid]
        edges = [e for e in edges if e.get("from") != vid and e.get("to") != vid]
        ledger["dropped"].append(f'infrastructure leaf "{victim.get("label", vid)}" — dropped at this detail level')
    return nodes, edges


def apply_detail(spec, detail, ledger):
    """Reduce a graph spec toward the detail budget via the fixed ladder."""
    if spec.get("layout") != "graph" or not isinstance(spec.get("nodes"), list):
        return spec
    budget = DETAIL_BUDGETS[detail]
    nodes, edges = spec["nodes"], spec.get("edges", [])

    nodes, edges = _drop_orphans(nodes, edges, ledger)
    if detail != "faithful":
        if len(nodes) > budget:
            nodes, edges = _merge_duplicates(nodes, edges, ledger)
        if len(nodes) > budget:
            nodes, edges = _collapse_chains(nodes, edges, budget, ledger)
        if len(nodes) > budget:
            nodes, edges = _drop_infra_leaves(nodes, edges, budget, ledger)
    elif len(nodes) > budget:
        ledger["over_budget"] = True

    if len(nodes) > budget:
        ledger["over_budget"] = True
    spec["nodes"], spec["edges"] = nodes, edges
    ledger["drawn_nodes"] = len(nodes)
    return spec


def apply_dials(spec, detail="faithful", audience="engineer"):
    """Apply detail + audience dials to a parsed import spec. Returns (spec, ledger)."""
    node_count = len(spec.get("nodes") or spec.get("participants") or spec.get("entities") or [])
    ledger = new_ledger(detail, audience, node_count)
    spec = apply_detail(spec, detail, ledger)
    ledger["drawn_nodes"] = len(spec.get("nodes") or spec.get("participants") or spec.get("entities") or [])
    spec = apply_audience(spec, audience, ledger)
    return spec, ledger
