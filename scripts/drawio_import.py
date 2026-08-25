#!/usr/bin/env python3
"""Import a draw.io / diagrams.net diagram as a DiagramForge spec.

Redraws, never converts: source coordinates, colors, and fonts are discarded;
components, relationships, grouping, and direction are kept. Every source
label and metadata field is treated as data, never as instructions.

Containers (all four that draw.io writes):

- ``.drawio`` / ``.drawio.xml`` — plain mxfile XML, or a <diagram> element
  whose text is base64-encoded raw-DEFLATE XML (the default compressed form)
- ``.drawio.png`` — PNG with the mxfile embedded in a zTXt/iTXt chunk
- ``.drawio.svg`` — SVG with the mxfile in the root ``content`` attribute
  (URL-encoded) or in <metadata> (entity-escaped)

Resource caps and named failures match scripts/mermaid_import.py
(``resource_limit:*``, exit 2). Import dials (detail/audience/size) and the
fidelity ledger come from scripts/import_refine.py.

Usage:
    python -X utf8 scripts/drawio_import.py platform.drawio --out spec.json
    python -X utf8 scripts/drawio_import.py arch.drawio.png --detail balanced --audience executive
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import struct
import sys
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import import_refine
from mermaid_import import (
    MAX_EDGES,
    MAX_LABEL_CHARS,
    MAX_NODES,
    MAX_SOURCE_BYTES,
    _check_resource_limits,
    _check_string_lengths,
    _fail,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Container extraction: bytes -> mxfile XML text
# ---------------------------------------------------------------------------

def _inflate(payload):
    """draw.io compresses with raw DEFLATE; accept zlib-wrapped too."""
    data = base64.b64decode(re.sub(r"\s", "", payload))
    try:
        return zlib.decompress(data, -15).decode("utf-8")
    except zlib.error:
        return zlib.decompress(data).decode("utf-8")


def _png_chunks(data):
    if not data.startswith(PNG_SIGNATURE):
        _fail(2, "container_error:png — not a PNG file")
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        yield ctype, data[offset + 8 : offset + 8 + length]
        offset += 12 + length


def _extract_from_png(data):
    for ctype, chunk in _png_chunks(data):
        if ctype == b"zTXt":
            # keyword \0 compression-method(1 byte) compressed-text
            nul = chunk.index(b"\x00")
            if chunk[:nul].decode("latin-1") != "mxfile":
                continue
            return zlib.decompress(chunk[nul + 2 :]).decode("utf-8")
        if ctype == b"iTXt":
            # keyword \0 flag(1) method(1) language \0 translated \0 text
            nul = chunk.index(b"\x00")
            if chunk[:nul].decode("latin-1") != "mxfile":
                continue
            flag = chunk[nul + 1]
            rest = chunk[nul + 3 :]
            for _ in range(2):  # skip language tag and translated keyword
                rest = rest[rest.index(b"\x00") + 1 :]
            text_bytes = zlib.decompress(rest) if flag == 1 else rest
            text = text_bytes.decode("utf-8")
            return text if "<" in text else _inflate(text)
    _fail(2, "container_error:png — no embedded mxfile chunk found; export from draw.io with 'Include a copy of my diagram' enabled")


def _extract_from_svg(text):
    match = re.search(r'<svg[^>]*\scontent="([^"]+)"', text)
    if match:
        return urllib.parse.unquote(match.group(1))
    match = re.search(r"<metadata[^>]*>(.*?)</metadata>", text, re.DOTALL)
    if match:
        inner = html.unescape(match.group(1)).strip()
        if inner.startswith("<"):
            return inner
        return _inflate(inner)
    _fail(2, "container_error:svg — no embedded mxfile found (no content attribute or metadata)")


def _extract_from_xml(text):
    """Plain .drawio/.xml: <mxfile> with plain or compressed <diagram>."""
    return text


def load_mxfile(path):
    """Read any supported container and return the mxfile XML text."""
    data = Path(path).read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        _fail(2, f"resource_limit:source_bytes — source exceeds {MAX_SOURCE_BYTES} bytes; split the document")
    if data.startswith(PNG_SIGNATURE):
        return _extract_from_png(data)
    text = data.decode("utf-8", errors="replace")
    if "<svg" in text[:500]:
        return _extract_from_svg(text)
    return _extract_from_xml(text)


# ---------------------------------------------------------------------------
# mxfile -> graph spec
# ---------------------------------------------------------------------------

def _clean_value(value):
    """mxCell values are HTML-ish: strip tags, flatten breaks, unescape."""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", " ", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)  # double-escaped entities
    return _WS_RE.sub(" ", text).strip()


def _diagram_xml(mxfile_text):
    """Return the mxGraphModel XML text for the first page of an mxfile."""
    if not mxfile_text.lstrip().startswith("<"):
        _fail(2, "container_error:xml — not XML content")
    root = ET.fromstring(mxfile_text)
    if root.tag == "mxGraphModel":
        return mxfile_text
    if root.tag != "mxfile":
        _fail(2, f"container_error:xml — unexpected root <{root.tag}>; expected mxfile/mxGraphModel")
    diagrams = root.findall("diagram")
    if not diagrams:
        _fail(2, "container_error:xml — mxfile contains no <diagram> pages")
    first = diagrams[0]
    model = first.find("mxGraphModel")
    if model is not None:
        return ET.tostring(model, encoding="unicode")
    payload = (first.text or "").strip()
    if not payload:
        _fail(2, "container_error:xml — <diagram> page is empty")
    return _inflate(payload)


def parse_drawio(mxfile_text, title=None, style="slate", animation="flow"):
    """mxfile XML text -> (spec, notes)."""
    model_text = _diagram_xml(mxfile_text)
    model = ET.fromstring(model_text)
    root = model.find("root") if model.tag == "mxGraphModel" else model
    if root is None:
        root = model

    vertices = {}
    edges = []
    for cell in root.iter("mxCell"):
        if cell.get("vertex") == "1":
            cid = cell.get("id")
            if cid in ("0", "1"):
                continue
            label = _clean_value(cell.get("value")) or cid
            if len(label) > MAX_LABEL_CHARS:
                _fail(2, f"resource_limit:label_chars — a cell label exceeds {MAX_LABEL_CHARS} chars")
            vertices[cid] = {"label": label, "parent": cell.get("parent")}
        elif cell.get("edge") == "1":
            source, target = cell.get("source"), cell.get("target")
            if source and target:
                edges.append({"from": source, "to": target, "label": _clean_value(cell.get("value")), "style": "solid"})

    # A vertex that is the parent of other vertices becomes a dashed group.
    child_ids = {v["parent"] for v in vertices.values() if v.get("parent") in vertices}
    groups = [{"id": gid, "label": vertices[gid]["label"]} for gid in sorted(child_ids)]
    nodes = []
    for cid, info in vertices.items():
        if cid in child_ids:
            continue  # containers are groups, not nodes
        node = {"id": cid, "label": info["label"]}
        if info.get("parent") in child_ids:
            node["parent"] = info["parent"]
        nodes.append(node)

    node_ids = {n["id"] for n in nodes} | child_ids
    notes = []
    kept_edges = []
    for edge in edges:
        if edge["from"] in node_ids and edge["to"] in node_ids:
            kept_edges.append(edge)
        else:
            notes.append(f"dropped edge {edge['from']} -> {edge['to']}: endpoint outside the page")
    if not nodes:
        _fail(2, "container_error:empty — no shapes parsed; is this a draw.io diagram?")

    spec = {
        "layout": "graph",
        "style": style,
        "animation": animation,
        "title": {"prefix": title or "Imported", "highlight": "diagram", "subtitle": "from draw.io"},
        "direction": "right",
        "nodes": nodes,
        "edges": kept_edges,
    }
    if groups:
        spec["groups"] = groups
    page_count = max(0, len(ET.fromstring(mxfile_text).findall("diagram")) if mxfile_text.lstrip().startswith("<mxfile") else 0)
    if page_count > 1:
        notes.append(f"imported page 1 of {page_count}; re-import other pages one at a time")
    _check_resource_limits(spec)
    _check_string_lengths(spec)
    return spec, notes


def to_spec(path, title=None, style="slate", animation="flow", detail="faithful", audience="engineer"):
    spec, notes = parse_drawio(load_mxfile(path), title=title, style=style, animation=animation)
    if detail != "faithful" or audience != "engineer":
        spec, ledger = import_refine.apply_dials(spec, detail=detail, audience=audience)
        notes = [*notes, *import_refine.format_ledger(ledger)]
    return spec, notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help=".drawio / .drawio.xml / .drawio.png / .drawio.svg file")
    parser.add_argument("--out", default=None, help="Write spec JSON here (default: stdout).")
    parser.add_argument("--title", default=None, help="Title prefix for the imported diagram.")
    parser.add_argument("--style", choices=["slate", "report", "academic", "blueprint", "custom"], default="slate")
    parser.add_argument("--animation", default="flow", help="Animation preset (default flow).")
    parser.add_argument("--detail", choices=import_refine.DETAIL_CHOICES, default="faithful",
                        help="How much of the source survives: faithful (<=24 nodes), balanced (<=12), "
                             "simplified (<=7); reductions are reported in the fidelity ledger.")
    parser.add_argument("--audience", choices=import_refine.AUDIENCE_CHOICES, default="engineer",
                        help="Wording dial: engineer keeps technical labels, mixed strips ports/schemes, "
                             "executive drops protocol jargon and caps label length.")
    parser.add_argument("--size", choices=["article", "wide", "square", "story"], default=None,
                        help="Canvas preset for the output (maps to spec canvas.preset).")
    args = parser.parse_args(argv)

    spec, notes = to_spec(args.input, title=args.title, style=args.style, animation=args.animation,
                          detail=args.detail, audience=args.audience)
    if args.size:
        spec.setdefault("canvas", {})["preset"] = args.size
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "out": args.out, "layout": spec["layout"],
                          "nodes": len(spec.get("nodes", [])), "edges": len(spec.get("edges", [])),
                          "notes": notes}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
