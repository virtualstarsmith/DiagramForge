#!/usr/bin/env python3
"""On-disk render cache for DiagramForge browser outputs.

Caches the artifacts produced by ``svg_renderer.render_all`` keyed on a hash
of the ops document (layout + theme + animation + canvas). When the same
document is rendered again into the same output directory, every artifact that
is still present on disk is reused without launching Chromium — a full
re-render of an unchanged spec drops from seconds to milliseconds.

Cache layout::

    <outdir>/.dfcache/
        index.json          # {doc_hash: {format: basename-relative path, ...}}

The cache is intentionally conservative: a hit requires every requested
format's file to still exist on disk, and the hash covers exactly the fields
that influence pixel output. Anything absent simply re-runs the renderer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CACHE_DIR_NAME = ".dfcache"


def _output_relevant_fields(doc):
    """Pick the doc fields that change pixel output. Everything else (graph
    adjacency used only by the interactive HTML's script, layout name, etc.)
    is intentionally excluded so cosmetic-only differences don't thrash."""
    return {
        "ops": doc.get("ops"),
        "canvas": doc.get("canvas"),
        "bg": doc.get("bg"),
        "theme": doc.get("theme"),
        "animation": doc.get("animation"),
        "finish": doc.get("finish"),
    }


def doc_hash(doc, salt: str = "") -> str:
    """Stable 16-char hash of the output-relevant doc fields.

    ``salt`` carries anything outside the doc that still changes pixel output
    (notably the animation preset, which selects different GIF/MP4 timing
    without altering the ops document).
    """
    payload = json.dumps((_output_relevant_fields(doc), salt), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_root(outdir) -> Path:
    return Path(outdir) / CACHE_DIR_NAME


def _index_path(outdir) -> Path:
    return _cache_root(outdir) / "index.json"


def _load_index(outdir) -> dict:
    try:
        return json.loads(_index_path(outdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(outdir, index) -> None:
    root = _cache_root(outdir)
    root.mkdir(parents=True, exist_ok=True)
    _index_path(outdir).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _format_key(fmt: str, result: dict) -> str | None:
    """The basename-relative filename for *fmt* in *result*, or None."""
    path_str = result.get(fmt) or result.get(f"{fmt}_skipped")
    if not path_str:
        return None
    return Path(path_str).name


def lookup(doc, outdir, basename: str, formats, salt: str = ""):
    """Return a reconstructed result dict if every requested format is cached
    and still present on disk, else None.

    ``formats`` is the iterable of format names the caller wants; "excalidraw"
    and "lottie" are produced outside render_all but are still cached because
    they derive from the same doc. ``salt`` is extra key material (the
    animation preset) that changes output without altering the doc.
    """
    outdir = Path(outdir)
    h = doc_hash(doc, salt)
    index = _load_index(outdir)
    entry = index.get(h)
    if not entry:
        return None
    wanted = set(formats)
    # The entry maps format -> filename; verify each requested file exists.
    result = {"renderer": "browser", "cached": True}
    for fmt in wanted:
        fname = entry.get(fmt)
        if not fname:
            return None  # this format was never produced for this hash
        fpath = outdir / fname
        if not fpath.is_file():
            return None  # file was deleted since caching — miss
        result[fmt] = str(fpath)
    # Carry forward metadata the caller/check_outputs may read.
    for meta_key in ("elements", "canvas", "animation", "style", "frames"):
        if meta_key in entry:
            result[meta_key] = entry[meta_key]
    result["cache_hash"] = h
    return result


def store(doc, outdir, basename: str, result: dict, formats, salt: str = "") -> str:
    """Record *result* under its doc hash so a future identical render hits."""
    outdir = Path(outdir)
    h = doc_hash(doc, salt)
    index = _load_index(outdir)
    entry = {}
    for fmt in formats:
        fname = _format_key(fmt, result)
        if fname:
            entry[fmt] = fname
    for meta_key in ("elements", "canvas", "animation", "style", "frames"):
        if meta_key in result:
            entry[meta_key] = result[meta_key]
    index[h] = entry
    _save_index(outdir, index)
    return h


def invalidate(outdir) -> int:
    """Delete the cache index for *outdir*. Returns the number of dropped entries."""
    path = _index_path(outdir)
    if not path.is_file():
        return 0
    try:
        n = len(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        n = 0
    try:
        path.unlink()
    except OSError:
        pass
    return n
