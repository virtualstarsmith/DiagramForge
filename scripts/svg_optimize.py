#!/usr/bin/env python3
"""Optimize DiagramForge's standalone SVG output.

Two complementary passes, both operating on the serialized SVG string:

1. **Font subsetting.** Every diagram embeds three full webfonts as base64
   data URIs (Excalifont + NotoSansSC Regular/Bold). The CJK fonts alone are
   ~2 MB, yet a single diagram usually touches only a few dozen glyphs.
   fontTools subsetting rebuilds each font retaining only the code points the
   diagram's text ops actually use, typically shrinking a 2.8 MB SVG to a
   few tens of KB while keeping it fully self-contained and offline-portable.

2. **Markup minification.** XML comments and redundant whitespace are stripped
   (numerical path data is left untouched to avoid corrupting base64 blobs).

The SVG remains byte-for-byte render-equivalent: the ``@font-face`` blocks
keep the same family names so ``check_outputs``'s ``svg_fonts_embedded``
contract (``@font-face`` + ``Excalifont``) still holds.
"""
from __future__ import annotations

import base64
import re
from io import BytesIO
from pathlib import Path

try:
    from fontTools import subset as _ft_subset
    _HAS_FONTTOOLS = True
except ImportError:  # pragma: no cover - fonttools is optional at runtime
    _HAS_FONTTOOLS = False

# Family -> (filename, weight). Mirrors svg_renderer.FONT_FACES so the subset
# CSS is a drop-in replacement for the embedded @font-face block.
_FONT_FACES = (
    ("Excalifont", "Excalifont-Regular.woff2", 400),
    ("NotoSansSC", "NotoSansSC-Regular.woff2", 400),
    ("NotoSansSC", "NotoSansSC-Bold.woff2", 700),
)

# Always retain ASCII + common punctuation so ligatures/spacing render even
# when a diagram happens to use characters only inside icon SVGs (which are
# inlined separately and do not flow through text ops).
_BASE_CODEPOINTS = set(range(0x20, 0x7F)) | {0xA0, 0x2014, 0x2013, 0x2026}  # pragma: no cover
  # pragma: no cover
_STYLE_RE = re.compile(r'<style([^>]*)>(.*?)</style>', re.DOTALL)
_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)


def collect_codepoints(doc) -> set:
    """Gather every unicode code point the diagram's text-bearing ops use."""
    cps = set(_BASE_CODEPOINTS)
    for op in doc.get("ops", []):
        kind = op.get("op")
        if kind in ("text", "signature"):
            for ch in op.get("text", ""):
                cps.add(ord(ch))
        elif kind == "line":
            # edge labels live in separate text ops, but guard anyway
            for ch in op.get("label", ""):
                cps.add(ord(ch))
    # titles / subtitles stored at the top of the doc are also rendered as text
    for key in ("title", "subtitle"):
        block = doc.get(key)
        if isinstance(block, dict):
            for ch in block.get("prefix", "") + block.get("highlight", ""):
                cps.add(ord(ch))
        elif isinstance(block, str):
            for ch in block:
                cps.add(ord(ch))
    return cps


def subset_font_to_woff2(font_path: Path, codepoints: set) -> bytes:
    """Return a woff2 byte string containing only *codepoints*.

    Raises if fontTools is unavailable or the subset fails; callers fall back
    to the full font.
    """
    return _subset_font(font_path, codepoints, flavor=["woff2"])


def subset_font_to_ttf(font_path: Path, codepoints: set) -> bytes:
    """Return a .ttf byte string containing only *codepoints*.

    Used to feed opentype.js (which parses ttf/otf/woff but not woff2 without
    extra decoders) a tiny per-diagram font so its parse step stays fast even
    for the large CJK source faces.
    """
    return _subset_font(font_path, codepoints, flavor=None)


def _subset_font(font_path: Path, codepoints: set, flavor) -> bytes:
    if not _HAS_FONTTOOLS:
        raise RuntimeError("fonttools not installed")
    opts = _ft_subset.Options()
    if flavor:
        opts.flavor = flavor
    opts.ignore_missing_unicodes = True
    opts.notdef_outline = True  # keep .notdef so the font stays valid
    font = _ft_subset.load_font(str(font_path), opts)
    subsetter = _ft_subset.Subsetter(options=opts)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    return buf.read()


def build_subset_font_css(codepoints: set, font_dir: Path) -> str:
    """Build the replacement @font-face CSS block with subsetted fonts.

    When a font cannot be subset (fonttools missing, empty glyph coverage,
    etc.) the original full font is embedded so the SVG still renders.
    """
    faces = []
    for family, filename, weight in _FONT_FACES:
        path = Path(font_dir) / filename
        if not path.is_file():
            continue
        data = None
        try:
            data = subset_font_to_woff2(path, codepoints)
        except Exception:
            data = None
        if not data:
            data = path.read_bytes()  # fall back to the full font
        b64 = base64.b64encode(data).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
        )
    return "\n".join(faces)


def minify_svg(svg_markup: str) -> str:
    """Strip XML comments and collapse inter-tag whitespace. Numerical data is
    left alone to protect base64 payloads and path coordinates."""
    svg_markup = _COMMENT_RE.sub("", svg_markup)
    # Collapse runs of whitespace between tags only (never inside text nodes).
    svg_markup = re.sub(r">\s+<", "><", svg_markup)
    return svg_markup


def optimize_svg(svg_markup: str, doc, font_dir) -> str:
    """Subet embedded fonts to the diagram's used glyphs and minify markup.

    Returns the (usually much smaller) SVG string. If fontTools is missing the
    font block is left untouched and only minification runs.
    """
    codepoints = collect_codepoints(doc)
    try:
        new_css = build_subset_font_css(codepoints, Path(font_dir))
        def _replace_font_style(m):
            # Only the @font-face block gets subsetted; other <style> blocks
            # (animation CSS, etc.) pass through untouched.
            if "@font-face" in m.group(2):
                return f"<style{m.group(1)}>{new_css}</style>"
            return m.group(0)
        if new_css:
            svg_markup = _STYLE_RE.sub(_replace_font_style, svg_markup)
    except Exception:
        # Subset failure must never corrupt the SVG; fall back to original.
        pass
    return minify_svg(svg_markup)
