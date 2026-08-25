#!/usr/bin/env python3
"""Import a Mermaid flowchart or sequence diagram as an DiagramForge spec.

Converts ``flowchart``/``graph`` (TD/LR/...) documents into the DiagramForge
``graph`` layout JSON, and ``sequenceDiagram`` documents into the DiagramForge
``sequence`` layout JSON, so existing Mermaid diagrams can be re-rendered as
hand-drawn animated art.

Supported flowchart subset (covers typical architecture/workflow charts):

- headers: ``graph TD`` / ``flowchart LR`` (LR/RL -> ``right``, TB/TD/BT -> ``down``)
- nodes: ``id[label]``, ``id{label}`` -> decision, ``id([label])`` / ``id(label)``
  / ``id((label))`` -> terminal, bare ``id`` and ``id[[label]]`` -> card
- edges: ``-->``, ``-- label -->``, ``-.->``, ``-. label .->``, ``==>``,
  chains (``a --> b --> c``) and fan lists (``a --> b & c``)
- ``%%`` comments and trailing semicolons

Not supported (ignored with a note): subgraphs, classDef/class styling, click
handlers, markdown label syntax. Cycle-closing edges are left as ``flow`` --
the DiagramForge planner already detects back edges and renders them as dashed
loop channels.

Supported sequenceDiagram subset:

- ``participant X as Label`` / ``actor X as Label`` declarations; undeclared
  ids join in first-use order
- messages: ``->>`` sync, ``->`` sync (plain line, arrowhead added),
  ``-->>`` return, ``-->`` async, ``-x``/``--x`` sync (lost-message marker
  simplified), ``-)``/``--)`` async; chained labels after ``:``
- ``Note left of / right of / over A[,B]: text`` -> note message
- ``alt``/``else``/``loop``/``opt``/``end`` -> combined fragments (nestable)
- ``activate``/``deactivate`` -> explicit activation overrides
- ``autonumber`` is ignored with a note; ``par``/``critical``/``break``/``rect``
  blocks are skipped with a note

Usage:
    python -X utf8 scripts/mermaid_import.py diagram.mmd --out spec.json
    cat diagram.mmd | python -X utf8 scripts/mermaid_import.py - --style report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Sibling modules must import even when this file is loaded from an arbitrary
# path (tests, editors), so pin the scripts dir onto sys.path.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import import_refine

# Resource caps for untrusted sources. Every source label, link, directive, and
# metadata field is treated as data, never as instructions; these caps keep a
# hostile or pathological document from exhausting the parser or the renderer.
# Exceeding a cap is a named failure (``resource_limit:<what>``), exit code 2 —
# the same severity as a spec-validation error.
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_NODES = 200
MAX_EDGES = 300
MAX_LABEL_CHARS = 200


def _fail(code, message):
    print(message, file=sys.stderr)
    sys.exit(code)

HEADER_RE = re.compile(r"^\s*(?:flowchart|graph)\s+([A-Za-z]{2})\s*$", re.IGNORECASE)
NODE_SHAPE_RE = r"[A-Za-z0-9_一-鿿][\w.-]*\s*(?:\[\([^]]*\)\]|\(\[[^\]]*\]\)|\(\([^)]*\)\)|\([^)]*\)|\{[^}]*\}|\[\[[^\]]*\]\]|\[[^\]]*\])?"
TOKEN_RE = re.compile(
    r"(?P<edge_labeled>(?:--|-\.|==)\s*(?:\"[^\"]*\"|[^>\-]+?)\s*(?:-->|\.->|==>))"
    r"|(?P<edge_plain>-->|==>|-\.->)"
    r"|(?P<node>" + NODE_SHAPE_RE + r")"
)
EDGE_PARTS_RE = re.compile(r"^\s*(?P<stem>--|-\.|==)\s*(?P<label>\"[^\"]*\"|.*?)\s*(?P<arrow>-->|\.->|==>)\s*$")
NODE_PATTERNS = [
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\[\((?P<label>.*)\)\]$"), "terminal"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\(\[(?P<label>.*)\]\)$"), "terminal"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\(\((?P<label>.*)\)\)$"), "terminal"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\((?P<label>.*)\)$"), "terminal"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\{(?P<label>.*)\}$"), "decision"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\[\[(?P<label>.*)\]\]$"), "card"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)\s*\[(?P<label>.*)\]$"), "card"),
    (re.compile(r"^(?P<id>[A-Za-z0-9_一-鿿][\w.-]*)$"), "card"),
]


def _clean_label(text):
    label = str(text or "").strip()
    if len(label) >= 2 and label[0] == label[-1] and label[0] in "\"'":
        label = label[1:-1]
    label = label.replace("<br/>", " ").replace("<br>", " ").strip()
    if len(label) > MAX_LABEL_CHARS:
        _fail(
            2,
            f"resource_limit:label_chars — a label is {len(label)} chars "
            f"(max {MAX_LABEL_CHARS}): {label[:60]!r}…",
        )
    return label


def parse_node(token, nodes, order):
    token = token.strip()
    for pattern, kind in NODE_PATTERNS:
        match = pattern.match(token)
        if match:
            nid = match.group("id")
            label = _clean_label(match.groupdict().get("label"))
            if nid not in nodes:
                nodes[nid] = {"label": label or nid, "kind": kind}
                order.append(nid)
            else:
                if label:
                    nodes[nid]["label"] = label
                if kind != "card":
                    nodes[nid]["kind"] = kind
            return nid
    return None  # pragma: no cover - the tokenizer only yields tokens NODE_PATTERNS matches


def _edge_attrs(token):
    """Mermaid edge token -> {"style", "label"} for an DiagramForge edge."""
    if token in ("-->", "==>", "-.->"):
        return {"style": "dotted" if "." in token else "solid", "label": ""}
    match = EDGE_PARTS_RE.match(token)
    if not match:
        return {"style": "solid", "label": ""}
    dotted = "." in match.group("stem") or "." in match.group("arrow")
    return {"style": "dotted" if dotted else "solid", "label": _clean_label(match.group("label"))}


def parse_mermaid(text):
    """Mermaid flowchart text -> (direction, nodes, order, edges, notes, groups, parents).

    ``groups`` is a list of ``{id, label}`` parsed from ``subgraph`` blocks;
    ``parents`` maps a node id to the id of the innermost subgraph that
    contained it, so DiagramForge can render the dashed group container.
    """
    direction = None
    nodes, order, edges, notes = {}, [], [], []
    groups, parents, group_stack = [], {}, []
    group_counter = 0
    # classDef -> accent role mapping (Mermaid class names to DiagramForge roles)
    class_roles = {}

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip().rstrip(";").strip()
        if not line:
            continue
        header = HEADER_RE.match(line)
        if header and direction is None:
            direction = "down" if header.group(1).upper() in ("TB", "TD", "BT") else "right"
            continue

        sub_m = re.match(r"^subgraph\s+(.+)$", line, re.IGNORECASE)
        if sub_m:
            group_counter += 1
            label_part = sub_m.group(1).strip().rstrip(";").strip()
            gid = f"grp{group_counter}"
            label = label_part
            # Common forms: `id [Label]`, `"Label"`, `id`, or `id Label`.
            br_m = re.match(r"^(\S+)\s*\[(.+)\]$", label_part)
            if br_m:
                gid = br_m.group(1)
                label = br_m.group(2)
            elif label_part.startswith('"') and label_part.endswith('"') and len(label_part) >= 2:
                label = label_part[1:-1]
            else:
                first = label_part.split()[0] if label_part.split() else label_part
                if re.match(r"^[A-Za-z0-9_]+$", first):
                    gid = first
                    label = label_part[len(first):].strip() or first
            groups.append({"id": gid, "label": label})
            group_stack.append(gid)
            continue
        if re.match(r"^end\s*$", line, re.IGNORECASE):
            if group_stack:
                group_stack.pop()
            continue
        class_def_m = re.match(r'^classDef\s+(\S+)\s+(.+)$', line, re.IGNORECASE)
        if class_def_m:
            # Record the class name; DiagramForge ignores the CSS but the class
            # itself can still route nodes to an accent role via a `class` line.
            continue
        class_m = re.match(r'^class\s+(\S+(?:\s*,\s*\S+)*)\s+(\S+)$', line, re.IGNORECASE)
        if class_m:
            targets = [t.strip() for t in class_m.group(1).split(",")]
            role = class_m.group(2)
            for t in targets:
                class_roles[t] = role
            continue
        if re.match(r"^(click|style|linkStyle)\b", line, re.IGNORECASE):
            continue

        last_node = None      # most recent node id on this line
        last_source = None    # node id that opened the current edge
        pending_edge = None   # edge attrs waiting for its target node
        last_edge = None      # attrs of the most recent edge (for `a --> b & c` fans)
        consumed = False
        for match in TOKEN_RE.finditer(line):
            token = match.group(0)
            if match.lastgroup == "node" or match.group("node") is not None:
                nid = parse_node(token, nodes, order)
                if nid is None:
                    continue  # pragma: no cover - parse_node never returns None for tokenizer-matched tokens
                consumed = True
                # Attach the node to its innermost subgraph if it lives in one.
                if group_stack and nid not in parents:
                    parents[nid] = group_stack[-1]
                if pending_edge is not None and last_source is not None:
                    edge = {"from": last_source, "to": nid, "style": pending_edge["style"]}
                    if pending_edge["label"]:
                        edge["label"] = pending_edge["label"]
                    edges.append(edge)
                elif last_edge is not None and last_source is not None and last_node is not None:
                    # Fan list (`a --> b & c`): consecutive node, repeat last edge.
                    edge = {"from": last_source, "to": nid, "style": last_edge["style"]}
                    if last_edge["label"]:
                        edge["label"] = last_edge["label"]
                    edges.append(edge)
                last_node = nid
                pending_edge = None
            else:
                attrs = _edge_attrs(token)
                consumed = True
                last_edge = attrs
                last_source = last_node
                pending_edge = attrs
        if not consumed:
            notes.append(f"skipped line: {line}")

    if direction is None:
        notes.append("no flowchart/graph header found; assumed direction 'right'")
    if groups:
        notes.append(f"parsed {len(groups)} subgraph group(s)")
    return direction or "right", nodes, order, edges, notes, groups, parents, class_roles


# ---------------------------------------------------------------------------
# sequenceDiagram import
# ---------------------------------------------------------------------------

SEQ_HEADER_RE = re.compile(r"^\s*sequenceDiagram\s*$", re.IGNORECASE)
_SEQ_ID = r"[A-Za-z0-9_一-鿿]\w*"
SEQ_DECL_RE = re.compile(rf"^\s*(participant|actor)\s+({_SEQ_ID})\s*(?:\s+as\s+(.+))?$", re.IGNORECASE)
SEQ_MSG_RE = re.compile(rf"^\s*({_SEQ_ID})\s*(-->>|->>|-->|->|-x|--x|-\)|--\))\s*({_SEQ_ID})\s*:\s*(.*)$")
SEQ_NOTE_RE = re.compile(rf"^\s*Note\s+(left of|right of|over)\s+({_SEQ_ID})(?:\s*,\s*({_SEQ_ID}))?\s*:\s*(.*)$",
                         re.IGNORECASE)
SEQ_FRAG_RE = re.compile(r"^\s*(alt|loop|opt)\b\s*(.*)$", re.IGNORECASE)
SEQ_ELSE_RE = re.compile(r"^\s*else\b\s*(.*)$", re.IGNORECASE)
SEQ_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)
SEQ_ACT_RE = re.compile(rf"^\s*(activate|deactivate)\s+({_SEQ_ID})\s*$", re.IGNORECASE)
SEQ_SKIP_RE = re.compile(r"^\s*(par|critical|break|rect|box|loop2|and)\b", re.IGNORECASE)

SEQ_ARROW_KINDS = {
    "->>": "sync", "->": "sync", "-x": "sync", "--x": "sync",
    "-->>": "return", "-->": "async", "-)": "async", "--)": "async",
}


ER_HEADER_RE = re.compile(r"^\s*erDiagram\s*$", re.IGNORECASE)
CLASS_HEADER_RE = re.compile(r"^\s*classDiagram\s*$", re.IGNORECASE)


def _diagram_kind(text):
    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line:
            continue
        if SEQ_HEADER_RE.match(line):
            return "sequence"
        if ER_HEADER_RE.match(line):
            return "er"
        if CLASS_HEADER_RE.match(line):
            return "class"
        if STATE_HEADER_RE.match(line):
            return "state"
        if GANTT_HEADER_RE.match(line):
            return "gantt"
        if MINDMAP_HEADER_RE.match(line):
            return "mindmap"
        if TIMELINE_HEADER_RE.match(line):
            return "timeline"
        if C4_HEADER_RE.match(line):
            return "c4"
        return "flowchart"
    return "flowchart"


def _is_sequence_diagram(text):
    return _diagram_kind(text) == "sequence"


def parse_mermaid_sequence(text):
    """Mermaid sequenceDiagram text -> (participants, order, messages, fragments, notes)."""
    participants, order = {}, []
    messages, fragments, notes = [], [], []
    frag_stack = []
    pending_deactivate = set()

    def ensure(pid, label=None, kind="system"):
        if pid not in participants:
            participants[pid] = {"label": label or pid, "kind": kind}
            order.append(pid)
        else:
            if label:
                participants[pid]["label"] = label
            if kind == "actor":
                participants[pid]["kind"] = "actor"

    def snap_fragment(frag):
        """Snap a fragment's [start, end) bounds to real (non-note) messages."""
        a = frag["start"]
        b = len(messages) - 1
        while a <= b and messages[a]["kind"] == "note":
            a += 1
        while b >= a and messages[b]["kind"] == "note":
            b -= 1
        if a > b:
            return None
        dividers = []
        for d in frag["dividers"]:
            at = d["at"]
            while at <= b and at < len(messages) and messages[at]["kind"] == "note":
                at += 1
            if a < at <= b:
                dividers.append({"at": at, "label": d["label"]})
        out = {"kind": frag["kind"], "label": frag["label"], "range": [a, b]}
        if dividers:
            out["dividers"] = dividers
        return out

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip().rstrip(";").strip()
        if not line:
            continue
        if SEQ_HEADER_RE.match(line):
            continue
        decl = SEQ_DECL_RE.match(line)
        if decl:
            ensure(decl.group(2), _clean_label(decl.group(3)), decl.group(1).lower())
            continue
        msg = SEQ_MSG_RE.match(line)
        if msg:
            frm, arrow, to, label = msg.group(1), msg.group(2), msg.group(3), _clean_label(msg.group(4))
            ensure(frm)
            ensure(to)
            entry = {"from": frm, "to": to, "kind": SEQ_ARROW_KINDS[arrow]}
            if label:
                entry["label"] = label
            if arrow in ("->",):
                notes.append(f"plain line '{frm}{arrow}{to}' drawn with an open arrowhead")
            if arrow in ("-x", "--x"):
                notes.append(f"lost-message marker '{frm}{arrow}{to}' simplified to a sync arrow")
            if frm in pending_deactivate:
                entry["deactivate"] = True
                pending_deactivate.discard(frm)
            messages.append(entry)
            continue
        note = SEQ_NOTE_RE.match(line)
        if note:
            first, second, text = note.group(2), note.group(3), _clean_label(note.group(4))
            ensure(first)
            targets = [first]
            if second:
                ensure(second)
                targets.append(second)
            messages.append({"kind": "note", "target": targets if len(targets) > 1 else targets[0],
                             "text": text})
            continue
        frag = SEQ_FRAG_RE.match(line)
        if frag and not SEQ_ELSE_RE.match(line):
            frag_stack.append({"kind": frag.group(1).lower(), "label": _clean_label(frag.group(2)),
                               "start": len(messages), "dividers": []})
            continue
        else_branch = SEQ_ELSE_RE.match(line)
        if else_branch:
            if frag_stack and frag_stack[-1]["kind"] == "alt":
                frag_stack[-1]["dividers"].append({"at": len(messages),
                                                   "label": _clean_label(else_branch.group(1))})
            else:
                notes.append(f"else without an open alt fragment: {line}")
            continue
        if SEQ_END_RE.match(line):
            if frag_stack:
                snapped = snap_fragment(frag_stack.pop())
                if snapped:
                    fragments.append(snapped)
                else:
                    notes.append("empty combined fragment dropped")
            else:
                notes.append(f"end without an open fragment: {line}")
            continue
        act = SEQ_ACT_RE.match(line)
        if act:
            pid = act.group(2)
            if act.group(1).lower() == "activate":
                for past in reversed(messages):
                    if past.get("to") == pid and past.get("kind") in ("sync", "async"):
                        past["activate"] = True
                        break
                else:
                    notes.append(f"activate {pid}: no earlier message targets it; ignored")
            else:
                pending_deactivate.add(pid)
            continue
        if re.match(r"^\s*autonumber\b", line, re.IGNORECASE):
            notes.append("autonumber ignored; messages render in declaration order")
            continue
        if SEQ_SKIP_RE.match(line):
            notes.append(f"unsupported block skipped: {line}")
            continue
        notes.append(f"skipped line: {line}")

    for frag in frag_stack:
        notes.append(f"unclosed {frag['kind']} fragment dropped (missing 'end')")
    for pid in pending_deactivate:
        notes.append(f"deactivate {pid}: no later message from it; ignored")
    return participants, order, messages, fragments, notes


def _sequence_to_spec(text, title=None, style="slate", animation="flow"):
    participants, order, messages, fragments, notes = parse_mermaid_sequence(text)
    if not any(m.get("kind") != "note" for m in messages):
        raise SystemExit("no sequence messages parsed; is this a Mermaid sequenceDiagram document?")
    spec = {
        "layout": "sequence",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "sequence", "subtitle": "from Mermaid"},
        "participants": [
            {"id": pid, "label": participants[pid]["label"],
             **({"kind": "actor"} if participants[pid]["kind"] == "actor" else {})}
            for pid in order
        ],
        "messages": messages,
    }
    if fragments:
        spec["fragments"] = fragments
    return spec, notes


# ---------------------------------------------------------------------------
# erDiagram import
# ---------------------------------------------------------------------------

ER_REL_RE = re.compile(
    r"^\s*([A-Za-z0-9_一-鿿]\w*)\s+"
    r"(\|\||\|o|o\||\}\||\}o)\s*--\s*(\|\||o\||\|\{|o\{)\s+"
    r"([A-Za-z0-9_一-鿿]\w*)\s*:\s*(.+)$")
ER_BLOCK_RE = re.compile(r"^\s*([A-Za-z0-9_一-鿿]\w*)\s*\{\s*$")
ER_ATTR_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s+([A-Za-z0-9_一-鿿][\w]*)(?:\s+(PK|FK|UK))?(?:\s+".*")?\s*$',
                        re.IGNORECASE)

ER_LEFT_CARDS = {"||": "1", "|o": "0..1", "}|": "1..*", "}o": "0..*"}
ER_RIGHT_CARDS = {"||": "1", "o|": "0..1", "|{": "1..*", "o{": "0..*"}


def parse_mermaid_er(text):
    """Mermaid erDiagram text -> (entities dict, order, relations, notes)."""
    entities, order, relations, notes = {}, [], [], []
    block = None
    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line or ER_HEADER_RE.match(line):
            continue
        if block is not None:
            if line.startswith("}"):
                block = None
                continue
            attr = ER_ATTR_RE.match(line)
            if attr:
                key = (attr.group(3) or "").lower()
                entities[block]["attributes"].append(
                    {"name": attr.group(2), "type": attr.group(1),
                     **({"key": key} if key in ("pk", "fk") else {})})
            else:
                notes.append(f"skipped attribute line: {line}")
            continue
        open_block = ER_BLOCK_RE.match(line)
        if open_block:
            block = open_block.group(1)
            if block not in entities:
                entities[block] = {"attributes": []}
                order.append(block)
            continue
        rel = ER_REL_RE.match(line)
        if rel:
            a, lc, rc, b, label = rel.groups()
            for eid in (a, b):
                if eid not in entities:
                    entities[eid] = {"attributes": []}
                    order.append(eid)
            relations.append({"from": a, "to": b, "label": _clean_label(label),
                              "from_card": ER_LEFT_CARDS[lc], "to_card": ER_RIGHT_CARDS[rc]})
            continue
        notes.append(f"skipped line: {line}")
    return entities, order, relations, notes


def _er_to_spec(text, title=None, style="slate", animation="flow"):
    entities, order, relations, notes = parse_mermaid_er(text)
    if not relations:
        raise SystemExit("no ER relations parsed; is this a Mermaid erDiagram document?")
    spec = {
        "layout": "er",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "ER diagram", "subtitle": "from Mermaid"},
        "entities": [{"id": eid, "label": eid, "attributes": entities[eid]["attributes"]} for eid in order],
        "relations": relations,
    }
    return spec, notes


# ---------------------------------------------------------------------------
# classDiagram import
# ---------------------------------------------------------------------------

CLASS_DECL_RE = re.compile(r"^\s*class\s+([A-Za-z0-9_一-鿿]\w*)(?:\s*~\w+~)?\s*(\{)?\s*$", re.IGNORECASE)
CLASS_STEREO_RE = re.compile(r"^\s*<<\s*(\w+)\s*>>\s*$")
# A <|-- B : B inherits A.  A *-- B : A is the composite.  Quoted cards allowed.
CLASS_REL_RE = re.compile(
    r'^\s*([A-Za-z0-9_一-鿿]\w*)\s*(?:"([^"]*)")?\s*'
    r"(<\|--|<\|\.\.|\*--|o--|--\|>|\.\.\|>|--\*|--o|-->|\.\.>|<--|<\.\.|--)\s*"
    r'(?:"([^"]*)")?\s*([A-Za-z0-9_一-鿿]\w*)\s*(?::\s*(.+))?$')

# (token, reversed) -> (kind, from_is_a)
CLASS_REL_KINDS = {
    ("<|--", False): "inheritance", ("--|>", False): "inheritance",
    ("<|..", False): "realization", ("..|>", False): "realization",
    ("*--", False): "composition", ("--*", False): "composition",
    ("o--", False): "aggregation", ("--o", False): "aggregation",
    ("-->", False): "association", ("<--", False): "association",
    ("..>", False): "dependency", ("<..", False): "dependency",
    ("--", False): "association",
}
# Whether the marker end is the FIRST id (e.g. "A <|-- B": triangle at A).
CLASS_MARKER_AT_A = {"<|--", "<|..", "*--", "o--", "<--", "<.."}
CLASS_DIAMOND_KINDS = ("composition", "aggregation")


def _class_member(line):
    """One class-block line -> member dict, or None."""
    line = line.strip().rstrip("$")  # $ = static marker
    if not line:
        return None
    vis = line[0] if line[0] in "+-#~" else "+"
    if line[0] in "+-#~":
        line = line[1:].strip()
    if "(" in line:
        head, _, tail = line.partition(")")
        member = {"name": head + ")", "visibility": vis}
        if tail.strip():
            member["type"] = tail.strip().split()[0]
        return member
    parts = line.split()
    if len(parts) >= 2:  # Mermaid block style is "type name"
        return {"name": parts[1], "type": parts[0], "visibility": vis}
    return {"name": parts[0], "visibility": vis}


def parse_mermaid_class(text):
    """Mermaid classDiagram text -> (classes dict, order, relations, notes)."""
    classes, order, relations, notes = {}, [], [], []
    block = None

    def ensure(cid):
        if cid not in classes:
            classes[cid] = {"kind": "class", "attributes": [], "methods": []}
            order.append(cid)

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line or CLASS_HEADER_RE.match(line):
            continue
        if block is not None:
            if line.startswith("}"):
                block = None
                continue
            stereo = CLASS_STEREO_RE.match(line)
            if stereo:
                kind = stereo.group(1).lower()
                classes[block]["kind"] = {"interface": "interface", "enumeration": "enum", "enum": "enum",
                                          "abstract": "abstract"}.get(kind, "class")
                continue
            member = _class_member(line)
            if member:
                if "(" in member["name"]:
                    classes[block]["methods"].append(member)
                else:
                    classes[block]["attributes"].append(member)
            continue
        decl = CLASS_DECL_RE.match(line)
        if decl:
            ensure(decl.group(1))
            if decl.group(2):
                block = decl.group(1)
            continue
        rel = CLASS_REL_RE.match(line)
        if rel:
            a, card_a, token, card_b, b, label = rel.groups()
            kind = CLASS_REL_KINDS.get((token, False), "association")
            if kind in ("inheritance", "realization"):
                # Triangle sits at the parent/interface end.
                frm, to = (b, a) if token in CLASS_MARKER_AT_A else (a, b)
                entry = {"from": frm, "to": to, "kind": kind}
            elif kind in CLASS_DIAMOND_KINDS:
                # Diamond sits at the composite/aggregate end.
                frm, to = (a, b) if token in CLASS_MARKER_AT_A else (b, a)
                entry = {"from": frm, "to": to, "kind": kind}
                if card_a:
                    entry["from_card" if token in CLASS_MARKER_AT_A else "to_card"] = card_a
                if card_b:
                    entry["to_card" if token in CLASS_MARKER_AT_A else "from_card"] = card_b
            else:
                frm, to = (a, b) if token not in ("<--", "<..") else (b, a)
                entry = {"from": frm, "to": to, "kind": kind}
            ensure(entry["from"])
            ensure(entry["to"])
            if label:
                entry["label"] = _clean_label(label)
            relations.append(entry)
            continue
        if re.match(r"^\s*(note|namespace|annotation|direction)\b", line, re.IGNORECASE):
            notes.append(f"skipped line: {line}")
            continue
        notes.append(f"skipped line: {line}")
    return classes, order, relations, notes


def _class_to_spec(text, title=None, style="slate", animation="flow"):
    classes, order, relations, notes = parse_mermaid_class(text)
    if not relations and not order:
        raise SystemExit("no classes parsed; is this a Mermaid classDiagram document?")
    spec = {
        "layout": "class",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "class diagram", "subtitle": "from Mermaid"},
        "classes": [
            {"id": cid, "label": cid,
             **({"kind": classes[cid]["kind"]} if classes[cid]["kind"] != "class" else {}),
             "attributes": classes[cid]["attributes"], "methods": classes[cid]["methods"]}
            for cid in order
        ],
        "relations": relations,
    }
    return spec, notes



# ---------------------------------------------------------------------------
# stateDiagram import
# ---------------------------------------------------------------------------

STATE_HEADER_RE = re.compile(r"^\s*stateDiagram(-v2)?\s*$", re.IGNORECASE)
STATE_TRANS_RE = re.compile(
    rf"^\s*(\[\*\]|[A-Za-z0-9_一-鿿][\w.]*)\s*-->\s*(\[\*\]|[A-Za-z0-9_一-鿿][\w.]*)\s*(?::\s*(.+))?$")
STATE_ALIAS_RE = re.compile(r'^\s*state\s+"?([^"]+?)"?\s+as\s+([A-Za-z0-9_一-鿿]\w*)\s*$', re.IGNORECASE)
STATE_DESCR_RE = re.compile(rf"^\s*([A-Za-z0-9_一-鿿][\w.]*)\s*:\s*(.+)$")


def parse_mermaid_state(text):
    """Mermaid stateDiagram text -> (states dict, order, transitions, notes).

    Supported: transitions with labels, [*] initial/final, ``state Label as id``
    aliases, ``id : description`` body lines. Composite ``state X { ... }``
    blocks are flattened (inner transitions kept, nesting noted).
    """
    states, order, transitions, notes = {}, [], [], []
    depth = 0

    def ensure(sid, label=None):
        if sid not in states:
            states[sid] = {"label": label or sid, "kind": "state", "body": ""}
            order.append(sid)
        elif label:
            states[sid]["label"] = label

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line or STATE_HEADER_RE.match(line):
            continue
        if re.match(r"^\s*state\s+\S+\s*\{\s*$", line):
            depth += 1
            notes.append("composite state flattened: inner transitions kept at top level")
            continue
        if line == "}" and depth:
            depth -= 1
            continue
        trans = STATE_TRANS_RE.match(line)
        if trans:
            frm, to, label = trans.group(1), trans.group(2), _clean_label(trans.group(3))
            entry = {}
            if frm == "[*]":
                frm = "_initial"
                entry["from_kind"] = "initial"
            if to == "[*]":
                to = "_final"
                entry["to_kind"] = "final"
            ensure(frm)
            ensure(to)
            if entry.get("from_kind"):
                states[frm]["kind"] = "initial"
                states[frm]["label"] = ""
            if entry.get("to_kind"):
                states[to]["kind"] = "final"
                states[to]["label"] = ""
            out = {"from": frm, "to": to}
            if label:
                out["label"] = label
            transitions.append(out)
            continue
        alias = STATE_ALIAS_RE.match(line)
        if alias:
            ensure(alias.group(2), _clean_label(alias.group(1)))
            continue
        descr = STATE_DESCR_RE.match(line)
        if descr and descr.group(1) in states:
            body = states[descr.group(1)]["body"]
            states[descr.group(1)]["body"] = (body + "\n" + descr.group(2).strip()).strip("\n")
            continue
        if re.match(r"^\s*(direction|note|scale)\b", line, re.IGNORECASE):
            notes.append(f"skipped line: {line}")
            continue
        notes.append(f"skipped line: {line}")
    return states, order, transitions, notes


def _state_to_spec(text, title=None, style="slate", animation="flow"):
    states, order, transitions, notes = parse_mermaid_state(text)
    if not transitions:
        raise SystemExit("no state transitions parsed; is this a Mermaid stateDiagram document?")
    spec = {
        "layout": "state",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "state machine", "subtitle": "from Mermaid"},
        "states": [
            {"id": sid, **({"kind": states[sid]["kind"]} if states[sid]["kind"] != "state" else {}),
             **({"label": states[sid]["label"]} if states[sid]["label"] else {}),
             **({"body": states[sid]["body"]} if states[sid]["body"] else {})}
            for sid in order
        ],
        "transitions": transitions,
    }
    return spec, notes



# ---------------------------------------------------------------------------
# gantt import
# ---------------------------------------------------------------------------

GANTT_HEADER_RE = re.compile(r"^\s*gantt\s*$", re.IGNORECASE)
GANTT_SECTION_RE = re.compile(r"^\s*section\s+(.+)$", re.IGNORECASE)
GANTT_TASK_RE = re.compile(r"^\s*(.+?)\s*:\s*(.+)$")
GANTT_SKIP_RE = re.compile(r"^\s*(title|dateFormat|axisFormat|tickInterval|excludes|todayMarker|"
                           r"weekends|inclusiveEndDates|topAxis|displayMode)\b", re.IGNORECASE)
GANTT_KIND_TAGS = {"done", "active", "crit", "milestone"}


def _gantt_iso(value):
    """'YYYY-MM-DD' (or datetime) -> ISO date string, else None."""
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else None


def parse_mermaid_gantt(text):
    """Mermaid gantt text -> (sections, notes).

    Task line: ``Label :tag, id, start, end-or-duration``. Tags done/active/
    crit/milestone map to bar kinds. ``after <id>`` resolves to that task's
    end date. Undated tasks chain after the previous task in the section.
    """
    from datetime import date as _date, timedelta as _delta
    sections, notes = [], []
    current = None
    last_end = {}   # task id -> end date
    prev_id = None

    def default_section():
        nonlocal current
        if current is None:
            current = {"label": "", "tasks": []}
            sections.append(current)
        return current

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].rstrip()
        if not line.strip() or GANTT_HEADER_RE.match(line):
            continue
        if GANTT_SKIP_RE.match(line):
            continue
        sec = GANTT_SECTION_RE.match(line)
        if sec:
            current = {"label": sec.group(1).strip(), "tasks": []}
            sections.append(current)
            prev_id = None
            continue
        task = GANTT_TASK_RE.match(line)
        if task:
            sec_obj = default_section()
            label = _clean_label(task.group(1))
            parts = [p.strip() for p in task.group(2).split(",")]
            kind = "task"
            tid = None
            start_raw, end_raw = None, None
            for p in parts:
                low = p.lower()
                if low in GANTT_KIND_TAGS:
                    kind = low
                elif re.match(r"^[A-Za-z]\w*$", p) and tid is None and start_raw is None:
                    tid = p
                elif start_raw is None:
                    start_raw = p
                else:
                    end_raw = p
            start = _gantt_iso(start_raw)
            if start is None and start_raw and start_raw.lower().startswith("after"):
                ref = start_raw.split(None, 1)[1].strip() if len(start_raw.split(None, 1)) > 1 else ""
                ref_end = last_end.get(ref)
                if ref_end:
                    start = ref_end
                else:
                    notes.append(f"task '{label}': unknown 'after' reference '{ref}'; chained to previous")
                    start = last_end.get(prev_id) or "2026-01-01"
            if start is None:
                start = last_end.get(prev_id) or "2026-01-01"
                if not parts or start_raw is None:
                    notes.append(f"task '{label}': no start date; chained after previous task")
            end = _gantt_iso(end_raw)
            out = {"label": label, "start": start, "kind": kind}
            if end:
                out["end"] = end
            else:
                dur_m = re.match(r"^(\d+)\s*([dhw])?$", str(end_raw or ""))
                days = {"d": 1, "w": 7, "h": 1}.get(dur_m.group(2) if dur_m else "d", 1)
                n = int(dur_m.group(1)) if dur_m else (0 if kind == "milestone" else 3)
                if kind == "milestone":
                    n = 0
                d0 = _date.fromisoformat(start)
                out["end"] = (d0 + _delta(days=max(1, n))).isoformat()
                if kind == "milestone":
                    out.pop("end")
            sec_obj["tasks"].append(out)
            d_start = _date.fromisoformat(start)
            last_end[tid or f"_{len(last_end)}"] = out.get("end") or d_start.isoformat()
            prev_id = tid or f"_{len(last_end) - 1}"
            if tid:
                last_end[tid] = out.get("end") or d_start.isoformat()
            prev_id = tid or prev_id
            continue
        notes.append(f"skipped line: {line.strip()}")
    return sections, notes


def _gantt_to_spec(text, title=None, style="slate", animation="flow"):
    sections, notes = parse_mermaid_gantt(text)
    if not any(s["tasks"] for s in sections):
        raise SystemExit("no gantt tasks parsed; is this a Mermaid gantt document?")
    spec = {
        "layout": "gantt",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "gantt chart", "subtitle": "from Mermaid"},
        "sections": sections,
    }
    return spec, notes


# ---------------------------------------------------------------------------
# mindmap import
# ---------------------------------------------------------------------------

MINDMAP_HEADER_RE = re.compile(r"^\s*mindmap\s*$", re.IGNORECASE)
MINDMAP_NODE_RES = [
    re.compile(r"^\(\((.+)\)\)$"), re.compile(r"^\(\(.+\)\)$"),
    re.compile(r"^\[\[(.+)\]\]$"), re.compile(r"^\[\((.+)\)\]$"),
    re.compile(r"^\(\((.+)\)\)$"), re.compile(r"^\((.+)\)$"),
    re.compile(r"^\[(.+)\]$"), re.compile(r"^\{\{(.+)\}\}$"),
    re.compile(r"^\)\)(.+)\(\($"),
]
MINDMAP_ID_RE = re.compile(r"^([A-Za-z]\w*)[\[\(\{]")


def _mindmap_label(token):
    token = token.strip()
    for rx in MINDMAP_NODE_RES:
        m = rx.match(token)
        if m:
            return m.group(1).strip()
    m = MINDMAP_ID_RE.match(token)
    if m:
        rest = token[len(m.group(1)):].strip("[](){}")
        return rest.strip() or m.group(1)
    return token


def parse_mermaid_mindmap(text):
    """Mermaid mindmap text -> (root dict, notes). Indentation = nesting."""
    root, notes = None, []
    stack = []  # (indent, node-dict-with-children)
    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].rstrip()
        if not line.strip() or MINDMAP_HEADER_RE.match(line):
            continue
        indent = len(line) - len(line.lstrip())
        label = _mindmap_label(line.strip())
        if not label:
            continue
        node = {"label": label, "children": []}
        if root is None:
            root = node
            stack = [(indent, node)]
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            notes.append(f"detached branch '{label}' attached to root")
            root["children"].append(node)
        stack.append((indent, node))
    return root, notes


def _mindmap_prune(node, depth=0):
    """Spec supports root -> topics (10) -> leaves (5)."""
    out = {"label": node["label"]}
    kids = node.get("children") or []
    if depth == 0:
        kids = kids[:10]
    elif depth == 1:
        kids = kids[:5]
    else:
        kids = []
    if kids:
        out["children"] = [_mindmap_prune(k, depth + 1) for k in kids]
    return out


def _mindmap_to_spec(text, title=None, style="slate", animation="flow"):
    root, notes = parse_mermaid_mindmap(text)
    if root is None or not root.get("children"):
        raise SystemExit("no mindmap branches parsed; is this a Mermaid mindmap document?")
    spec = {
        "layout": "mindmap",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "mindmap", "subtitle": "from Mermaid"},
        "root": _mindmap_prune(root),
    }
    return spec, notes


# ---------------------------------------------------------------------------
# timeline import
# ---------------------------------------------------------------------------

TIMELINE_HEADER_RE = re.compile(r"^\s*timeline\s*$", re.IGNORECASE)
TIMELINE_EVENT_RE = re.compile(r"^\s*(.+?)\s*:\s*(.+)$")
TIMELINE_SKIP_RE = re.compile(r"^\s*(title|section)\b", re.IGNORECASE)


def parse_mermaid_timeline(text):
    """Mermaid timeline text -> (events, notes).

    ``period : event`` or ``period : event1 : event2`` — each event becomes
    one entry sharing the period label as its time.
    """
    events, notes = [], []
    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line or TIMELINE_HEADER_RE.match(line):
            continue
        if TIMELINE_SKIP_RE.match(line):
            continue
        m = TIMELINE_EVENT_RE.match(line)
        if m:
            period = _clean_label(m.group(1))
            for part in m.group(2).split(":"):
                label = _clean_label(part)
                if label:
                    events.append({"label": label, "time": period})
            continue
        notes.append(f"skipped line: {line}")
    return events, notes


def _timeline_to_spec(text, title=None, style="slate", animation="flow"):
    events, notes = parse_mermaid_timeline(text)
    if not events:
        raise SystemExit("no timeline events parsed; is this a Mermaid timeline document?")
    spec = {
        "layout": "timeline",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "timeline", "subtitle": "from Mermaid"},
        "events": events[:12],
    }
    if len(events) > 12:
        notes.append(f"only the first 12 of {len(events)} events render")
    return spec, notes


# ---------------------------------------------------------------------------
# C4 import (C4Context / C4Container subset)
# ---------------------------------------------------------------------------

C4_HEADER_RE = re.compile(r"^\s*C4(Context|Container|Component|Deployment)\s*$")
C4_ELEM_RE = re.compile(
    r"^\s*(Person|Person_Ext|System|System_Ext|Container|ContainerDb|ContainerQueue|"
    r"Container_Ext|Component)\s*\(\s*([A-Za-z0-9_]+)\s*(?:,\s*(.*?))?\)\s*$")
C4_BOUNDARY_RE = re.compile(
    r"^\s*(System_Boundary|Container_Boundary|Enterprise_Boundary|Boundary)\s*\(\s*([A-Za-z0-9_]+)\s*"
    r"(?:,\s*(.*?))?\)\s*\{\s*$")
C4_REL_RE = re.compile(
    r"^\s*(Rel|Rel_R|Rel_L|Rel_U|Rel_D|BiRel|Rel_Back)\s*\(\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*"
    r"(?:,\s*(.*?))?\)\s*$")
C4_KIND_MAP = {
    "Person": "person", "Person_Ext": "person",
    "System": "system", "System_Ext": "ext_system",
    "Container": "container", "Container_Ext": "container", "Component": "container",
    "ContainerDb": "database", "ContainerQueue": "queue",
}


def _c4_args(raw):
    """Split a C4 argument tail on commas, stripping quotes and blanks."""
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if len(part) >= 2 and part.startswith('"') and part.endswith('"'):
            part = part[1:-1]
        if part:
            out.append(part)
    return out


def parse_mermaid_c4(text):
    """Mermaid C4 text -> (elements, boundaries, relations, notes)."""
    elements, order = {}, []
    boundaries = []
    relations, notes = [], []
    boundary_stack = []

    def ensure(eid, kind, label="", tech=""):
        if eid not in elements:
            elements[eid] = {"kind": kind, "label": label or eid, "technology": tech, "boundary": ""}
            order.append(eid)
        if boundary_stack and not elements[eid]["boundary"]:
            elements[eid]["boundary"] = boundary_stack[-1]

    for raw_line in text.splitlines():
        line = raw_line.split("%%", 1)[0].strip()
        if not line or C4_HEADER_RE.match(line):
            continue
        if re.match(r"^(title|UpdateLayoutConfig|UpdateRelStyle|Lay_|LAYOUT)\b", line):
            continue
        bound = C4_BOUNDARY_RE.match(line)
        if bound:
            bid = bound.group(2)
            label = (bound.group(3) or "").strip().strip('"')
            boundaries.append({"id": bid, "label": label or bid})
            boundary_stack.append(bid)
            continue
        if line == "}":
            if boundary_stack:
                boundary_stack.pop()
            continue
        elem = C4_ELEM_RE.match(line)
        if elem:
            args = _c4_args(elem.group(3))
            label = args[0] if args else elem.group(2)
            tech = args[1] if len(args) > 1 else ""
            ensure(elem.group(2), C4_KIND_MAP.get(elem.group(1), "system"), label, tech)
            continue
        rel = C4_REL_RE.match(line)
        if rel:
            args = _c4_args(rel.group(4))
            out = {"from": rel.group(2), "to": rel.group(3)}
            if args:
                out["label"] = args[0]
            if len(args) > 1:
                out["technology"] = args[1]
            relations.append(out)
            continue
        notes.append(f"skipped line: {line}")
    return elements, order, boundaries, relations, notes


def _c4_to_spec(text, title=None, style="slate", animation="flow"):
    elements, order, boundaries, relations, notes = parse_mermaid_c4(text)
    if not elements:
        raise SystemExit("no C4 elements parsed; is this a Mermaid C4Context/C4Container document?")
    spec = {
        "layout": "c4",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "C4 diagram", "subtitle": "from Mermaid"},
        "elements": [
            {"id": eid, "label": elements[eid]["label"], "kind": elements[eid]["kind"],
             **({"technology": elements[eid]["technology"]} if elements[eid]["technology"] else {}),
             **({"boundary": elements[eid]["boundary"]} if elements[eid]["boundary"] else {})}
            for eid in order
        ],
        "relations": relations,
    }
    if boundaries:
        spec["boundaries"] = boundaries
    return spec, notes


def _count_tree(node):
    """Total node count of a nested mindmap tree."""
    if not isinstance(node, dict):
        return 0
    return 1 + sum(_count_tree(child) for child in node.get("children", []))


def _check_resource_limits(spec):
    """Post-parse caps across all per-layout spec shapes."""
    node_keys = ("nodes", "participants", "entities", "classes", "states", "elements", "events")
    edge_keys = ("edges", "messages", "relations", "transitions", "links", "flows", "connections")
    nodes = sum(len(spec[key]) for key in node_keys if isinstance(spec.get(key), list))
    edges = sum(len(spec[key]) for key in edge_keys if isinstance(spec.get(key), list))
    if isinstance(spec.get("sections"), list):  # gantt
        nodes += sum(len(s.get("tasks", [])) for s in spec["sections"] if isinstance(s, dict))
    if isinstance(spec.get("root"), dict):  # mindmap
        nodes += _count_tree(spec["root"])
    if nodes > MAX_NODES:
        _fail(2, f"resource_limit:nodes — imported diagram has {nodes} elements (max {MAX_NODES}); simplify or split the source")
    if edges > MAX_EDGES:
        _fail(2, f"resource_limit:edges — imported diagram has {edges} relations/messages (max {MAX_EDGES}); simplify or split the source")


def _check_string_lengths(value):
    """Any string landing in the spec stays under the label cap, whatever
    layout produced it (belt and suspenders behind _clean_label)."""
    if isinstance(value, str):
        if len(value) > MAX_LABEL_CHARS:
            _fail(2, f"resource_limit:label_chars — a field is {len(value)} chars (max {MAX_LABEL_CHARS})")
    elif isinstance(value, dict):
        for item in value.values():
            _check_string_lengths(item)
    elif isinstance(value, list):
        for item in value:
            _check_string_lengths(item)


def to_spec(text, title=None, style="slate", animation="flow", detail="faithful", audience="engineer"):
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        _fail(2, f"resource_limit:source_bytes — source exceeds {MAX_SOURCE_BYTES} bytes; split the document")
    kind = _diagram_kind(text)
    if kind == "sequence":
        spec, notes = _sequence_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "er":
        spec, notes = _er_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "class":
        spec, notes = _class_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "state":
        spec, notes = _state_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "gantt":
        spec, notes = _gantt_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "mindmap":
        spec, notes = _mindmap_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "timeline":
        spec, notes = _timeline_to_spec(text, title=title, style=style, animation=animation)
    elif kind == "c4":
        spec, notes = _c4_to_spec(text, title=title, style=style, animation=animation)
    else:
        spec, notes = _flowchart_to_spec(text, title=title, style=style, animation=animation)
    _check_resource_limits(spec)
    _check_string_lengths(spec)
    if detail != "faithful" or audience != "engineer":
        spec, ledger = import_refine.apply_dials(spec, detail=detail, audience=audience)
        notes = [*notes, *import_refine.format_ledger(ledger)]
    return spec, notes


def _flowchart_to_spec(text, title=None, style="slate", animation="flow"):
    direction, nodes, order, edges, notes, groups, parents, class_roles = parse_mermaid(text)
    if not nodes or not edges:
        raise SystemExit("no flowchart parsed (need at least one edge); is this a Mermaid flowchart/graph document?")
    spec_nodes = []
    for nid in order:
        info = nodes[nid]
        node = {"id": nid, "label": info["label"]}
        if info["kind"] != "card":
            node["kind"] = info["kind"]
        if nid in parents:
            node["parent"] = parents[nid]
        if nid in class_roles:
            # Route Mermaid class memberships to a DiagramForge accent role
            # when the class name matches a known role (green/amber/pink/...).
            role = class_roles[nid].lower()
            if role in ("green", "amber", "pink", "cyan", "purple", "muted"):
                node["accent"] = role
        spec_nodes.append(node)
    spec = {
        "layout": "graph",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "flowchart", "subtitle": "from Mermaid"},
        "direction": direction,
        "nodes": spec_nodes,
        "edges": edges,
    }
    if groups:
        spec["groups"] = groups
    return spec, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Mermaid file path, or '-' for stdin.")
    parser.add_argument("--out", default=None, help="Write spec JSON here (default: stdout).")
    parser.add_argument("--title", default=None, help="Title prefix for the imported diagram.")
    parser.add_argument("--style", choices=["slate", "report", "academic", "blueprint", "custom"], default="slate")
    parser.add_argument("--animation", default="flow",
                        help="Animation preset (default flow).")
    parser.add_argument("--detail", choices=import_refine.DETAIL_CHOICES, default="faithful",
                        help="How much of the source survives: faithful (<=24 nodes), balanced (<=12), "
                             "simplified (<=7). Reduction follows a fixed degrade ladder and is reported "
                             "in the fidelity ledger.")
    parser.add_argument("--audience", choices=import_refine.AUDIENCE_CHOICES, default="engineer",
                        help="Wording, not count: engineer keeps technical sublabels, mixed strips "
                             "ports/schemes, executive drops protocol jargon and caps label length.")
    parser.add_argument("--size", choices=["article", "wide", "square", "story"], default=None,
                        help="Canvas preset for the output (maps to spec canvas.preset).")
    args = parser.parse_args()

    text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    spec, notes = to_spec(text, title=args.title, style=args.style, animation=args.animation,
                          detail=args.detail, audience=args.audience)
    if args.size:
        spec.setdefault("canvas", {})["preset"] = args.size
    payload = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        if spec["layout"] == "sequence":
            summary = {"participants": len(spec["participants"]), "messages": len(spec["messages"])}
        elif spec["layout"] == "er":
            summary = {"entities": len(spec["entities"]), "relations": len(spec["relations"])}
        elif spec["layout"] == "class":
            summary = {"classes": len(spec["classes"]), "relations": len(spec["relations"])}
        elif spec["layout"] == "state":
            summary = {"states": len(spec["states"]), "transitions": len(spec["transitions"])}
        elif spec["layout"] == "gantt":
            summary = {"sections": len(spec["sections"]),
                       "tasks": sum(len(s["tasks"]) for s in spec["sections"])}
        elif spec["layout"] == "mindmap":
            summary = {"topics": len(spec["root"].get("children", []))}
        elif spec["layout"] == "timeline":
            summary = {"events": len(spec["events"])}
        elif spec["layout"] == "c4":
            summary = {"elements": len(spec["elements"]), "relations": len(spec["relations"])}
        else:
            summary = {"nodes": len(spec["nodes"]), "edges": len(spec["edges"])}
        print(json.dumps({"ok": True, "out": args.out, "layout": spec["layout"], **summary,
                          "notes": notes}, ensure_ascii=False, indent=2))
    else:
        print(payload)
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
