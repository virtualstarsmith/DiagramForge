#!/usr/bin/env python3
import argparse
import bisect
import json
import math
import random
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

try:
    from svg.path import parse_path
except ImportError:  # pragma: no cover - exercised only when optional dependency is missing.
    parse_path = None

# Sibling modules must import even when this file is loaded from an arbitrary
# path (tests, editors), so pin the scripts dir onto sys.path.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)  # pragma: no cover

import drawio_export
import graph_model
import lint_geometry
import theme_loader

try:
    import icon_browser
except ImportError:  # pragma: no cover - allows import when run as a module path.
    icon_browser = None

try:
    import svg_renderer
except ImportError:  # pragma: no cover - allows import when run as a module path.
    svg_renderer = None

try:
    import lottie_export
except ImportError:  # pragma: no cover - allows import when run as a module path.
    lottie_export = None

try:
    import render_cache
except ImportError:  # pragma: no cover - allows import when run as a module path.
    render_cache = None

ANIMATION_CHOICES = ("flow", "draw", "relay", "trace", "chapter", "failure-recovery")

# When set to "skip", draw_svg_icon_tile only paints the tile chrome and leaves
# the glyph to the browser engine, which stamps animated frames afterwards.
ICON_GLYPH_MODE = "draw"

# Optional primitive-op recorder. When a list is installed here, every draw_*
# call appends a JSON-friendly op describing itself (CSS-space coordinates).
# The browser/SVG renderer replays these ops with rough.js, so both renderers
# share one layout. Managed by render_static_with_ops().
OPS_SINK = None


def ops_record(op):
    if OPS_SINK is not None:
        OPS_SINK.append(op)


DEFAULT_W = 1210
DEFAULT_H = 1138
DEFAULT_FRAMES = 41
DEFAULT_FPS = 20
SCALE = 2
UPDATED = 1782475200000

# Corner-radius scale — the only values card/container corners may take.
# Geometric pills (terminal nodes, stadium action boxes) and tiny controls
# (ports, activation bars) keep literal radii; everything else uses these.
RADIUS_SM = 4      # tags, chips, label masks
RADIUS_MD = 8      # node boxes
RADIUS_LG = 12     # cards, containers
RADIUS_FRAME = 16  # outer chrome frame

# Min visible clearance between an edge label's mask and its connector: the
# line must stay traceable right up to the label — a label that hides its own
# arrow is a hard fail.
EDGE_LABEL_GAP = 8

# ---------------------------------------------------------------------------
# Visual styles — four formal palettes for professional contexts.
# Each style MUST list every key in _THEME_KEYS so no hue leaks from another
# style: the renderer reads THEME[key] directly with no fallback, so a missing
# key would surface a foreign color (e.g. neon pink inside academic). A startup
# assertion enforces full coverage.
#   slate     dark technical  (GitHub/Linear)   dark finish,  multi-accent
#   report    light corporate (consulting/PPT)  light finish, soft multi-accent
#   academic  light academic  (B/W ink + accent) light finish, single-accent
#   blueprint dark engineering(indigo + cyan)   dark finish,  two-tone
# ---------------------------------------------------------------------------
_THEME_KEYS = frozenset({
    "bg", "white", "muted", "frame", "core_fill", "core_stroke",
    "green", "green_fill", "purple", "purple_fill", "cyan", "blue_fill",
    "highlight", "amber", "pink", "archive_fill", "source_fill", "pack_fill",
    "amber_fill", "sand_fill", "icon_fill", "decision_fill",
    "src_card_fill", "layer_card_fill", "pack_card_fill",
    # Neutral gray ramp for hierarchical bands (lanes / panels), per the
    # enterprise scheme: levels read through lightness steps, not hue swaps,
    # and external layers sink to the deepest gray.
    "lane_band_0", "lane_band_1", "lane_band_2", "lane_band_3",
    "lane_column", "lane_border",
})

STYLE_THEMES = {
    "slate": {  # dark technical — low-saturation multi-accent on slate blue
        "bg": "#0f172a", "white": "#e2e8f0", "muted": "#94a3b8", "frame": "#334155",
        "core_fill": "#1e293b", "core_stroke": "#3b82f6", "green": "#10b981", "green_fill": "#064e3b",
        "purple": "#6366f1", "purple_fill": "#1e1b4b", "cyan": "#0891b2", "blue_fill": "#172554",
        "highlight": "#134e4a", "amber": "#f59e0b", "pink": "#ef4444",
        "archive_fill": "#1e1b4b", "source_fill": "#064e3b", "pack_fill": "#064e3b",
        "amber_fill": "#451a03", "sand_fill": "#1c1410", "icon_fill": "#1e293b", "decision_fill": "#0f172a",
        "src_card_fill": "#1e293b", "layer_card_fill": "#1e1b4b", "pack_card_fill": "#1e293b",
        "lane_band_0": "#1e293b", "lane_band_1": "#263548", "lane_band_2": "#2e4055", "lane_band_3": "#374a61",
        "lane_column": "#263548", "lane_border": "#475569",
    },
    "report": {  # light corporate — clean white, enterprise blue, printable
        "bg": "#ffffff", "white": "#1e293b", "muted": "#64748b", "frame": "#cbd5e1",
        "core_fill": "#ffffff", "core_stroke": "#0f62fe", "green": "#0f62fe", "green_fill": "#eff6ff",
        "purple": "#4f46e5", "purple_fill": "#e0e7ff", "cyan": "#0891b2", "blue_fill": "#eff6ff",
        "highlight": "#dbeafe", "amber": "#d97706", "pink": "#dc2626",
        "archive_fill": "#e0e7ff", "source_fill": "#eff6ff", "pack_fill": "#ffffff",
        "amber_fill": "#fef3c7", "sand_fill": "#fefce8", "icon_fill": "#ffffff", "decision_fill": "#f0f9ff",
        "src_card_fill": "#ffffff", "layer_card_fill": "#ffffff", "pack_card_fill": "#ffffff",
        "lane_band_0": "#ffffff", "lane_band_1": "#f4f4f4", "lane_band_2": "#ececec", "lane_band_3": "#e0e0e0",
        "lane_column": "#d6d6d6", "lane_border": "#c6c6c6",
    },
    "academic": {  # light academic — white canvas, black ink, single deep-ink-blue accent
        "bg": "#ffffff", "white": "#1a1a1a", "muted": "#707070", "frame": "#9ca3af",
        "core_fill": "#ffffff", "core_stroke": "#1f3a5f", "green": "#1f3a5f", "green_fill": "#f3f4f6",
        "purple": "#1f3a5f", "purple_fill": "#e5e7eb", "cyan": "#1f3a5f", "blue_fill": "#f9fafb",
        "highlight": "#1f3a5f", "amber": "#1f3a5f", "pink": "#1f3a5f",
        "archive_fill": "#e5e7eb", "source_fill": "#f3f4f6", "pack_fill": "#f9fafb",
        "amber_fill": "#eceef0", "sand_fill": "#f3f4f6", "icon_fill": "#ffffff", "decision_fill": "#f3f4f6",
        "src_card_fill": "#ffffff", "layer_card_fill": "#f3f4f6", "pack_card_fill": "#ffffff",
        "lane_band_0": "#ffffff", "lane_band_1": "#f9fafb", "lane_band_2": "#f3f4f6", "lane_band_3": "#e5e7eb",
        "lane_column": "#e5e7eb", "lane_border": "#d1d5db",
    },
    "blueprint": {  # dark engineering — deep indigo canvas, white structure + cyan accent
        "bg": "#0d2447", "white": "#f0f6ff", "muted": "#7d9bc4", "frame": "#2a4a7f",
        "core_fill": "#0a1f3d", "core_stroke": "#f0f6ff", "green": "#5fbcd6", "green_fill": "#12365e",
        "purple": "#5fbcd6", "purple_fill": "#0f2c50", "cyan": "#5fbcd6", "blue_fill": "#12365e",
        "highlight": "#5fbcd6", "amber": "#5fbcd6", "pink": "#5fbcd6",
        "archive_fill": "#0f2c50", "source_fill": "#12365e", "pack_fill": "#0a1f3d",
        "amber_fill": "#154070", "sand_fill": "#12365e", "icon_fill": "#0a1f3d", "decision_fill": "#0d2447",
        "src_card_fill": "#12365e", "layer_card_fill": "#0f2c50", "pack_card_fill": "#12365e",
        "lane_band_0": "#0a1f3d", "lane_band_1": "#0f2c50", "lane_band_2": "#12365e", "lane_band_3": "#154070",
        "lane_column": "#0f2c50", "lane_border": "#2a4a7f",
    },
}
# Every style must fully cover the key set so apply_style can swap palettes
# wholesale without a base palette leaking foreign hues.
assert all(set(v) == _THEME_KEYS for v in STYLE_THEMES.values()), \
    "each STYLE_THEMES entry must define exactly the _THEME_KEYS keys"

# Finish mode per style: dark = deep canvas with glow beams; light = clean
# paper with traveling dots. Both finishes are grit-free (no grain/vignette).
STYLE_FINISH = {"slate": "dark", "blueprint": "dark", "report": "light", "academic": "light"}
DEFAULT_STYLE = "slate"
FINISH_MODE = STYLE_FINISH[DEFAULT_STYLE]
CURRENT_STYLE = DEFAULT_STYLE
THEME = dict(STYLE_THEMES[DEFAULT_STYLE])

# Sketch mode (explicit opt-in, default off). The four formal styles render
# clean by default: straight strokes, no icon tile chrome, sans-serif text
# everywhere, no default signature, print-clean light finish. Setting
# sketch=true restores the legacy hand-drawn language: rough.js wobble,
# Excalifont display type, tinted icon plates, the "@diagramforge" brand
# block, and the soft light-finish glow.
SKETCH = False

# Named canvas presets. Explicit
# canvas.width/height always win over preset values. Note: `graph` layouts
# compute their own natural canvas and treat width/height as diagnostics.
CANVAS_PRESETS = {
    "article": {"width": 1210, "height": 1138},  # portrait hero for articles (the signature look)
    "wide": {"width": 1600, "height": 900},      # 16:9 slides / video covers
    "square": {"width": 1080, "height": 1080},   # social feed posts
    "story": {"width": 1080, "height": 1350},    # 4:5 portrait covers (Xiaohongshu/Instagram)
}


def resolve_canvas_preset(spec):
    """Expand canvas.preset into width/height defaults; explicit values win."""
    canvas = spec.get("canvas")
    if not isinstance(canvas, dict):
        return
    preset = canvas.get("preset")
    if not preset:
        return
    values = CANVAS_PRESETS.get(preset)
    if values is None:
        return  # validate_spec reports the unknown preset name
    canvas.setdefault("width", values["width"])
    canvas.setdefault("height", values["height"])



def apply_style(name):
    """Switch the live THEME palette and finish mode to the named style."""
    global FINISH_MODE, CURRENT_STYLE
    if name not in STYLE_THEMES:
        choices = ", ".join(STYLE_THEMES)
        raise SystemExit(f"unknown style '{name}'. choices: {choices}")
    THEME.clear()
    THEME.update(STYLE_THEMES[name])
    FINISH_MODE = STYLE_FINISH.get(name, "dark")
    CURRENT_STYLE = name


def apply_custom_theme(theme):
    """Switch the live THEME palette to a validated custom theme dict.

    The finish mode (dark canvas vs light paper) derives from the theme's bg
    luminance. Validation already happened in theme_loader before this runs.
    """
    global FINISH_MODE, CURRENT_STYLE
    THEME.clear()
    THEME.update(theme)
    FINISH_MODE = theme_loader.finish_mode(theme)
    CURRENT_STYLE = "custom"


def set_sketch(flag):
    """Toggle sketch mode: hand-drawn strokes/plates/signature vs formal clean."""
    global SKETCH
    SKETCH = bool(flag)

ROOT = Path(__file__).resolve().parents[1]
TABLER_ICON_DIR = ROOT / "assets" / "icons" / "tabler"
# User-supplied vendor icon packs (e.g. assets/icons/vendor/aws/*.svg). Content
# is git-ignored on purpose: official cloud icon sets may not be redistributed
# (see references/vendor-icons.md). Vendor files take priority over the bundled
# Tabler set so official brand icons render when present.
VENDOR_ICON_DIR = ROOT / "assets" / "icons" / "vendor"
FONT_DIR = ROOT / "assets" / "fonts"
BUNDLED_HAND_FONT = FONT_DIR / "Excalifont-Regular.ttf"
BUNDLED_CJK_FONTS = {
    False: FONT_DIR / "NotoSansSC-Regular.ttf",
    True: FONT_DIR / "NotoSansSC-Bold.ttf",
}
_CJK_COVERAGE_RANGES = None
_CJK_COVERAGE_STARTS = None
ICON_ALIASES = {
    "file": "file-text",
    "document": "file-text",
    "folder": "folder",
    "scan": "search",
    "search": "search",
    "shield": "shield-check",
    "shield-check": "shield-check",
    "db": "database",
    "database": "database",
    "hash": "hash",
    "package": "package",
    "cube": "cube",
    "message": "message",
    "event": "calendar-event",
    "calendar": "calendar-event",
    "calendar-event": "calendar-event",
    "api": "api",
    "clock": "clock",
    "schedule": "clock",
    "brain": "brain",
    "gear": "settings",
    "settings": "settings",
    "eye": "eye",
    "observe": "eye",
    "terminal": "terminal-2",
    "terminal-2": "terminal-2",
    "world": "world",
    "globe": "world",
    "video": "video",
    "photo": "photo",
    "snapshot": "photo",
    "server": "server",
    "lock": "lock-check",
    "lock-check": "lock-check",
    "check": "check",
    "arrow-down-circle": "arrow-down-circle",
    "clipboard": "clipboard-text",
    "clipboard-text": "clipboard-text",
    # Stable semantic vocabulary. These aliases intentionally decouple specs
    # from the underlying icon filename so the art pack can evolve later.
    "cloud": "world", "cluster": "server", "container": "cube", "kubernetes": "cube",
    "queue": "message", "cache": "database", "load-balancer": "settings", "cdn": "world",
    "warehouse": "database", "lake": "database", "vector-db": "database", "stream": "arrow-down-circle",
    "etl": "settings", "analytics": "search", "dashboard": "eye", "model": "brain",
    "agent": "brain", "prompt": "message", "embedding": "hash", "rag": "search",
    "tool-call": "settings", "guardrail": "shield-check", "evaluation": "check",
    "identity": "lock-check", "key": "lock-check", "firewall": "shield-check", "audit": "clipboard-text",
    "policy": "file-text", "secret": "lock-check", "compliance": "check", "user": "message",
    "team": "message", "admin": "shield-check", "customer": "message", "payment": "check",
    "notification": "message", "success": "check", "warning": "shield-check", "failure": "arrow-down-circle",
    "pending": "clock", "retry": "arrow-down-circle", "manual-step": "clipboard-text",
    "memory": "database", "validate": "shield-check", "scope": "search", "budget": "clock",
    "output": "package", "think": "brain", "act": "settings", "observe": "eye",
    "working-memory": "clipboard-text", "code": "terminal-2", "trigger": "calendar-event",
    "prompt": "message", "embedding": "hash", "analytics": "eye", "dashboard": "eye",
    "firewall": "shield-check", "notification": "message", "customer": "message", "admin": "shield-check",
    # Loop-workflow vocabulary (agent loops, pipelines, orchestration). Each key
    # has a dedicated illustrated builder; the Tabler name is the outline fallback.
    "loop": "arrow-down-circle", "iterate": "arrow-down-circle", "cycle": "arrow-down-circle",
    "plan": "clipboard-text", "roadmap": "clipboard-text",
    "decision": "check", "condition": "check",
    "merge": "arrow-down-circle", "join": "arrow-down-circle", "aggregate": "arrow-down-circle",
    "split": "arrow-down-circle", "fanout": "arrow-down-circle", "fan-out": "arrow-down-circle",
    "parallel": "arrow-down-circle", "branch": "arrow-down-circle",
    "handoff": "package", "hand-off": "package", "delegate": "package",
    "subagent": "brain", "sub-agent": "brain", "worker": "brain",
    "orchestrator": "settings", "coordinator": "settings", "dispatch": "settings",
    "human": "message", "review": "clipboard-text", "approval": "check", "hitl": "clipboard-text",
    "checkpoint": "check", "milestone": "check",
    "rollback": "arrow-down-circle", "revert": "arrow-down-circle", "undo": "arrow-down-circle",
    "sandbox": "cube", "experiment": "cube", "lab": "cube",
    "compare": "search", "ab-test": "search", "benchmark": "search", "versus": "search",
    "score": "check", "grade": "check", "rating": "check", "rank": "check",
    "error": "arrow-down-circle", "exception": "arrow-down-circle", "fault": "arrow-down-circle",
    "wait": "clock", "delay": "clock", "timeout": "clock", "sleep": "clock",
    "emit": "message", "broadcast": "message", "publish": "message", "webhook": "api",
    "ingest": "arrow-down-circle", "intake": "arrow-down-circle", "import": "arrow-down-circle", "receive": "arrow-down-circle",
    # Cloud vendor / infra vocabulary. With an official icon pack dropped into
    # assets/icons/vendor/<pack>/ the exact file wins (see
    # references/vendor-icons.md); otherwise these fall back to the nearest
    # bundled Tabler icon so specs stay portable.
    "aws": "world", "amazon-web-services": "world", "gcp": "world", "google-cloud": "world",
    "azure": "world", "aliyun": "world", "tencent-cloud": "world",
    "s3": "package", "ec2": "server", "lambda": "settings", "ecs": "cube", "eks": "cube",
    "rds": "database", "dynamodb": "database", "sqs": "message", "sns": "message",
    "k8s": "cube", "docker": "cube", "helm": "package", "terraform": "settings",
    "kafka": "arrow-down-circle", "rabbitmq": "message", "redis": "database",
    "postgres": "database", "postgresql": "database", "mysql": "database", "mongodb": "database",
    "elasticsearch": "search", "nginx": "server", "grpc": "api", "graphql": "api",
    "prometheus": "eye", "grafana": "eye", "jenkins": "settings", "github": "api", "gitlab": "api",
}
SVG_ICON_CACHE = {}

# Single source of truth for icon sizing so every tile across the diagram is
# visually consistent. Supersampling keeps the rasterized strokes crisp.
ICON_TILE = 50
ICON_PAD = 7
# Frameless (plain) icons have no tile chrome, so the glyph can breathe wider.
ICON_PAD_PLAIN = 2
ICON_SUPERSAMPLE = 3


def hex_rgba(value, alpha=255):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def c(v):
    return int(round(v * SCALE))


def snap4(v):
    """4px grid: every coordinate, size, and gap snaps to a multiple of 4.
    Deterministic rounding keeps shared edges shared (equal values snap
    equal). Applied at the draw-primitive boundary so the Pillow raster, the
    op stream, and the Excalidraw export all share snapped geometry."""
    return round(v / 4) * 4


def scaled_box(x, y, w, h):
    return (c(x), c(y), c(x + w), c(y + h))


def font_candidates(hand=False, cjk=False, bold=False):
    """Bundled fonts first (identical output on Windows / macOS / Codex Linux
    sandbox), then platform fonts as fallback."""
    if hand:
        return [
            str(BUNDLED_HAND_FONT),
            "C:/Windows/Fonts/segoeprb.ttf",
            "C:/Windows/Fonts/segoepr.ttf",
            "C:/Windows/Fonts/comicbd.ttf",
            "C:/Windows/Fonts/comic.ttf",
            "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
            "/System/Library/Fonts/MarkerFelt.ttc",
            "/System/Library/Fonts/Noteworthy.ttc",
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
        ]
    if cjk:
        return [
            str(BUNDLED_CJK_FONTS[bold]),
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]
    return [
        # Noto Sans SC ships clean Latin glyphs, so plain labels stay
        # consistent across platforms too.
        str(BUNDLED_CJK_FONTS[bold]),
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def cjk_coverage_ranges():
    global _CJK_COVERAGE_RANGES, _CJK_COVERAGE_STARTS
    if _CJK_COVERAGE_RANGES is None:
        try:
            raw = json.loads((FONT_DIR / "notosanssc-coverage.json").read_text(encoding="utf-8"))
            _CJK_COVERAGE_RANGES = [(int(a), int(b)) for a, b in raw]
        except (OSError, ValueError):
            _CJK_COVERAGE_RANGES = []
        _CJK_COVERAGE_STARTS = [a for a, _ in _CJK_COVERAGE_RANGES]
    return _CJK_COVERAGE_RANGES, _CJK_COVERAGE_STARTS


def bundled_cjk_covers(text):
    ranges, starts = cjk_coverage_ranges()
    if not ranges:
        return False
    for ch in str(text):
        cp = ord(ch)
        if cp == 0x0A:  # newline, never rendered as a glyph
            continue
        i = bisect.bisect_right(starts, cp) - 1
        if i < 0 or cp > ranges[i][1]:
            return False
    return True


def load_font(size, hand=False, cjk=False, bold=False, text=""):
    candidates = font_candidates(hand=hand, cjk=cjk, bold=bold)
    if cjk and text and not bundled_cjk_covers(text):
        # Rare glyph outside the bundled subset: prefer full system CJK fonts.
        bundled = str(BUNDLED_CJK_FONTS[bold])
        candidates = [p for p in candidates if p != bundled] + [bundled]
    for path in candidates:
        try:
            return ImageFont.truetype(path, c(size))
        except OSError:
            continue
    return ImageFont.load_default()


def has_cjk(text):
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def text_size(draw, text, font, spacing=3):
    if not text:
        return 0, 0
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=c(spacing))
    return box[2] - box[0], box[3] - box[1]


def wrap_token(draw, token, font, max_width):
    if not token:
        return [token]
    parts = []
    current = ""
    for char in token:
        candidate = current + char
        if current and text_size(draw, candidate, font)[0] > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def wrap_line(draw, line, font, max_width):
    if not line:
        return [line]
    tokens = list(line) if has_cjk(line) else line.split(" ")
    separator = "" if has_cjk(line) else " "
    lines = []
    current = ""
    for token in tokens:
        candidate = token if not current else current + separator + token
        if text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if text_size(draw, token, font)[0] <= max_width:
            current = token
        else:
            split_parts = wrap_token(draw, token, font, max_width)
            lines.extend(split_parts[:-1])
            current = split_parts[-1] if split_parts else ""
    if current:
        lines.append(current)
    return lines


def wrap_text(draw, text, font, max_width):
    lines = []
    for raw_line in str(text).splitlines() or [""]:
        lines.extend(wrap_line(draw, raw_line, font, max_width))
    return "\n".join(lines)


EMERGENCY_MIN_TEXT_SIZE = 6


def text_variants(draw, text, font, max_width, wrap):
    raw = str(text)
    if not wrap:
        return [raw]
    wrapped = wrap_text(draw, raw, font, max_width)
    if wrapped == raw:
        return [wrapped]
    return [wrapped, raw]


def _word_safe(raw, wrapped):
    """True when wrapping only happened at word boundaries (CJK is always safe)."""
    if wrapped == raw or has_cjk(raw):
        return True
    return wrapped.replace("\n", " ") == raw


def fit_text(draw, text, w, h, size, min_size=10, hand=False, bold=False, spacing=3, wrap=True):
    raw_text = str(text)
    has_cjk_text = has_cjk(raw_text)
    max_width = c(w)
    max_height = c(h)
    start_size = int(size)
    emergency_min = min(start_size, int(min_size), EMERGENCY_MIN_TEXT_SIZE)
    # Pass 1 only accepts word-boundary wraps: a long single word shrinks to
    # fit on one line instead of breaking mid-word at full size. Pass 2
    # re-allows mid-word breaks as the last resort before the emergency floor.
    for allow_word_breaks in (False, True):
        for candidate_size in range(start_size, emergency_min - 1, -1):
            candidate_font = load_font(candidate_size, hand=hand and not has_cjk_text, cjk=has_cjk_text, bold=bold, text=raw_text)
            for candidate_text in text_variants(draw, raw_text, candidate_font, max_width, wrap):
                if not allow_word_breaks and not _word_safe(raw_text, candidate_text):
                    continue
                tw, th = text_size(draw, candidate_text, candidate_font, spacing=spacing)
                if tw <= max_width and th <= max_height:
                    return candidate_text, candidate_size, candidate_font

    fallback_font = load_font(emergency_min, hand=hand and not has_cjk_text, cjk=has_cjk_text, bold=bold, text=raw_text)
    fallback_text = wrap_text(draw, raw_text, fallback_font, max_width) if wrap else raw_text
    return fallback_text, emergency_min, fallback_font


class Excal:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.elements = []
        self.count = 0
        self.rng = random.Random(2069769416930414980)

    def base(self, prefix, kind, x, y, w, h, stroke, fill="transparent", stroke_width=2, stroke_style="solid", roundness=None):
        self.count += 1
        element = {
            "id": f"{prefix}-{self.count:04d}",
            "type": kind,
            "x": round(x, 2),
            "y": round(y, 2),
            "width": round(w, 2),
            "height": round(h, 2),
            "angle": 0,
            "strokeColor": stroke,
            "backgroundColor": fill or "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": stroke_style,
            "roughness": 1 if SKETCH else 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "index": f"a{self.count:04d}",
            "roundness": roundness,
            "seed": self.rng.randint(1, 2147483646),
            "version": 1,
            "versionNonce": self.rng.randint(1, 2147483646),
            "isDeleted": False,
            "boundElements": None,
            "updated": UPDATED,
            "link": None,
            "locked": False,
            "customData": {"_diagramforge": True},
        }
        self.elements.append(element)
        return element

    def rect(self, x, y, w, h, stroke, fill="transparent", width=2, style="solid"):
        return self.base("rect", "rectangle", x, y, w, h, stroke, fill, width, style, {"type": 3})

    def ellipse(self, x, y, w, h, stroke, fill="transparent", width=2, style="solid"):
        return self.base("ellipse", "ellipse", x, y, w, h, stroke, fill, width, style, None)

    def diamond(self, x, y, w, h, stroke, fill="transparent", width=2):
        return self.base("diamond", "diamond", x, y, w, h, stroke, fill, width, "solid", {"type": 2})

    def text(self, text, x, y, w, h, size, color, align="left"):
        element = self.base("text", "text", x, y, w, h, color, "transparent", 1, "solid", None)
        element.update(
            {
                "text": text,
                "fontSize": int(round(size)),
                "fontFamily": 5,
                "textAlign": align,
                "verticalAlign": "top",
                "baseline": int(round(size * 1.25)),
                "containerId": None,
                "originalText": text,
                "lineHeight": 1.25,
            }
        )
        return element

    def line(self, points, stroke, width=2, style="solid", arrow=False):
        arrow = "open" if arrow is True else (arrow or False)
        kind = "arrow" if arrow else "line"
        min_x = min(x for x, _ in points)
        min_y = min(y for _, y in points)
        max_x = max(x for x, _ in points)
        max_y = max(y for _, y in points)
        element = self.base(
            kind,
            kind,
            min_x,
            min_y,
            max_x - min_x,
            max_y - min_y,
            stroke,
            "transparent",
            width,
            style,
            {"type": 2},
        )
        element["points"] = [[round(x - min_x, 2), round(y - min_y, 2)] for x, y in points]
        element["startArrowhead"] = None
        element["endArrowhead"] = ("triangle" if arrow in ("filled", "triangle") else "arrow") if arrow else None
        element["startBinding"] = None
        element["endBinding"] = None
        return element

    def write(self, path):
        import time
        # Stamp every element with the real export time so the file reflects
        # when it was generated (the legacy module-level constant froze all
        # exports at a single fixed timestamp).
        now_ms = int(time.time() * 1000)
        for el in self.elements:
            el["updated"] = now_ms
        data = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": self.elements,
            "appState": {
                "viewBackgroundColor": THEME["bg"],
                "gridSize": 20,
                "currentItemFontFamily": 5,
            },
            "files": {},
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _label_mask(ex, draw, x, y, w, h):
    """Opaque paper chip behind an edge label, recorded before the text op so
    the connector never bleeds through the glyphs. Fill and stroke are both
    the page bg, so the chip itself is invisible — only its knock-out effect
    on lines beneath is seen."""
    ops_record({"op": "rect", "x": x, "y": y, "w": w, "h": h, "stroke": THEME["bg"],
                "fill": THEME["bg"], "width": 1, "radius": RADIUS_SM, "style": "solid",
                "role": "edge-label-mask"})
    ex.rect(x, y, w, h, THEME["bg"], THEME["bg"], 1, "solid")
    draw.rounded_rectangle(scaled_box(x, y, w, h), radius=c(RADIUS_SM), fill=hex_rgba(THEME["bg"]))


def draw_text(ex, draw, text, x, y, w, h, size, color=None, align="center", hand=False, bold=False, spacing=3, fit=False, min_size=10, wrap=True, mask=False, role=None):
    x, y, w, h = snap4(x), snap4(y), snap4(w), snap4(h)
    color = color or THEME["white"]
    hand = hand and SKETCH  # formal mode keeps every label in the sans face
    if fit:
        text, size, font = fit_text(draw, text, w, h, size, min_size=min_size, hand=hand, bold=bold, spacing=spacing, wrap=wrap)
    else:
        font = load_font(size, hand=hand and not has_cjk(text), cjk=has_cjk(text), bold=bold, text=text)
    tw, th = text_size(draw, text, font, spacing=spacing)
    tx = c(x)
    if align == "center":
        tx = c(x) + (c(w) - tw) / 2
    elif align == "right":
        tx = c(x + w) - tw
    ty = c(y) + (c(h) - th) / 2
    if mask and text:
        # Snug chip hugging the measured glyphs — not the layout box — so a
        # generous label box can't erase connectors or bars it only overlaps.
        pad_x, pad_y = 6, 3
        _label_mask(ex, draw,
                    max(0.0, (tx - c(pad_x)) / SCALE), max(0.0, (ty - c(pad_y)) / SCALE),
                    (tw + 2 * c(pad_x)) / SCALE, (th + 2 * c(pad_y)) / SCALE)
    op = {"op": "text", "text": str(text), "x": x, "y": y, "w": w, "h": h, "size": size,
          "color": color, "align": align, "hand": bool(hand), "bold": bool(bold), "spacing": spacing}
    if role:
        op["role"] = role
    ops_record(op)
    ex.text(text, x, y, w, h, size, color, align=align)
    draw.multiline_text((tx, ty), text, font=font, fill=hex_rgba(color), spacing=c(spacing), align=align)


def draw_rect(ex, draw, x, y, w, h, stroke, fill=None, width=2, radius=RADIUS_MD, style="solid"):
    x, y, w, h = snap4(x), snap4(y), snap4(w), snap4(h)
    ops_record({"op": "rect", "x": x, "y": y, "w": w, "h": h, "stroke": stroke, "fill": fill,
                "width": width, "radius": radius, "style": style})
    ex.rect(x, y, w, h, stroke, fill or "transparent", width, style)
    draw.rounded_rectangle(scaled_box(x, y, w, h), radius=c(radius), outline=hex_rgba(stroke), fill=hex_rgba(fill) if fill else None, width=max(1, c(width)))


def draw_ellipse(ex, draw, x, y, w, h, stroke, fill=None, width=2):
    x, y, w, h = snap4(x), snap4(y), snap4(w), snap4(h)
    ops_record({"op": "ellipse", "x": x, "y": y, "w": w, "h": h, "stroke": stroke, "fill": fill, "width": width})
    ex.ellipse(x, y, w, h, stroke, fill or "transparent", width)
    draw.ellipse(scaled_box(x, y, w, h), outline=hex_rgba(stroke), fill=hex_rgba(fill) if fill else None, width=max(1, c(width)))


def draw_line(ex, draw, points, stroke, width=2, style="solid", arrow=False):
    # arrow: False, True ("open"), "open" (V head) or "filled" (UML solid
    # triangle, used by sequence sync messages).
    arrow = "open" if arrow is True else (arrow or False)
    # Drop duplicate consecutive points: a zero-length final segment would
    # send the arrowhead math (atan2 of a 0-length run) into a random angle.
    clean = [points[0]] if points else []
    for p in points[1:]:
        if tuple(p) != tuple(clean[-1]):
            clean.append(p)
    points = clean
    points = [(snap4(px), snap4(py)) for px, py in points]
    ops_record({"op": "line", "points": [[px, py] for px, py in points], "stroke": stroke,
                "width": width, "style": style, "arrow": arrow})
    ex.line(points, stroke, width, style, arrow)
    scaled = [(c(x), c(y)) for x, y in points]
    if style == "solid":
        draw.line(scaled, fill=hex_rgba(stroke), width=max(1, c(width)), joint="curve")
    else:
        total = path_len(points)
        dist = 0
        dash = 8 if style == "dashed" else 2
        gap = 8 if style == "dashed" else 7
        while dist < total:
            start = point_at_distance(points, dist)
            end = point_at_distance(points, min(total, dist + dash))
            draw.line([(c(start[0]), c(start[1])), (c(end[0]), c(end[1]))], fill=hex_rgba(stroke), width=max(1, c(width)))
            dist += dash + gap
    if arrow and len(points) >= 2:
        head = "filled" if arrow == "filled" else ("triangle" if arrow == "triangle" else False)
        arrow_head(draw, points[-2], points[-1], stroke, width, filled=head)


def draw_diamond(ex, draw, x, y, w, h, stroke, fill=None, width=2):
    x, y, w, h = snap4(x), snap4(y), snap4(w), snap4(h)
    ops_record({"op": "diamond", "x": x, "y": y, "w": w, "h": h, "stroke": stroke, "fill": fill, "width": width})
    ex.diamond(x, y, w, h, stroke, fill or "transparent", width)
    pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    scaled = [(c(px), c(py)) for px, py in pts]
    draw.polygon(scaled, outline=hex_rgba(stroke), fill=hex_rgba(fill) if fill else None)
    draw.line(scaled + [scaled[0]], fill=hex_rgba(stroke), width=max(1, c(width)))


def path_len(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def point_at_distance(points, distance):
    left = distance
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        if left <= seg:
            t = left / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        left -= seg
    return points[-1]


def point_at_fraction(points, t):
    total = path_len(points)
    return point_at_distance(points, (t % 1.0) * total)


def arrow_head(draw, a, b, stroke, width=2, filled=False):
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    length = 14 + width
    spread = 0.52
    p1 = (b[0] - length * math.cos(angle - spread), b[1] - length * math.sin(angle - spread))
    p2 = (b[0] - length * math.cos(angle + spread), b[1] - length * math.sin(angle + spread))
    if filled == "triangle":
        # UML hollow triangle (inheritance/realization): slightly longer, outline only.
        length = 20 + width
        p1 = (b[0] - length * math.cos(angle - spread), b[1] - length * math.sin(angle - spread))
        p2 = (b[0] - length * math.cos(angle + spread), b[1] - length * math.sin(angle + spread))
        pts = [(c(p1[0]), c(p1[1])), (c(b[0]), c(b[1])), (c(p2[0]), c(p2[1]))]
        draw.polygon(pts, outline=hex_rgba(stroke), fill=hex_rgba(THEME["bg"]))
        draw.line(pts + [pts[0]], fill=hex_rgba(stroke), width=max(1, c(width)))
    elif filled:
        draw.polygon([(c(p1[0]), c(p1[1])), (c(b[0]), c(b[1])), (c(p2[0]), c(p2[1]))], fill=hex_rgba(stroke))
    else:
        draw.line([(c(p1[0]), c(p1[1])), (c(b[0]), c(b[1])), (c(p2[0]), c(p2[1]))], fill=hex_rgba(stroke), width=max(1, c(width)))


def is_custom_icon(kind):
    """Custom icons are encoded as '@<absolute path>' (see resolve_custom_icons)."""
    return isinstance(kind, str) and kind.startswith("@")


def custom_icon_path(kind):
    return Path(str(kind)[1:])


_ICON_SVG_CACHE = {}


def find_icon_svg(icon_name):
    """Locate an icon SVG: vendor packs first, then the bundled Tabler set.

    Vendor packs live at assets/icons/vendor/<pack>/<name>.svg and are searched
    in sorted pack order. Results are cached per process.
    """
    name = str(icon_name or "")
    if not name or name.startswith("@"):
        return None
    if name in _ICON_SVG_CACHE:
        return _ICON_SVG_CACHE[name]
    path = None
    if VENDOR_ICON_DIR.is_dir():
        for pack in sorted(VENDOR_ICON_DIR.iterdir()):
            candidate = pack / f"{name}.svg" if pack.is_dir() else None
            if candidate is not None and candidate.is_file():
                path = candidate
                break
    if path is None:
        candidate = TABLER_ICON_DIR / f"{name}.svg"
        if candidate.is_file():
            path = candidate
    _ICON_SVG_CACHE[name] = path
    return path


def resolve_icon_name(kind):
    if is_custom_icon(kind):
        return str(kind)
    key = str(kind or "file")
    # An exact SVG file (vendor pack or bundled Tabler) always wins over the
    # alias table; aliases are the fallback when no file matches the raw key.
    if find_icon_svg(key) is not None:
        return key
    return ICON_ALIASES.get(key, key)


def load_svg_icon(icon_name, color, size):
    if parse_path is None:
        return None
    cache_key = (icon_name, color, size)
    if cache_key in SVG_ICON_CACHE:
        return SVG_ICON_CACHE[cache_key].copy()

    path = find_icon_svg(icon_name)
    if path is None:
        return None
    try:
        rendered = render_svg_outline(path, color, size)
    except Exception:
        return None
    SVG_ICON_CACHE[cache_key] = rendered
    return rendered.copy()


def strip_namespace(tag):
    return tag.rsplit("}", 1)[-1]


def svg_number(value, default=0.0):
    if value is None:
        return default
    return float(str(value).replace("px", "").strip() or default)


def icon_point(x, y, scale, offset):
    return (offset + x * scale, offset + y * scale)


def draw_svg_polyline(draw, points, color, width):
    if len(points) >= 2:
        draw.line(points, fill=hex_rgba(color, 245), width=width, joint="curve")
    elif points:
        x, y = points[0]
        radius = max(1, width // 2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=hex_rgba(color, 245))


def sample_svg_segment(segment, scale, offset):
    try:
        length = max(1.0, float(segment.length(error=1e-3)))
    except Exception:
        length = 8.0
    steps = max(3, min(48, int(length * scale / 4)))
    points = []
    for i in range(steps + 1):
        point = segment.point(i / steps)
        points.append(icon_point(point.real, point.imag, scale, offset))
    return points


def draw_svg_path(draw, d, color, width, scale, offset):
    parsed = parse_path(d)
    for segment in parsed:
        points = sample_svg_segment(segment, scale, offset)
        draw_svg_polyline(draw, points, color, width)


def draw_svg_shape(draw, element, color, width, scale, offset):
    tag = strip_namespace(element.tag)
    if tag == "path":
        d = element.attrib.get("d")
        if d:
            draw_svg_path(draw, d, color, width, scale, offset)
    elif tag == "line":
        points = [
            icon_point(svg_number(element.attrib.get("x1")), svg_number(element.attrib.get("y1")), scale, offset),
            icon_point(svg_number(element.attrib.get("x2")), svg_number(element.attrib.get("y2")), scale, offset),
        ]
        draw_svg_polyline(draw, points, color, width)
    elif tag in {"polyline", "polygon"}:
        raw_points = element.attrib.get("points", "").replace(",", " ").split()
        coords = [svg_number(item) for item in raw_points]
        points = [icon_point(coords[i], coords[i + 1], scale, offset) for i in range(0, len(coords) - 1, 2)]
        if tag == "polygon" and points:
            points.append(points[0])
        draw_svg_polyline(draw, points, color, width)
    elif tag == "circle":
        cx = svg_number(element.attrib.get("cx"))
        cy = svg_number(element.attrib.get("cy"))
        r = svg_number(element.attrib.get("r"))
        x, y = icon_point(cx, cy, scale, offset)
        rr = r * scale
        draw.ellipse((x - rr, y - rr, x + rr, y + rr), outline=hex_rgba(color, 245), width=width)
    elif tag == "rect":
        x = svg_number(element.attrib.get("x"))
        y = svg_number(element.attrib.get("y"))
        w = svg_number(element.attrib.get("width"))
        h = svg_number(element.attrib.get("height"))
        rx = svg_number(element.attrib.get("rx"), 0.0)
        x1, y1 = icon_point(x, y, scale, offset)
        x2, y2 = icon_point(x + w, y + h, scale, offset)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=rx * scale, outline=hex_rgba(color, 245), width=width)


def render_svg_outline(path, color, size):
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    view_box = root.attrib.get("viewBox", "0 0 24 24").split()
    vb_w = svg_number(view_box[2], 24.0) if len(view_box) >= 4 else 24.0

    # Render large, then downscale with LANCZOS so the line art is smooth and
    # the stroke weight stays bold instead of thin and broken at small sizes.
    render_size = max(48, size) * ICON_SUPERSAMPLE
    margin = max(2, int(round(render_size * 0.06)))
    scale = (render_size - margin * 2) / vb_w
    width = max(3, int(round(render_size / 24 * 2.0)))
    img = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for element in root.iter():
        draw_svg_shape(draw, element, color, width, scale, margin)
    return img.resize((size, size), Image.Resampling.LANCZOS)


_PILLOW_ILL_FAMILIES = (
    ("loop", ("loop", "iterate", "cycle", "retry", "rollback", "revert", "undo")),
    ("decision", ("decision", "condition")),
    ("error", ("error", "exception", "fault", "warning")),
    ("wait", ("wait", "delay", "timeout", "sleep", "hourglass")),
    # Before the shield family so "checkpoint" is not swallowed by "check".
    ("file", ("plan", "roadmap", "checkpoint", "milestone")),
    ("brain", ("brain", "think", "model", "reason", "subagent", "sub-agent", "worker")),
    ("agent", ("agent",)),
    ("gear", ("gear", "act", "tool", "settings", "etl", "load-balancer",
              "orchestr", "coordinator", "dispatch")),
    ("analytics", ("analytics", "dashboard", "compare", "ab-test", "benchmark", "versus")),
    ("eye", ("eye", "observe", "monitor")),
    ("db", ("db", "database", "memory", "working-memory", "warehouse", "lake",
            "storage", "cache", "vector", "embedding", "ingest", "intake", "import", "receive")),
    ("search", ("search", "scan", "rag", "scope")),
    ("shield", ("shield", "validate", "guard", "check", "success", "firewall",
                "admin", "compliance", "approve", "score", "grade", "rating", "rank")),
    ("clock", ("clock", "budget", "schedule", "pending", "time")),
    ("notification", ("notification", "emit", "broadcast", "publish", "webhook")),
    ("message", ("message", "chat", "prompt", "queue")),
    ("api", ("api",)),
    ("package", ("package", "output", "deliver", "cube", "box", "container",
                 "handoff", "hand-off", "delegate", "sandbox", "experiment", "lab")),
    ("cloud", ("cloud", "deploy", "cdn", "globe", "world")),
    ("server", ("server", "cluster")),
    ("lock", ("lock", "secret", "key", "identity")),
    ("user", ("user", "customer", "team", "human", "review", "approval", "hitl")),
    ("terminal", ("terminal", "code")),
    ("file", ("file", "document", "policy", "audit", "clipboard", "manual-step", "folder")),
)


def draw_illustrated_icon_raster(draw, kind, x, y, color, scale=1.0, hero=False):
    """Dependency-free Pillow fallback: static rest poses of the duotone set.

    Mirrors the browser engine's "Neon Sketch Duotone" language - plate-free
    theme-ink strokes with one semantic accent - collapsed to the closest of
    ~19 hand-kept families.
    """
    semantic = str(kind).lower()
    family = "module"
    for name, keys in _PILLOW_ILL_FAMILIES:
        if semantic.startswith(keys):
            family = name
            break
    t = ICON_TILE * scale / 48.0 * (1.16 if hero else 1.0)
    ox = x + ICON_TILE * scale / 2 - 24 * t
    oy = y + ICON_TILE * scale / 2 - 24 * t

    def P(vx, vy):
        return (c(ox + vx * t), c(oy + vy * t))

    # ImageDraw here overwrites rather than alpha-blends, so translucent
    # duotone tones are premixed against the card/background color.
    def _mix(top, base, k):
        a = hex_rgba(top)
        b = hex_rgba(base)
        return tuple(int(a[i] * k + b[i] * (1 - k)) for i in range(3)) + (255,)

    ink = hex_rgba(THEME["white"])
    ink_soft = _mix(THEME["white"], THEME["icon_fill"], 0.52)
    ghost = _mix(THEME["white"], THEME["icon_fill"], 0.24)
    acc = hex_rgba(color)
    acc_soft = _mix(color, THEME["icon_fill"], 0.22)

    def W(w):
        return max(2, c(w * t))

    def line(pts, col=None, w=2.8, ghosted=True):
        seq = [P(px, py) for px, py in pts]
        if col is None:
            if ghosted:
                gseq = [(px_ + c(0.75 * t), py_ - c(0.55 * t)) for px_, py_ in seq]
                draw.line(gseq, fill=ghost, width=max(1, c(w * t * 0.55)), joint="curve")
            draw.line(seq, fill=ink, width=W(w), joint="curve")
        else:
            draw.line(seq, fill=col, width=W(w), joint="curve")

    def ell(x0, y0, x1, y1, outline=None, fill=None, w=2.8):
        draw.ellipse((*P(x0, y0), *P(x1, y1)), outline=outline, fill=fill, width=W(w))

    def rrect(x0, y0, x1, y1, r, outline=None, fill=None, w=2.8):
        draw.rounded_rectangle((*P(x0, y0), *P(x1, y1)), radius=c(r * t),
                               outline=outline, fill=fill, width=W(w))

    def arc(x0, y0, x1, y1, start, end, col=None, w=2.8):
        draw.arc((*P(x0, y0), *P(x1, y1)), start, end, fill=col or ink, width=W(w))

    if family == "brain":
        ell(9.5, 8, 38.5, 40, outline=ink)
        line([(24, 11), (24, 37)], col=ink_soft, w=1.8)
        line([(16.5, 18.5), (24, 24.5), (31.5, 17.5)], col=hex_rgba(color, 150), w=2)
        line([(18.5, 30), (24, 24.5), (29.5, 30)], col=hex_rgba(color, 150), w=2)
        for px, py in ((16.5, 18.5), (24, 24.5), (31.5, 17.5), (18.5, 30), (29.5, 30)):
            ell(px - 2, py - 2, px + 2, py + 2, outline=acc, fill=acc_soft, w=1)
    elif family == "agent":
        rrect(11, 15, 37, 36.5, 6.5, outline=ink)
        line([(8.2, 23.5), (8.2, 30.5)], w=2.6)
        line([(39.8, 23.5), (39.8, 30.5)], w=2.6)
        line([(24, 15), (24, 9.6)], w=2.2)
        ell(21.9, 6.1, 26.1, 10.3, fill=acc)
        for ex_ in (18.6, 29.4):
            ell(ex_ - 2.7, 21.6, ex_ + 2.7, 27, fill=acc)
        arc(18.5, 26.5, 29.5, 33.9, 20, 160, col=acc, w=2.2)
    elif family == "gear":
        for i in range(8):
            a = i * math.pi / 4
            line([(22 + math.cos(a) * 12.6, 22 + math.sin(a) * 12.6),
                  (22 + math.cos(a) * 17.6, 22 + math.sin(a) * 17.6)], w=4.4, ghosted=False)
        ell(10.4, 10.4, 33.6, 33.6, outline=ink, w=3)
        ell(17.4, 17.4, 26.6, 26.6, outline=acc, fill=acc_soft, w=2)
        ell(33.1, 33.1, 41.9, 41.9, outline=ink_soft, w=2.2)
        ell(36.1, 36.1, 38.9, 38.9, fill=acc)
    elif family == "eye":
        arc(5.5, 9.5, 42.5, 38.5, 199, 341, w=3)
        arc(5.5, 9.5, 42.5, 38.5, 19, 161, w=3)
        ell(16.6, 16.6, 31.4, 31.4, outline=acc, fill=acc_soft, w=2.4)
        ell(20.8, 20.8, 27.2, 27.2, fill=acc)
        ell(25.1, 20.5, 27.3, 22.7, fill=ink)
        for lx0, ly0, lx1, ly1 in ((13, 13.5, 11, 10.8), (24, 10.4, 24, 7.4), (35, 13.5, 37, 10.8)):
            line([(lx0, ly0), (lx1, ly1)], col=ink_soft, w=2, ghosted=False)
    elif family == "db":
        ell(10.5, 9.2, 37.5, 18.8, outline=ink, w=3)
        line([(10.5, 14), (10.5, 33.5)], w=3)
        line([(37.5, 14), (37.5, 33.5)], w=3)
        arc(10.5, 28.7, 37.5, 38.3, 0, 180, w=3)
        line([(13.5, 22.4), (34.5, 22.4)], col=hex_rgba(color, 150), w=2, ghosted=False)
        line([(13.5, 27.6), (34.5, 27.6)], col=hex_rgba(color, 150), w=2, ghosted=False)
    elif family == "search":
        ell(8.2, 8.2, 32.8, 32.8, outline=ink, w=3)
        line([(29.6, 29.6), (38.6, 38.6)], w=4.2)
        line([(11.5, 20.5), (29.5, 20.5)], col=acc, w=2.2, ghosted=False)
        for hx, hy in ((16.5, 17.2), (24.5, 24.0)):
            ell(hx - 1.9, hy - 1.9, hx + 1.9, hy + 1.9, fill=hex_rgba(color, 140))
    elif family == "shield":
        pts = [P(24, 6.5), P(37.8, 11.2), P(36.4, 26), P(24, 38.5), P(11.6, 26), P(10.2, 11.2)]
        draw.polygon(pts, fill=acc_soft)
        line([(24, 6.5), (37.8, 11.2), (36.4, 26), (24, 38.5), (11.6, 26), (10.2, 11.2), (24, 6.5)], w=3)
        line([(17, 23.5), (22, 29), (31.5, 17.5)], col=acc, w=3.4, ghosted=False)
    elif family == "clock":
        ell(6.8, 6.8, 41.2, 41.2, outline=ink, w=3)
        for i in range(4):
            a = i * math.pi / 2
            line([(24 + math.cos(a) * 13.2, 24 + math.sin(a) * 13.2),
                  (24 + math.cos(a) * 15.8, 24 + math.sin(a) * 15.8)], w=2.4, ghosted=False)
        line([(24, 24), (30.2, 20.4)], w=3.2, ghosted=False)
        line([(24, 24), (24, 11.6)], col=acc, w=3, ghosted=False)
        ell(21.9, 21.9, 26.1, 26.1, fill=acc)
    elif family == "notification":
        arc(17.5, 10.5, 30.5, 30, 180, 360, w=2.8)
        line([(17.5, 20), (17.5, 27.5), (13.5, 30.5), (34.5, 30.5), (30.5, 27.5), (30.5, 20)], w=2.8)
        line([(24, 10.5), (24, 7.8)], w=2.2)
        ell(21.6, 32.1, 26.4, 36.9, fill=acc)
    elif family == "message":
        rrect(7.5, 9.5, 40.5, 32, 8, outline=ink)
        line([(15.5, 31.5), (12.5, 39.5), (21.5, 31.8)], w=2.6)
        for dx_ in (16.8, 24, 31.2):
            ell(dx_ - 2.2, 18.6, dx_ + 2.2, 23, fill=acc)
    elif family == "api":
        line([(17.5, 11.5), (8.5, 24), (17.5, 36.5)], w=3.2)
        line([(30.5, 11.5), (39.5, 24), (30.5, 36.5)], w=3.2)
        line([(27, 13.5), (21, 34.5)], col=ink_soft, w=2.4, ghosted=False)
        ell(21.5, 21.5, 26.5, 26.5, fill=acc)
    elif family == "package":
        rrect(10.5, 18, 37.5, 36.5, 2.5, outline=ink, fill=acc_soft)
        line([(10.5, 18), (37.5, 18)], w=3)
        line([(24, 18), (24, 36.5)], col=ink_soft, w=1.8, ghosted=False)
        line([(17.5, 30.5), (17.5, 25)], col=acc, w=1.9, ghosted=False)
        line([(15.2, 27), (17.5, 24.6), (19.8, 27)], col=acc, w=1.9, ghosted=False)
    elif family == "cloud":
        ell(12.2, 8, 35.8, 30, outline=ink, w=3)
        arc(6, 17, 22, 32.5, 90, 270, w=3)
        arc(27, 15, 43.5, 32.5, 270, 90, w=3)
        line([(14, 31.4), (36, 31.4)], w=3)
        for sx in (17.5, 24, 30.5):
            line([(sx, 35), (sx, 38.6)], col=acc, w=2.4, ghosted=False)
            line([(sx, 40.6), (sx, 42.5)], col=hex_rgba(color, 140), w=2.4, ghosted=False)
    elif family == "server":
        for sy in (9.5, 19.5, 29.5):
            rrect(10.5, sy, 37.5, sy + 9, 2.5, outline=ink, w=2.6)
            ell(31.8, sy + 2.8, 35.2, sy + 6.2, outline=acc, fill=acc_soft, w=1)
            line([(14.5, sy + 4.5), (22.5, sy + 4.5)], col=ink_soft, w=2, ghosted=False)
        ell(31.8, 22.3, 35.2, 25.7, fill=acc)
    elif family == "lock":
        arc(16.5, 7.5, 31.5, 22.5, 180, 360, w=3)
        line([(16.5, 15), (16.5, 21)], w=3)
        line([(31.5, 15), (31.5, 21)], w=3)
        rrect(12.5, 21, 35.5, 37.5, 4, outline=ink, fill=acc_soft)
        ell(21.4, 25.4, 26.6, 30.6, fill=acc)
        line([(24, 29.5), (24, 33)], col=acc, w=2.4, ghosted=False)
    elif family == "user":
        ell(17.8, 9.8, 30.2, 22.2, outline=ink, w=2.8)
        arc(10.5, 26.5, 37.5, 47.5, 180, 360, w=3)
        ell(32.1, 11.1, 36.9, 15.9, fill=acc)
    elif family == "terminal":
        rrect(8.5, 11, 39.5, 37, 3.5, outline=ink)
        line([(8.5, 17.5), (39.5, 17.5)], col=ink_soft, w=1.8, ghosted=False)
        for dx_ in (11.5, 15, 18.5):
            ell(dx_ - 1.1, 13.1, dx_ + 1.1, 15.3, fill=ink_soft)
        line([(12.5, 22.5), (16.5, 25.5), (12.5, 28.5)], col=acc, w=2.2, ghosted=False)
        line([(19.5, 25.5), (30, 25.5)], col=acc, w=2.4, ghosted=False)
        line([(12.5, 32.5), (26, 32.5)], col=ink_soft, w=2.2, ghosted=False)
    elif family == "analytics":
        line([(10.5, 9.5), (10.5, 37), (39.5, 37)], w=2.8)
        for bx, bh in ((15, 10), (22.5, 15), (30, 21)):
            rrect(bx, 37 - bh, bx + 5.2, 37, 1.4, outline=acc, fill=acc_soft, w=1.7)
        line([(13, 30), (20.5, 25), (28, 21), (36.5, 12.5)], col=acc, w=2.2, ghosted=False)
    elif family == "file":
        line([(13, 8.5), (29, 8.5), (35.5, 15), (35.5, 39.5), (13, 39.5), (13, 8.5)], w=2.8)
        line([(29, 8.5), (29, 15), (35.5, 15)], col=ink_soft, w=2.2, ghosted=False)
        for i, (lx, ly) in enumerate(((17.5, 21), (17.5, 26), (17.5, 31))):
            line([(lx, ly), (lx + (9 if i == 2 else 13.5), ly)], col=acc, w=2, ghosted=False)
    elif family == "loop":
        arc(11, 11, 37, 37, -60, 150, w=3)
        arc(11, 11, 37, 37, 120, 330, col=acc, w=3)
        line([(20.5, 8.5), (27, 11.2), (21.5, 15.5)], w=2.8)
        line([(27.5, 39.5), (21, 36.8), (26.5, 32.5)], col=acc, w=2.8, ghosted=False)
        ell(21.9, 21.9, 26.1, 26.1, fill=acc)
    elif family == "decision":
        pts = [P(24, 9.5), P(38.5, 24), P(24, 38.5), P(9.5, 24)]
        draw.polygon(pts, fill=acc_soft)
        line([(24, 9.5), (38.5, 24), (24, 38.5), (9.5, 24), (24, 9.5)], w=2.8)
        line([(2.5, 24), (8, 24)], col=ink_soft, w=2.2, ghosted=False)
        line([(40, 24), (45.5, 24)], col=ink_soft, w=2.2, ghosted=False)
        arc(20.8, 16.6, 27.6, 23.4, 150, 450, col=acc, w=2.2)
        ell(22.8, 28.2, 26, 31.4, fill=acc)
    elif family == "error":
        pts = [P(24, 9), P(41, 36.5), P(7, 36.5)]
        draw.polygon(pts, fill=acc_soft)
        line([(24, 9), (41, 36.5), (7, 36.5), (24, 9)], w=2.8)
        line([(24, 18), (24, 27.5)], col=acc, w=3, ghosted=False)
        ell(22.1, 30.5, 25.9, 34.3, fill=acc)
    elif family == "wait":
        line([(14.5, 9), (33.5, 9)], w=2.8)
        line([(14.5, 39), (33.5, 39)], w=2.8)
        line([(17, 9), (17, 12), (21.5, 20), (22.2, 24), (17, 32), (17, 39)], w=2.6)
        line([(31, 9), (31, 12), (26.5, 20), (25.8, 24), (31, 32), (31, 39)], w=2.6)
        pts = [P(19.2, 13.5), P(28.8, 13.5), P(24, 22)]
        draw.polygon(pts, fill=acc_soft)
        line([(19.2, 13.5), (28.8, 13.5)], col=acc, w=1.8, ghosted=False)
        pts = [P(18.5, 38.4), P(29.5, 38.4), P(24, 31.5)]
        draw.polygon(pts, fill=acc)
    else:  # module: IC chip fallback
        rrect(13, 13, 35, 35, 4.5, outline=ink)
        for v in (17.5, 24, 30.5):
            for pts in (((v, 13), (v, 8.5)), ((v, 35), (v, 39.5)),
                        ((13, v), (8.5, v)), ((35, v), (39.5, v))):
                line(list(pts), col=ink_soft, w=2, ghosted=False)
        rrect(19, 19, 29, 29, 2, outline=acc, fill=acc_soft, w=1.8)
        ell(22.2, 22.2, 25.8, 25.8, fill=acc)
    return True


def draw_svg_icon_tile(ex, draw, kind, x, y, color, scale, plain=False, glyph_color=None, icon_style="outline"):
    icon_name = resolve_icon_name(kind)
    tile = int(round(ICON_TILE * scale))
    pad = int(round((ICON_PAD_PLAIN if plain else ICON_PAD) * scale))
    radius = int(round(11 * scale))
    stroke_color = glyph_color or THEME["white"]

    illustrated = icon_style in ("illustrated", "hero") and not is_custom_icon(kind)
    if not plain:
        # Keep Excalidraw editable with a simple local placeholder while the
        # PNG/GIF use the higher fidelity Tabler SVG asset.
        ex.rect(x + 1 * scale, y + 1 * scale, tile - 2 * scale, tile - 2 * scale, color, THEME["icon_fill"], 1, "solid")
        if not illustrated:
            # The duotone illustrations are plate-free; tile chrome is only
            # for outline glyphs.
            box = (c(x), c(y), c(x + tile), c(y + tile))
            draw.rounded_rectangle(box, radius=c(radius), outline=hex_rgba(color, 150), fill=hex_rgba(THEME["icon_fill"], 170), width=max(1, c(1.25)))
    else:
        # Frameless: no raster chrome, but keep an editable marker in the
        # .excalidraw file so the icon spot is still visible/movable there.
        ex.ellipse(x + tile * 0.16, y + tile * 0.16, tile * 0.68, tile * 0.68, color, "transparent", 1)

    # In browser mode the glyph is stamped per-frame later; only paint the tile.
    if ICON_GLYPH_MODE == "skip" and not is_custom_icon(kind):
        return True

    if icon_style in ("illustrated", "hero") and not is_custom_icon(kind):
        return draw_illustrated_icon_raster(draw, kind, x, y, color, scale, hero=icon_style == "hero")

    icon_size = max(28, int(round((tile - pad * 2) * SCALE)))
    if is_custom_icon(kind):
        icon_img = load_custom_icon_image(custom_icon_path(kind), icon_size)
    else:
        icon_img = load_svg_icon(icon_name, stroke_color, icon_size)
    if icon_img is None:
        return False
    ox = c(x) + (c(tile) - icon_size) // 2
    oy = c(y) + (c(tile) - icon_size) // 2
    draw._image.alpha_composite(icon_img, (ox, oy))
    return True


def load_custom_icon_image(path, size):
    """Rasterize a user-supplied icon for the Pillow pipeline.

    PNG keeps its original colors; SVG is traced as white outline strokes
    (best effort - filled brand marks look best in the browser renderer).
    """
    cache_key = (str(path), size)
    if cache_key in SVG_ICON_CACHE:
        return SVG_ICON_CACHE[cache_key].copy()
    if not path.is_file():
        return None
    rendered = None
    try:
        if path.suffix.lower() == ".png":
            img = Image.open(path).convert("RGBA")
            ratio = min(size / img.width, size / img.height)
            fitted = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                                Image.Resampling.LANCZOS)
            rendered = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            rendered.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
        elif path.suffix.lower() == ".svg" and parse_path is not None:
            rendered = render_svg_outline(path, THEME["white"], size)
    except Exception:
        rendered = None
    if rendered is None:
        return None
    SVG_ICON_CACHE[cache_key] = rendered
    return rendered.copy()


def draw_primitive_icon(ex, draw, kind, x, y, color=None, scale=1.0):
    color = color or THEME["cyan"]
    if kind == "folder":
        draw_line(ex, draw, [(x, y + 9 * scale), (x, y + 35 * scale), (x + 48 * scale, y + 35 * scale), (x + 48 * scale, y + 7 * scale), (x + 26 * scale, y + 7 * scale), (x + 21 * scale, y), (x + 2 * scale, y), (x + 2 * scale, y + 9 * scale)], THEME["white"], 2)
        draw_rect(ex, draw, x + 5 * scale, y + 15 * scale, 38 * scale, 15 * scale, color, color, 1, 3)
    elif kind == "file":
        draw_rect(ex, draw, x + 7 * scale, y, 33 * scale, 36 * scale, THEME["white"], color, 2, 4)
        draw_line(ex, draw, [(x + 15 * scale, y + 14 * scale), (x + 31 * scale, y + 14 * scale)], THEME["bg"], 2)
        draw_line(ex, draw, [(x + 15 * scale, y + 24 * scale), (x + 31 * scale, y + 24 * scale)], THEME["bg"], 2)
    elif kind == "scan":
        draw_ellipse(ex, draw, x + 14, y + 11, 38, 38, THEME["white"], None, 4)
        draw_line(ex, draw, [(x + 47, y + 45), (x + 64, y + 62)], THEME["white"], 5)
    elif kind == "shield":
        pts = [(x + 38, y + 7), (x + 63, y + 17), (x + 58, y + 47), (x + 38, y + 65), (x + 18, y + 47), (x + 13, y + 17)]
        draw.polygon([(c(px), c(py)) for px, py in pts], fill=hex_rgba(THEME["green"], 180), outline=hex_rgba(THEME["white"]))
        draw_line(ex, draw, pts + [pts[0]], THEME["white"], 3)
        draw_line(ex, draw, [(x + 27, y + 37), (x + 36, y + 48), (x + 51, y + 27)], THEME["white"], 4)
    elif kind == "db":
        draw_ellipse(ex, draw, x + 15, y + 9, 50, 17, THEME["white"], color, 2)
        draw_rect(ex, draw, x + 15, y + 17, 50, 37, THEME["white"], color, 2, 0)
        draw_ellipse(ex, draw, x + 15, y + 45, 50, 17, THEME["white"], color, 2)
    elif kind == "hash":
        draw_line(ex, draw, [(x + 27, y + 14), (x + 22, y + 58)], THEME["amber"], 4)
        draw_line(ex, draw, [(x + 50, y + 14), (x + 45, y + 58)], THEME["amber"], 4)
        draw_line(ex, draw, [(x + 15, y + 29), (x + 62, y + 29)], THEME["white"], 4)
        draw_line(ex, draw, [(x + 13, y + 45), (x + 60, y + 45)], THEME["white"], 4)
    elif kind == "package":
        draw_line(ex, draw, [(x + 38, y + 8), (x + 66, y + 23), (x + 66, y + 52), (x + 38, y + 68), (x + 10, y + 52), (x + 10, y + 23), (x + 38, y + 8)], THEME["white"], 3)
        draw_line(ex, draw, [(x + 10, y + 23), (x + 38, y + 38), (x + 66, y + 23)], THEME["amber"], 3)
        draw_line(ex, draw, [(x + 38, y + 38), (x + 38, y + 68)], THEME["amber"], 3)
    else:
        draw_ellipse(ex, draw, x + 18, y + 18, 36, 36, color, color, 2)


def icon(ex, draw, kind, x, y, color=None, scale=1.0, plain=False, glyph_color=None,
         icon_style="outline", icon_motion="auto", icon_size="standard"):
    global OPS_SINK
    color = color or THEME["cyan"]
    icon_name = resolve_icon_name(kind)
    custom = is_custom_icon(kind)
    # Formal mode drops the tinted icon tile chrome entirely — plate-free
    # glyphs read cleaner in business documents. Sketch mode keeps the plate.
    if not SKETCH:
        plain = True
    if custom or (TABLER_ICON_DIR / f"{icon_name}.svg").is_file():
        # One semantic op fully describes the tile for the browser renderer;
        # suppress the raster fallback's primitive ops to avoid duplicates.
        op = {"op": "icon", "name": icon_name, "semantic": str(kind), "x": x, "y": y,
              "tile": int(round(ICON_TILE * scale)),
              "pad": int(round((ICON_PAD_PLAIN if plain else ICON_PAD) * scale)),
              "radius": int(round(11 * scale)), "accent": color,
              "glyph": glyph_color or THEME["white"], "fill": THEME["icon_fill"],
              "iconStyle": icon_style, "iconMotion": icon_motion, "iconSize": icon_size}
        if custom:
            op["custom"] = True
            op["file"] = str(custom_icon_path(kind))
        if plain:
            op["plain"] = True
        ops_record(op)
        saved, OPS_SINK = OPS_SINK, None
        try:
            if not draw_svg_icon_tile(ex, draw, kind, x, y, color, scale, plain=plain, glyph_color=glyph_color, icon_style=icon_style):
                draw_primitive_icon(ex, draw, kind, x, y, color, scale)
        finally:
            OPS_SINK = saved
        return
    if draw_svg_icon_tile(ex, draw, kind, x, y, color, scale, plain=plain, glyph_color=glyph_color, icon_style=icon_style):
        return  # pragma: no cover - tabler-backed kinds take the first branch; others fail to None
    draw_primitive_icon(ex, draw, kind, x, y, color, scale)


def icon_presentation(item, default_style="outline"):
    """Extract optional high-fidelity icon presentation fields from a spec item."""
    item = item or {}
    return {
        "icon_style": item.get("icon_style", default_style),
        "icon_motion": item.get("icon_motion", "auto"),
        "icon_size": item.get("icon_size", "standard"),
    }


# The classic "@diagramforge" signature is drawn with its right edge flush at
# x=1180; longer signatures shift the whole brand block left (so nothing clips
# at the canvas edge) and stretch the hand-drawn underline to match the text.
SIGNATURE_X = 994
SIGNATURE_RIGHT_LIMIT = 1180
SIGNATURE_UNDERLINE_REF = 186.0


def signature_text_width(draw, text):
    font = load_font(24, cjk=True, bold=True, text=text)
    lines = str(text).splitlines() or [""]
    return max(draw.textlength(line, font=font) for line in lines) / SCALE


def custom_image(ex, draw, path, x, y, w, h):
    """A user image (brand logo etc.) fitted into a w x h box, aspect kept.

    Records an 'image' op for the browser renderer and pastes a raster
    letterboxed copy for the Pillow pipeline. Returns False when the file
    cannot be rasterized locally (caller may fall back to text)."""
    path = Path(str(path))
    ops_record({"op": "image", "name": f"img:{path}", "file": str(path),
                "x": x, "y": y, "w": w, "h": h})
    ex.rect(x, y, w, h, THEME["frame"], "transparent", 1, "solid")
    img = None
    try:
        if path.suffix.lower() == ".png" and path.is_file():
            img = Image.open(path).convert("RGBA")
        elif path.suffix.lower() == ".svg" and path.is_file() and parse_path is not None:
            img = render_svg_outline(path, THEME["white"], c(min(w, h)))
    except Exception:
        img = None
    if img is None:
        return False
    bw, bh = c(w), c(h)
    ratio = min(bw / img.width, bh / img.height)
    fitted = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                        Image.Resampling.LANCZOS)
    draw._image.alpha_composite(fitted, (c(x) + (bw - fitted.width) // 2, c(y) + (bh - fitted.height) // 2))
    return True


def draw_signature(ex, draw, text, x, y, stretch=1.0):
    if SKETCH:
        ops_record({"op": "signature", "text": str(text), "x": x, "y": y, "stretch": round(stretch, 3),
                    "layers": [[-1, 1, THEME["purple"], 165], [1, -1, THEME["cyan"], 135], [0, 0, THEME["white"], 245]],
                    "underline": THEME["purple"], "underline2": THEME["white"]})
        ex.text(text, x, y, int(round(120 * stretch)), 36, 23, THEME["white"], align="left")
        font = load_font(24, cjk=True, bold=True, text=text)
        sx, sy = c(x), c(y)
        k = stretch
        for dx, dy, color, alpha in [(-1, 1, THEME["purple"], 165), (1, -1, THEME["cyan"], 135), (0, 0, THEME["white"], 245)]:
            draw.text((sx + c(dx), sy + c(dy)), text, font=font, fill=hex_rgba(color, alpha))
        draw.line([(sx + c(6 * k), sy + 56), (sx + c(28 * k), sy + 61), (sx + c(62 * k), sy + 58), (sx + c(86 * k), sy + 63)],
                  fill=hex_rgba(THEME["purple"], 170), width=3)
        draw.line([(sx + c(8 * k), sy + 54), (sx + c(84 * k), sy + 60)], fill=hex_rgba(THEME["white"], 125), width=1)
    else:
        # Formal signature: one quiet sans line (e.g. a company attribution),
        # no layered ghost strokes and no hand-drawn underline.
        ops_record({"op": "signature", "text": str(text), "x": x, "y": y, "stretch": 1.0,
                    "layers": [[0, 0, THEME["muted"], 230]], "underline": None, "underline2": None})
        font = load_font(16, cjk=True, bold=False, text=text)
        sx, sy = c(x), c(y)
        draw.text((sx, sy), text, font=font, fill=hex_rgba(THEME["muted"], 230))


def brand(ex, draw, signature, width=1210):
    text = str(signature or "").strip()
    if not text:
        return  # no signature configured: no text, no decorative dots
    dx = width - 1210  # brand block stays flush to the right frame on any canvas
    w_text = signature_text_width(draw, text)
    shift = max(0, int(round(SIGNATURE_X + w_text - SIGNATURE_RIGHT_LIMIT)))
    stretch = max(1.0, min(3.0, w_text / SIGNATURE_UNDERLINE_REF))
    if SKETCH:
        dots = [
            (0, 0, THEME["cyan"]),
            (10, 8, THEME["white"]),
            (0, 16, THEME["purple"]),
            (10, 24, THEME["white"]),
            (20, 0, THEME["white"]),
            (30, 8, THEME["pink"]),
            (20, 16, THEME["white"]),
            (30, 24, THEME["green"]),
        ]
        for ddx, ddy, color in dots:
            draw_ellipse(ex, draw, 955 + dx - shift + ddx, 143 + ddy, 5, 5, color, color, 1)
        draw_signature(ex, draw, text, SIGNATURE_X + dx - shift, 135, stretch)
    else:
        # Formal: right-align the quiet signature to the same frame edge.
        x = SIGNATURE_RIGHT_LIMIT + dx - w_text
        ex.text(text, x, 152, int(round(w_text)), 24, 16, THEME["muted"], align="left")
        draw_signature(ex, draw, text, x, 152)


def small_input(ex, draw, x, y, item, plain=False):
    kind = item.get("icon", "file")
    color = item.get("color", THEME["cyan"])
    # Plain style: no tile chrome, glyph strokes take the item's accent color
    # (custom icons keep their own colors either way).
    icon(ex, draw, kind, x + 9, y, color, 1.0, plain=plain, glyph_color=color if plain else None,
         **icon_presentation(item))
    draw_text(ex, draw, item.get("label", ""), x - 5, y + 54, 78, 22, 12, THEME["white"], "center", fit=True, min_size=8)


def core_card(ex, draw, x, y, card, w=260):
    # Text boxes scale with the card; ratios reproduce the legacy w=260 offsets.
    draw_rect(ex, draw, x, y, w, 90, THEME["core_stroke"], THEME["blue_fill"], 2, RADIUS_MD)
    hero = card.get("icon_size") == "hero" or card.get("icon_style") == "hero"
    icon(ex, draw, card.get("icon", "file"), x + (7 if hero else 14), y + (5 if hero else 13),
         card.get("color", THEME["cyan"]), scale=1.38 if hero else 1.0, **icon_presentation(card))
    draw_text(ex, draw, card.get("title", ""), x + round(w * 0.423), y + 11, round(w * 0.385), 28, 20, THEME["white"], "center", hand=True, bold=True, fit=True, min_size=15)
    draw_text(ex, draw, card.get("body", ""), x + round(w * 0.354), y + 42, round(w * 0.577), 38, 14, THEME["white"], "center", spacing=3, fit=True, min_size=11)


def mini_card(ex, draw, x, y, w, h, card, stroke, fill):
    draw_rect(ex, draw, x, y, w, h, stroke, fill, 2, RADIUS_MD)
    icon(ex, draw, card.get("icon", "file"), x + 10, y + 10, card.get("color", THEME["cyan"]), **icon_presentation(card))
    draw_text(ex, draw, card.get("title", ""), x + 78, y + 12, 115, 24, 17, THEME["white"], "left", bold=True, fit=True, min_size=12)
    draw_text(ex, draw, card.get("body", ""), x + 78, y + 38, w - 92, h - 43, 12, THEME["white"], "left", spacing=3, fit=True, min_size=10)


def pack_row(ex, draw, x, y, card):
    draw_rect(ex, draw, x, y, 228, 84, THEME["green"], THEME["pack_card_fill"], 2, RADIUS_MD)
    icon(ex, draw, card.get("icon", "file"), x + 12, y + 10, card.get("color", THEME["cyan"]), **icon_presentation(card))
    draw_text(ex, draw, card.get("title", ""), x + 86, y + 12, 120, 25, 17, THEME["white"], "center", bold=True, fit=True, min_size=12)
    draw_text(ex, draw, card.get("body", ""), x + 80, y + 42, 135, 30, 12, THEME["white"], "center", spacing=3, fit=True, min_size=10)


def draw_chrome(ex, draw, spec, plan):
    """Shared title block, outer frame and brand signature for every layout."""
    title = spec.get("title", {})
    draw_line(ex, draw, [(29, 31), (29, 78)], THEME["purple"], 11)
    draw_text(ex, draw, title.get("prefix", "The internals of"), 45, 14, 535, 66, 47, THEME["white"], "left", hand=True, bold=True)
    draw_rect(ex, draw, 600, 27, 392, 72, THEME["highlight"], THEME["highlight"], 2, RADIUS_FRAME)
    draw_text(ex, draw, title.get("highlight", "Memory Pack"), 622, 19, 350, 76, 44, THEME["green"], "center", hand=True, bold=True)
    draw_text(ex, draw, title.get("subtitle", ""), 104, 90, 420, 25, 15, THEME["muted"], "left")
    fx, fy, fw, fh = plan["frame"]
    draw_rect(ex, draw, fx, fy, fw, fh, THEME["frame"], None, 2, RADIUS_FRAME)
    # Formal output carries no branding by default; sketch mode keeps the
    # classic "@diagramforge" brand block. An explicit spec signature always
    # wins (e.g. a company attribution on a formal diagram).
    brand(ex, draw, spec.get("signature", "@diagramforge" if SKETCH else ""), plan["canvas"]["width"])


def render_panorama(ex, draw, spec, plan):
    inputs_plan = plan["inputs"]
    draw_rect(ex, draw, *inputs_plan["box"], THEME["green"], None, 2, RADIUS_MD)
    box_cx = inputs_plan["box"][0] + inputs_plan["box"][2] / 2
    draw_text(ex, draw, spec.get("input_title", "Source / Input"), box_cx - 106, 137, 210, 28, 22, THEME["white"], "center", hand=True, bold=True)
    plain_inputs = spec.get("input_style", "boxed") == "plain"
    for x, item in zip(inputs_plan["xs"], inputs_plan["items"]):
        small_input(ex, draw, x, 174, item, plain=plain_inputs)
    acx = inputs_plan["arrow_cx"]
    draw_line(ex, draw, [(acx, 258), (acx, 316)], THEME["white"], 2, "solid", True)

    core = spec.get("core", {})
    core_plan = plan["core"]
    card_w = core_plan["w"]
    draw_rect(ex, draw, *core_plan["group"], THEME["core_stroke"], THEME["core_fill"], 2, RADIUS_FRAME)
    draw_text(ex, draw, core.get("title", "Archive Core"), 462, 327, 210, 31, 22, THEME["white"], "center", hand=True, bold=True)
    draw_text(ex, draw, core.get("subtitle", "(local read-only pipeline)"), 635, 336, 220, 23, 13, THEME["white"], "center")
    for i, (x, card) in enumerate(zip(core_plan["xs"], core_plan["cards"])):
        core_card(ex, draw, x, 366, card, w=card_w)
        if i:
            draw_line(ex, draw, [(core_plan["xs"][i - 1] + card_w, 411), (x, 411)], THEME["white"], 2, "solid", True)
    last_cx = core_plan["last_cx"]
    draw_line(ex, draw, [(last_cx, 456), (last_cx, 481), (768, 481), (768, 508)], THEME["white"], 2, "solid", True)

    decision = spec.get("decision", {"title": "Ready?", "body": "safe, traced\nusable"})
    draw_diamond(ex, draw, 706, 508, 120, 120, THEME["green"], THEME["decision_fill"], 2)
    draw_text(ex, draw, decision.get("title", "Ready?"), 728, 541, 78, 26, 20, THEME["white"], "center", fit=True, min_size=14)
    draw_text(ex, draw, decision.get("body", ""), 728, 569, 78, 34, 14, THEME["white"], "center", fit=True, min_size=10)
    draw_rect(ex, draw, 1022, 527, 100, 94, THEME["core_stroke"], THEME["blue_fill"], 2, RADIUS_MD)
    icon(ex, draw, spec.get("output", {}).get("icon", "file"), 1035, 537, THEME["cyan"], **icon_presentation(spec.get("output", {})))
    draw_text(ex, draw, spec.get("output", {}).get("label", "Report"), 1038, 588, 70, 24, 18, THEME["white"], "center", bold=True, fit=True, min_size=12)
    draw_line(ex, draw, [(826, 568), (1022, 568)], THEME["white"], 2, "solid", True)
    draw_text(ex, draw, decision.get("yes_label", "Yes"), 877, 543, 91, 25, 15, THEME["white"], "center", fit=True, min_size=10)
    loop_x = core_plan["first_loop_x"]
    draw_line(ex, draw, [(707, 568), (510, 568), (loop_x, 568), (loop_x, 456)], THEME["muted"], 2, "dashed", True)
    draw_text(ex, draw, spec.get("loop_label", "Loop until checked and updated"), 330, 504, 540, 25, 14, THEME["white"], "center")
    draw_text(ex, draw, spec.get("retry_label", "No / missing source or conflict"), 475, 580, 250, 24, 14, THEME["white"], "center")

    panels = plan["panels"]
    present = panels["present"]
    px = panels["x"]

    if "left_panel" in present:
        lx = px["left_panel"]
        left = spec.get("left_panel", {})
        draw_line(ex, draw, [(lx + 117, 637), (lx + 117, 736)], THEME["white"], 2, "solid", True)
        draw_line(ex, draw, [(lx + 166, 736), (lx + 166, 637)], THEME["white"], 2, "solid", True)
        draw_text(ex, draw, left.get("down_label", "Read"), lx + 40, 677, 105, 22, 16, THEME["white"], "center", fit=True, min_size=10)
        draw_text(ex, draw, left.get("up_label", "Context"), lx + 169, 676, 76, 22, 16, THEME["white"], "center", fit=True, min_size=10)
        draw_rect(ex, draw, lx, 735, 281, 344, THEME["green"], THEME["source_fill"], 2, RADIUS_LG)
        draw_text(ex, draw, left.get("title", "Memory Sources"), lx + 19, 752, 180, 30, 22, THEME["white"], "left", hand=True, bold=True)
        if left.get("badge_file"):
            custom_image(ex, draw, left["badge_file"], lx + 192, 758, 76, 28)
        else:
            draw_text(ex, draw, left.get("badge", "read only"), lx + 205, 779, 62, 18, 11, THEME["green"], "center")
        for (y, h), card in zip(graph_model.LEFT_CARD_SLOTS, left.get("cards", [])[:3]):
            mini_card(ex, draw, lx + 12, y, 258, h, card, THEME["green"], THEME["src_card_fill"])

    if "center_panel" in present:
        cx0 = px["center_panel"]
        center = spec.get("center_panel", {})
        draw_rect(ex, draw, cx0, 734, 522, 346, THEME["purple"], THEME["archive_fill"], 2, RADIUS_LG)
        draw_text(ex, draw, center.get("title", "Archive Layers"), cx0 + 179, 756, 180, 34, 23, THEME["white"], "center", hand=True, bold=True)
        draw_text(ex, draw, center.get("subtitle", "(local, readable, traceable storage)"), cx0 + 111, 790, 300, 24, 14, THEME["white"], "center")
        layer_xs = panels["layer_xs"]
        layer_cards = list(center.get("cards", []))[:4]
        while len(layer_cards) < len(layer_xs):
            layer_cards.append({"title": "", "body": "", "icon": "file"})
        for i, (x, card) in enumerate(zip(layer_xs, layer_cards)):
            draw_rect(ex, draw, x, 827, 112, 142, THEME["purple"], THEME["layer_card_fill"], 2, RADIUS_MD)
            icon(ex, draw, card.get("icon", "file"), x + 18, 840, card.get("color", THEME["cyan"]), **icon_presentation(card))
            draw_text(ex, draw, card.get("title", ""), x + 10, 910, 92, 25, 18, THEME["white"], "center", bold=True, fit=True, min_size=12)
            draw_text(ex, draw, card.get("body", ""), x + 8, 936, 96, 28, 11, THEME["white"], "center", spacing=2, fit=True, min_size=8)
            if i:
                draw_line(ex, draw, [(layer_xs[i - 1] + 112, 890), (x, 890)], THEME["white"], 2, "solid", True)
        draw_rect(ex, draw, cx0 + 158, 1010, 220, 50, THEME["purple"], THEME["archive_fill"], 2, RADIUS_MD)
        draw_text(ex, draw, center.get("footer", "Redact + Dedup"), cx0 + 195, 1017, 165, 33, 20, THEME["white"], "center", hand=True, bold=True, fit=True, min_size=14)
        draw_line(ex, draw, [(cx0 + 270, 969), (cx0 + 270, 1010)], THEME["muted"], 2, "dashed", True)

    if "right_panel" in present:
        rx = px["right_panel"]
        right = spec.get("right_panel", {})
        if "center_panel" in present:
            c_right = px["center_panel"] + 522
            draw_line(ex, draw, [(c_right, 890), (rx, 890)], THEME["white"], 2, "solid", True)
            draw_text(ex, draw, right.get("incoming_label", "Compile"), rx - 54, 868, 65, 20, 12, THEME["white"], "center")
        draw_rect(ex, draw, rx, 735, 258, 344, THEME["green"], THEME["pack_fill"], 2, RADIUS_LG)
        draw_text(ex, draw, right.get("title", "Memory Pack"), rx + 44, 750, 170, 34, 22, THEME["white"], "center", hand=True, bold=True)
        for y, card in zip(graph_model.PACK_YS, right.get("cards", [])[:3]):
            pack_row(ex, draw, rx + 14, y, card)
        draw_line(ex, draw, [(rx + 132, 735), (rx + 132, 691), (766, 691), (766, 628)], THEME["white"], 2, "solid", True)
        draw_text(ex, draw, right.get("return_label", "Reusable"), 867, 669, 75, 23, 16, THEME["white"], "center")

    plus_marks = [(375, 292, THEME["cyan"]), (704, 293, THEME["green"]), (1048, 292, THEME["purple"])]
    if present:
        plus_marks += [(315, 707, THEME["green"]), (868, 707, THEME["purple"])]
    for x, y, color in plus_marks:
        draw_line(ex, draw, [(x - 8, y), (x + 8, y)], color, 2)
        draw_line(ex, draw, [(x, y - 8), (x, y + 8)], color, 2)


def render_swimlane(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    lanes = plan["lanes"]
    col_w = lanes.get("column_w", 178)
    # Lane bands + title columns first; step cards are painted last so
    # connector strokes never run over them (edges-under-nodes, like graph).
    for i, lane in enumerate(lanes["items"]):
        y, lane_h = lane["_y"], lane["_h"]
        tint = lane.get("_tint") or {"stroke": "green", "band": "source_fill", "column": "green_fill"}
        stroke = THEME[tint["stroke"]]
        draw_rect(ex, draw, lanes["x"], y, lanes["w"], lane_h, stroke, THEME[tint["band"]], 2, RADIUS_LG)
        # Darker title column on the left (reference style), then title + subtitle.
        draw_rect(ex, draw, lanes["x"], y, col_w, lane_h, stroke, THEME[tint["column"]], 1.5, RADIUS_LG)
        title_h = 40 if lane.get("subtitle") else 74
        draw_text(ex, draw, lane.get("title", ""), lanes["x"] + 18, y + (18 if lane.get("subtitle") else 24),
                  col_w - 34, title_h, 22, THEME["white"], "left", hand=True, bold=True, fit=True, min_size=14)
        if lane.get("subtitle"):
            draw_text(ex, draw, lane.get("subtitle", ""), lanes["x"] + 18, y + 62, col_w - 34, lane_h - 74, 13,
                      THEME["muted"], "left", spacing=2, fit=True, min_size=9)
        if lane.get("caption"):
            # Full-width caption row under the step cards (reference-diagram style).
            draw_text(ex, draw, lane["caption"], lanes["x"] + col_w + 20, y + lane_h - 30,
                      lanes["w"] - col_w - 60, 20, 12, THEME["muted"], "center", fit=True, min_size=9)
    for edge in plan["edges"]:
        pts = [tuple(p) for p in edge["points"]]
        color = THEME.get(edge.get("color"), THEME["muted"])
        draw_line(ex, draw, pts, color, 2, edge.get("style", "solid"), True)
        if edge.get("label"):
            align = "center"
            if edge.get("label_pos"):
                lx, ly, lw = edge["label_pos"]
            else:
                mx, my, horiz = _edge_label_anchor(pts)
                if edge.get("loop"):
                    lw, ly = 260, my - 26
                elif horiz and abs(pts[0][1] - pts[-1][1]) < 4:
                    # Straight in-lane hop: the gap is narrow, so lift the label
                    # into the empty strip above the cards (arrow y = card center).
                    lw, ly = 150, my - 59
                elif horiz:
                    lw, ly = 200, my - 26
                else:
                    # Vertical run: label sits beside the line, not on it.
                    lw, ly, align = 120, my - 9, "left"
                lx = mx + EDGE_LABEL_GAP if align == "left" else mx - lw / 2
            if edge.get("badge"):
                ly -= 16  # keep the label clear of the numbered badge on the line
            # Keep the label off any step card it would overlap.
            for lane in plan.get("lanes", {}).get("items", []):
                for step in lane.get("steps", []):
                    sx, sy, sw, sh = step["_box"]
                    if lx < sx + sw and lx + lw > sx and ly < sy + sh and ly + 18 > sy:
                        ly = sy - 24
                        break
            draw_text(ex, draw, edge["label"], lx, ly, lw, 18, 12,
                      THEME["muted"], align, fit=True, min_size=9, mask=True, role="edge-label")
        if edge.get("badge"):
            mx, my, _horiz = _edge_label_anchor(pts)
            draw_edge_badge(ex, draw, edge["badge"], mx, my, color)
    for lane in lanes["items"]:
        y = lane["_y"]
        tint = lane.get("_tint") or {"stroke": "green", "band": "source_fill", "column": "green_fill"}
        stroke = THEME[tint["stroke"]]
        for step in lane.get("steps", []):
            x, sy, w, h = step["_box"]
            draw_rect(ex, draw, x, sy, w, h, stroke, THEME["icon_fill"], 1.5, RADIUS_MD)
            icon(ex, draw, step.get("icon", "file"), x + 9, sy + 15, step.get("color", THEME["cyan"]), **icon_presentation(step))
            draw_text(ex, draw, step.get("title", ""), x + 66, sy + 10, w - 74, 58, 15, THEME["white"], "left", bold=True, fit=True, min_size=9)
            if step.get("note"):
                draw_text(ex, draw, step["note"], x + 2, sy + 84, w - 4, 14, 10,
                          THEME["muted"], "center", fit=True, min_size=7)
    draw_legend(ex, draw, spec, plan)


def _edge_label_anchor(points):
    """Midpoint of the longest segment: labels sit on the calm lane run, not
    on the short stubs that leave/enter a node."""
    best, best_len = None, -1
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if seg > best_len:
            best_len = seg
            best = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, abs(b[0] - a[0]) >= abs(b[1] - a[1]))
    return best


def _solid_segs_drawn():
    """Solid connector segments already recorded in the op stream. Edge labels
    are drawn after their lines (two-pass painters draw them after all lines),
    so this is the full obstacle field a label mask must keep clear of."""
    segs = []
    if OPS_SINK:
        for op in OPS_SINK:
            if op.get("op") == "line" and op.get("style", "solid") == "solid":
                pts = op.get("points", [])
                segs.extend((tuple(a), tuple(b)) for a, b in zip(pts, pts[1:]))
    return segs


def _mask_clearance(mx0, my0, mw, mh, segs):
    """Min distance from a candidate mask rect to any solid segment."""
    x0, y0, x1, y1 = mx0, my0, mx0 + mw, my0 + mh
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    best = math.inf
    for a, b in segs:
        # Quick reject: segment bbox far from the rect.
        if max(a[0], b[0]) < x0 - 60 or min(a[0], b[0]) > x1 + 60:
            continue
        if max(a[1], b[1]) < y0 - 60 or min(a[1], b[1]) > y1 + 60:
            continue
        if (x0 < a[0] < x1 and y0 < a[1] < y1) or (x0 < b[0] < x1 and y0 < b[1] < y1):
            return 0.0
        hit = False
        for c1, c2 in edges:
            if _segs_cross(a, b, c1, c2):
                hit = True
                break
        if hit:
            return 0.0
        for c in corners:
            best = min(best, _pt_seg_dist(c, a, b))
        for c1, c2 in edges:
            best = min(best, _pt_seg_dist(a, c1, c2), _pt_seg_dist(b, c1, c2))
    return best


def _segs_cross(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 != o2 and o3 != o4


def _pt_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def draw_edge_label(ex, draw, text, mx, my, horiz, lw=120, lh=20, size=12, color=None, min_size=9, dy=0):
    """Edge label kept off its own connector: centered above a horizontal run,
    to the right of a vertical run, with EDGE_LABEL_GAP of visible line
    between the mask chip and the stroke. When the default spot collides with
    another solid connector, the label is nudged along the run until its mask
    clears every line drawn so far. Returns the (x, y) used."""
    color = color or THEME["white"]
    if horiz:
        lw0, align = lw, "center"
        base = (mx - lw / 2, my - EDGE_LABEL_GAP - lh + dy)
    else:
        lw0, align = min(lw, 120), "left"
        # The snug mask pads the glyphs by 6px on each side; add it to the
        # offset so the *mask*, not just the text, keeps EDGE_LABEL_GAP clear.
        base = (mx + EDGE_LABEL_GAP + 6, my - lh / 2 + dy)
    lx, ly = base
    # Measure the snug mask (not the layout box) so the clearance check
    # matches what actually gets painted.
    ftext, _fsize, font = fit_text(draw, text, lw0, lh, size, min_size=min_size)
    tw, th = text_size(draw, ftext, font, spacing=3)
    segs = _solid_segs_drawn()
    if segs and ftext:
        def mask_at(cx, cy):
            # Predict post-snap geometry: draw_text snaps the box to the 4px
            # grid before measuring, so the estimate must snap the same way.
            scx, scy, sw, sh = snap4(cx), snap4(cy), snap4(lw0), snap4(lh)
            tx = scx + (sw - tw) / 2 if align == "center" else scx
            ty = scy + (sh - th) / 2
            return tx - 6, ty - 3, tw + 12, th + 6

        shifts = [0]
        for k in range(1, 7):
            shifts += [-8 * k, 8 * k]
        best_pos, best_clear = (lx, ly), -1
        for s in shifts:
            cand = (lx + s, ly) if horiz else (lx, ly + s)
            clear = _mask_clearance(*mask_at(*cand), segs)
            if clear >= 6:
                best_pos, best_clear = cand, clear
                break
            if clear > best_clear:
                best_pos, best_clear = cand, clear
        lx, ly = best_pos
    draw_text(ex, draw, text, lx, ly, lw0, lh, size, color, align, fit=True, min_size=min_size,
              mask=True, role="edge-label")
    return lx, ly


def draw_cardinality_label(ex, draw, text, pts, from_end, lw=26, size=12, min_size=9):
    """Cardinality tag (1, N, M…) beside a relation endpoint, placed on the
    side of the line AWAY from the elbow turn so the riser never crosses the
    tag. ``pts`` is the full routed path; ``from_end`` picks which endpoint."""
    p = pts[0] if from_end else pts[-1]
    corner = pts[1] if from_end else pts[-2]
    dx, dy = corner[0] - p[0], corner[1] - p[1]
    nxt = (pts[2] if from_end else pts[-3]) if len(pts) > 2 else None
    if abs(dx) >= abs(dy):
        # Horizontal leave/arrive: sit on the side opposite the vertical turn.
        turn_up = nxt is not None and (nxt[1] - corner[1]) < 0
        ly = p[1] + 8 if turn_up else p[1] - 26
        if from_end:
            # Label just outside the source box, on the leaving side.
            lx = p[0] + (10 if dx >= 0 else -34)
        else:
            # Label on the approach side of the destination endpoint — the
            # other side is inside the destination box.
            lx = p[0] + (12 if dx >= 0 else -38)
    else:
        # Vertical leave/arrive: sit beside the endpoint, opposite the turn.
        turn_right = nxt is None or (nxt[0] - corner[0]) > 0
        ly = p[1] - 26
        lx = p[0] + (-34 if turn_right else 10)
    segs = _solid_segs_drawn()
    if segs:
        ftext, _fsize, font = fit_text(draw, text, lw, 18, size, min_size=min_size)
        tw, th = text_size(draw, ftext, font, spacing=3)
        if ftext:
            def mask_at(cx):
                tx = cx + (lw - tw) / 2
                ty = ly + (18 - th) / 2
                return tx - 6, ty - 3, tw + 12, th + 6

            best_lx, best_clear = lx, -1
            for s in [0, -8, 8, -16, 16, -24, 24]:
                clear = _mask_clearance(*mask_at(lx + s), segs)
                if clear >= 6:
                    best_lx, best_clear = lx + s, clear
                    break
                if clear > best_clear:
                    best_lx, best_clear = lx + s, clear
            lx = best_lx
    draw_text(ex, draw, text, lx, ly, lw, 18, size, THEME["muted"], "center",
              fit=True, min_size=min_size, mask=True, role="edge-label")


def draw_edge_badge(ex, draw, badge, mx, my, color):
    """Numbered step badge: small filled circle centered on the edge midpoint."""
    r = 11
    draw_ellipse(ex, draw, mx - r, my - r, 2 * r, 2 * r, color, color, 1)
    draw_text(ex, draw, str(badge), mx - r, my - r, 2 * r, 2 * r, 12, "#ffffff",
              "center", bold=True, spacing=0, wrap=False)


def draw_legend(ex, draw, spec, plan):
    """Bottom-right legend row inside the frame: colored dot + label items."""
    legend = spec.get("legend") or []
    if not legend:
        return
    fx, fy, fw, fh = plan["frame"]
    widths = [34 + len(str(item.get("label", ""))) * 7 for item in legend[:6]]
    x = fx + fw - 24 - sum(widths)
    y = fy + fh - 40
    for item, iw in zip(legend[:6], widths):
        color = THEME.get(item.get("color"), THEME["muted"])
        draw_ellipse(ex, draw, x, y + 3, 12, 12, color, color, 1)
        draw_text(ex, draw, str(item.get("label", "")), x + 18, y - 2, iw - 18, 20, 11,
                  THEME["muted"], "left", fit=True, min_size=8)
        x += iw


def render_grid(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    for cell in plan["grid"]["items"]:
        x, y, w, h = cell["_box"]
        tint = cell.get("_tint") or {"stroke": "green", "band": "source_fill", "column": "green_fill"}
        stroke = THEME[tint["stroke"]]
        draw_rect(ex, draw, x, y, w, h, stroke, THEME[tint["band"]], 2, RADIUS_LG)
        draw_text(ex, draw, cell.get("title", ""), x + 18, y + 10, w - 36, 30, 19,
                  THEME["white"], "left", hand=True, bold=True, fit=True, min_size=12)
        for step in cell.get("steps", []):
            sx, sy, sw, sh = step["_box"]
            draw_rect(ex, draw, sx, sy, sw, sh, stroke, THEME["icon_fill"], 1.5, RADIUS_MD)
            # Narrow catalog chips: icon centered on top, label below (like
            # the graph layout's narrow-card treatment).
            icon(ex, draw, step.get("icon", "file"), sx + (sw - 50) // 2, sy + 8,
                 step.get("color", THEME["cyan"]), **icon_presentation(step))
            draw_text(ex, draw, step.get("title", ""), sx + 4, sy + 54, sw - 8, 30, 12,
                      THEME["white"], "center", bold=True, fit=True, min_size=8)
    for edge in plan["edges"]:
        pts = [tuple(p) for p in edge["points"]]
        draw_line(ex, draw, pts, THEME["muted"], 2, "solid", True)
    draw_legend(ex, draw, spec, plan)


def render_graph(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")

    for grp in plan.get("graph_groups", []):
        gx, gy, gw, gh = grp["box"]
        draw_rect(ex, draw, gx, gy, gw, gh, THEME["muted"], None, 1.5, RADIUS_LG, "dashed")
        if grp.get("label"):
            draw_text(ex, draw, grp["label"], gx + 16, gy + 5, gw - 32, 22, 14,
                      THEME["muted"], "left", hand=True, bold=True, fit=True, min_size=10)

    for edge in plan["graph_edges"]:
        pts = [tuple(p) for p in edge["points"]]
        color = THEME.get(edge.get("color"), THEME["muted"])
        draw_line(ex, draw, pts, color, 2, edge.get("style", "solid"), True)

    for g in plan["graph_nodes"]:
        x, y, w, h = g["_box"]
        stroke, fill = THEME[g["_accent"]], THEME[g["_fill"]]
        kind = g["_kind"]
        if kind == "decision":
            draw_diamond(ex, draw, x, y, w, h, stroke, THEME["decision_fill"], 2)
            draw_text(ex, draw, g.get("label", ""), x + 18, y + h / 2 - 22, w - 36, 26, 18,
                      THEME["white"], "center", hand=True, bold=True, fit=True, min_size=11)
            draw_text(ex, draw, g.get("body", ""), x + 20, y + h / 2 + 6, w - 40, 26, 12,
                      THEME["muted"], "center", fit=True, min_size=8)
            continue
        if kind == "terminal":
            draw_rect(ex, draw, x, y, w, h, stroke, THEME["icon_fill"], 2, min(w, h) // 2)
            draw_text(ex, draw, g.get("label", ""), x + 14, y, w - 28, h, 17,
                      THEME["white"], "center", hand=True, bold=True, fit=True, min_size=11)
            continue
        if kind == "circle":
            side = min(w, h)
            cx, cy = x + (w - side) / 2, y + (h - side) / 2
            draw_ellipse(ex, draw, cx, cy, side, side, stroke, fill, 2)
            draw_text(ex, draw, g.get("label", ""), cx + 8, cy + 8, side - 16, side - 16, 14,
                      THEME["white"], "center", hand=True, bold=True, fit=True, min_size=9)
            continue
        draw_rect(ex, draw, x, y, w, h, stroke, fill, 2, RADIUS_LG)
        icon_xy = g.get("_icon_xy")
        if icon_xy and w < 150:  # narrow card: icon on top, label under it
            icon(ex, draw, g["icon"], icon_xy[0], icon_xy[1], g.get("color", THEME["cyan"]), **icon_presentation(g))
            draw_text(ex, draw, g.get("label", ""), x + 6, icon_xy[1] + 62, w - 12, 24, 15,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
        elif icon_xy:
            icon(ex, draw, g["icon"], icon_xy[0], icon_xy[1], g.get("color", THEME["cyan"]), **icon_presentation(g))
            tx = icon_xy[0] + 70
            if g.get("body"):
                draw_text(ex, draw, g.get("label", ""), tx, y + 12, x + w - tx - 10, 26, 17,
                          THEME["white"], "left", hand=True, bold=True, fit=True, min_size=11)
                draw_text(ex, draw, g.get("body", ""), tx, y + 40, x + w - tx - 10, h - 50, 12,
                          THEME["muted"], "left", spacing=2, fit=True, min_size=8)
            else:
                draw_text(ex, draw, g.get("label", ""), tx, y, x + w - tx - 10, h, 17,
                          THEME["white"], "left", hand=True, bold=True, fit=True, min_size=11)
        else:
            if g.get("body"):
                draw_text(ex, draw, g.get("label", ""), x + 10, y + 12, w - 20, 28, 17,
                          THEME["white"], "center", hand=True, bold=True, fit=True, min_size=11)
                draw_text(ex, draw, g.get("body", ""), x + 12, y + 42, w - 24, h - 52, 12,
                          THEME["muted"], "center", spacing=2, fit=True, min_size=8)
            else:
                draw_text(ex, draw, g.get("label", ""), x + 10, y, w - 20, h, 17,
                          THEME["white"], "center", hand=True, bold=True, fit=True, min_size=11)

    # Edge labels + badges last: node boxes must not clip the mask chips.
    for edge in plan["graph_edges"]:
        pts = [tuple(p) for p in edge["points"]]
        color = THEME.get(edge.get("color"), THEME["muted"])
        if edge.get("label"):
            mx, my, horiz = _edge_label_anchor(pts)
            dy = -16 if edge.get("badge") else 0  # keep clear of the badge on the line
            draw_edge_label(ex, draw, edge["label"], mx, my, horiz, lw=150, lh=22, size=13,
                            color=THEME["muted"] if edge.get("loop") else THEME["white"], min_size=9, dy=dy)
        if edge.get("badge"):
            mx, my, _horiz = _edge_label_anchor(pts)
            draw_edge_badge(ex, draw, edge["badge"], mx, my, color)

    draw_legend(ex, draw, spec, plan)
    if spec.get("footer"):
        fy = plan["canvas"]["height"] - 74
        draw_text(ex, draw, spec["footer"], 105, fy, 1000, 26, 14, THEME["muted"], "center")


def render_sequence(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    seq = plan["sequence"]
    life = seq["lifeline"]

    # Lifelines first so heads, bars and arrows paint over them.
    for p in seq["participants"]:
        draw_line(ex, draw, [(p["_cx"], life["top"]), (p["_cx"], life["bottom"])],
                  THEME["frame"], 1.5, "dashed")

    # Combined fragment frames, outermost first so nested frames stay visible.
    # Tabs and guard labels are painted last (below) so activation bars and
    # arrows never clip them.
    fragments = sorted(seq["fragments"], key=lambda fr: -fr["depth"])
    for f in fragments:
        draw_rect(ex, draw, f["x"], f["y"], f["w"], f["h"], THEME["muted"], None, 1.5, RADIUS_MD)
        for d in f["dividers"]:
            draw_line(ex, draw, [(f["x"], d["y"]), (f["x"] + f["w"], d["y"])], THEME["muted"], 1.5, "dashed")

    for a in seq["activations"]:
        draw_rect(ex, draw, a["x"], a["y"], a["w"], a["h"], THEME["white"], THEME["icon_fill"], 1.5, 3)

    for m in seq["messages"]:
        if m["kind"] == "note":
            nt = m["_note"]
            draw_rect(ex, draw, nt["x"], nt["y"], nt["w"], nt["h"], THEME["amber"], THEME["icon_fill"], 1.5, RADIUS_SM)
            draw_text(ex, draw, m.get("text", ""), nt["x"] + 8, nt["y"] + 4, nt["w"] - 16, nt["h"] - 8, 12,
                      THEME["amber"], "center", fit=True, min_size=9)
            continue
        pts = m["_points"]
        draw_line(ex, draw, pts, THEME.get(m["_color"], THEME["white"]), 2, m["_style"], m["_arrow"])
        label = m.get("label", "")
        if not label:
            continue
        if m["kind"] == "self":
            # +84: the loop's vertical leg ends at +64; the snug mask pads 6px,
            # so this keeps the mask 12px+ clear of the leg.
            draw_text(ex, draw, label, pts[0][0] + 84, pts[0][1] + 2, 150, 22, 13,
                      THEME["white"], "left", fit=True, min_size=10, mask=True, role="edge-label")
        else:
            lx = min(pts[0][0], pts[-1][0])
            lw = max(90, abs(pts[-1][0] - pts[0][0]) - 16)
            draw_text(ex, draw, label, lx + 8, pts[0][1] - 30, lw, 24, 14,
                      THEME["white"], "center", fit=True, min_size=10, mask=True, role="edge-label")

    # Fragment tabs + guard/divider labels on top of bars and arrows.
    for f in fragments:
        tab_w = 64
        draw_rect(ex, draw, f["x"], f["y"], tab_w, 24, THEME["muted"], THEME["icon_fill"], 1.5, RADIUS_SM)
        draw_text(ex, draw, f["kind"], f["x"], f["y"] + 1, tab_w, 22, 13, THEME["white"], "center", bold=True)
        if f["label"]:
            draw_text(ex, draw, f["label"], f["x"] + tab_w + 10, f["y"] + 1, max(60, f["w"] - tab_w - 20), 22, 13,
                      THEME["white"], "left", fit=True, min_size=9)
        for d in f["dividers"]:
            if d["label"]:
                draw_text(ex, draw, d["label"], f["x"] + 10, d["y"] - 25, 240, 22, 12,
                          THEME["muted"], "left", fit=True, min_size=9, mask=True)

    # Participant heads on top of everything that crosses them.
    for p in seq["participants"]:
        accent = THEME.get(p["_accent"], THEME["green"])
        draw_rect(ex, draw, p["_x"], p["_y"], p["_w"], p["_h"], accent, THEME["icon_fill"], 2, RADIUS_MD)
        icon(ex, draw, p.get("icon") or ("user" if p["kind"] == "actor" else "server"),
             p["_x"] + 10, p["_y"] + 12, p.get("color", THEME["cyan"]), **icon_presentation(p))
        draw_text(ex, draw, p.get("label", ""), p["_x"] + 56, p["_y"] + 8, p["_w"] - 64, p["_h"] - 16, 16,
                  THEME["white"], "left", bold=True, fit=True, min_size=10)

    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def render_er(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    er = plan["er"]
    for e in er["entities"]:
        x, y, w, h = e["_box"]
        accent = THEME.get(e["_accent"], THEME["green"])
        fill = THEME.get(graph_model.GRAPH_FILLS.get(e["_accent"], "icon_fill"), THEME["icon_fill"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        draw_rect(ex, draw, x, y, w, graph_model.ER_HEADER_H, accent, fill, 2, RADIUS_MD)
        draw_text(ex, draw, e.get("label", ""), x + 8, y + 4, w - 16, graph_model.ER_HEADER_H - 8, 16,
                  THEME["white"], "center", bold=True, fit=True, min_size=11)
        ay = y + graph_model.ER_HEADER_H + 6
        attrs = e["_attrs"] or [{"name": "", "type": "", "key": None}]
        for a in attrs:
            text = a["name"] + (f": {a['type']}" if a["type"] else "")
            draw_text(ex, draw, text, x + 12, ay, w - 60, graph_model.ER_ROW_H, 12,
                      THEME["white"], "left", fit=True, min_size=9)
            if a["key"]:
                draw_text(ex, draw, a["key"].upper(), x + w - 48, ay, 38, graph_model.ER_ROW_H, 10,
                          THEME["amber"], "right", fit=True, min_size=8)
            ay += graph_model.ER_ROW_H
    for r in er["relations"]:
        pts = r["_points"]
        draw_line(ex, draw, pts, THEME["white"], 1.5, "solid", False)
        if r.get("from_card"):
            draw_cardinality_label(ex, draw, r["from_card"], pts, from_end=True)
        if r.get("to_card"):
            draw_cardinality_label(ex, draw, r["to_card"], pts, from_end=False)
        if r.get("label"):
            mx, my, horiz = _edge_label_anchor(pts)
            draw_edge_label(ex, draw, r["label"], mx, my, horiz, lw=120, lh=20, size=13,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def _stick_actor(ex, draw, cx, cy, color):
    """UML actor stick figure; cy is the vertical center of the whole figure."""
    draw_ellipse(ex, draw, cx - 10, cy - 40, 20, 20, color, None, 2)
    draw_line(ex, draw, [(cx, cy - 20), (cx, cy + 12)], color, 2)
    draw_line(ex, draw, [(cx - 17, cy - 8), (cx + 17, cy - 8)], color, 2)
    draw_line(ex, draw, [(cx, cy + 12), (cx - 13, cy + 42)], color, 2)
    draw_line(ex, draw, [(cx, cy + 12), (cx + 13, cy + 42)], color, 2)


def render_usecase(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    uc = plan["usecase"]
    b = uc["boundary"]
    draw_rect(ex, draw, b["x"], b["y"], b["w"], b["h"], THEME["frame"], None, 2, RADIUS_LG)
    if b["label"]:
        draw_text(ex, draw, b["label"], b["x"] + 20, b["y"] + 8, b["w"] - 40, 28, 17,
                  THEME["muted"], "center", bold=True, fit=True, min_size=11)
    for l in uc["links"]:
        pts = l["_points"]
        draw_line(ex, draw, pts, THEME["white"], 1.5, l["_style"], l["_arrow"])
    for u in uc["usecases"]:
        x = u["_cx"] - graph_model.USECASE_ELLIPSE_W / 2
        y = u["_cy"] - graph_model.USECASE_ELLIPSE_H / 2
        draw_ellipse(ex, draw, x, y, graph_model.USECASE_ELLIPSE_W, graph_model.USECASE_ELLIPSE_H,
                     THEME["cyan"], THEME["icon_fill"], 2)
        draw_text(ex, draw, u.get("label", ""), x + 14, y + 10, graph_model.USECASE_ELLIPSE_W - 28,
                  graph_model.USECASE_ELLIPSE_H - 20, 14, THEME["white"], "center", fit=True, min_size=9)
    for a in uc["actors"]:
        _stick_actor(ex, draw, a["_cx"], a["_cy"], THEME["green"])
        draw_text(ex, draw, a.get("label", ""), a["_cx"] - 60, a["_cy"] + 48, 120, 22, 13,
                  THEME["white"], "center", bold=True, fit=True, min_size=9)
    # Link labels last: ellipses and actors must not clip the mask chips.
    for l in uc["links"]:
        label = l["label"] or (f"«{l['kind']}»" if l["kind"] in ("include", "extend") else "")
        if label:
            mx, my, horiz = _edge_label_anchor(l["_points"])
            draw_edge_label(ex, draw, label, mx, my, horiz, lw=110, lh=18, size=11,
                            color=THEME["muted"], min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def _class_diamond(ex, draw, points, color, filled):
    """Composition/aggregation diamond at the relation's start end."""
    p1, p2 = points[0], points[1]
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    ux, uy = math.cos(angle), math.sin(angle)
    fill = color if filled else THEME["bg"]
    if abs(ux) >= 0.99 or abs(uy) >= 0.99:
        # Axis-aligned segment: a real diamond primitive (can be filled).
        cx, cy = p1[0] + ux * 13, p1[1] + uy * 13
        if abs(ux) >= 0.99:
            draw_diamond(ex, draw, cx - 12, cy - 7, 24, 14, color, fill, 2)
        else:
            draw_diamond(ex, draw, cx - 7, cy - 12, 14, 24, color, fill, 2)
        return
    cx, cy = p1[0] + ux * 12, p1[1] + uy * 12
    perp = (-uy * 7, ux * 7)
    tip = (p1[0], p1[1])
    back = (p1[0] + ux * 24, p1[1] + uy * 24)
    pts = [tip, (cx + perp[0], cy + perp[1]), back, (cx - perp[0], cy - perp[1])]
    draw_line(ex, draw, pts + [pts[0]], color, 2, "solid", False)


def render_class(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    cls = plan["class"]
    for c in cls["classes"]:
        x, y, w, h = c["_box"]
        accent = THEME.get(c["_accent"], THEME["green"])
        fill = THEME.get(graph_model.GRAPH_FILLS.get(c["_accent"], "icon_fill"), THEME["icon_fill"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        header_h = graph_model.CLASS_HEADER_H + (graph_model.CLASS_STEREO_H if c["_stereo"] else 0)
        draw_rect(ex, draw, x, y, w, header_h, accent, fill, 2, RADIUS_MD)
        if c["_stereo"]:
            draw_text(ex, draw, c["_stereo"], x + 8, y + 2, w - 16, graph_model.CLASS_STEREO_H, 10,
                      THEME["muted"], "center", fit=True, min_size=8)
        name_y = y + (graph_model.CLASS_STEREO_H if c["_stereo"] else 0) + 4
        draw_text(ex, draw, c.get("label", ""), x + 8, name_y, w - 16, graph_model.CLASS_HEADER_H - 8, 15,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
        ay = y + header_h + 8
        draw_line(ex, draw, [(x, ay - 4), (x + w, ay - 4)], accent, 1.5)
        for m in c["_attrs"] or []:
            text = f"{m['visibility']} {m['name']}" + (f": {m['type']}" if m["type"] else "")
            draw_text(ex, draw, text, x + 12, ay, w - 24, graph_model.CLASS_ROW_H, 11,
                      THEME["white"], "left", fit=True, min_size=8)
            ay += graph_model.CLASS_ROW_H
        if not c["_attrs"]:
            ay += graph_model.CLASS_ROW_H
        ay += 6
        if c["_methods"]:
            draw_line(ex, draw, [(x, ay - 4), (x + w, ay - 4)], accent, 1.5)
            for m in c["_methods"]:
                text = f"{m['visibility']} {m['name']}" + (f": {m['type']}" if m["type"] else "")
                draw_text(ex, draw, text, x + 12, ay, w - 24, graph_model.CLASS_ROW_H, 11,
                          THEME["white"], "left", fit=True, min_size=8)
                ay += graph_model.CLASS_ROW_H
    for r in cls["relations"]:
        pts = r["_points"]
        draw_line(ex, draw, pts, THEME["white"], 1.5, r["_style"], r["_arrow"])
        if r["kind"] in ("composition", "aggregation"):
            _class_diamond(ex, draw, pts, THEME["white"], filled=(r["kind"] == "composition"))
        p1, p2 = pts[0], pts[-1]
        if r.get("from_card"):
            draw_cardinality_label(ex, draw, r["from_card"], pts, from_end=True, lw=30, size=11, min_size=8)
        if r.get("to_card"):
            draw_cardinality_label(ex, draw, r["to_card"], pts, from_end=False, lw=30, size=11, min_size=8)
        if r.get("label"):
            mx, my, horiz = _edge_label_anchor(pts)
            draw_edge_label(ex, draw, r["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=THEME["white"], min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def _uml_terminal(ex, draw, box, kind):
    """UML initial pseudostate (filled dot) / final state (ringed dot)."""
    x, y, w, h = box
    if kind == "initial":
        draw_ellipse(ex, draw, x, y, w, h, THEME["white"], THEME["white"], 2)
    else:
        draw_ellipse(ex, draw, x, y, w, h, THEME["white"], None, 2)
        pad = 6
        draw_ellipse(ex, draw, x + pad, y + pad, w - 2 * pad, h - 2 * pad, THEME["white"], THEME["white"], 2)


def render_activity(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    act = plan["activity"]
    for e in act["edges"]:
        color = THEME["muted"] if e["_back"] else THEME["white"]
        draw_line(ex, draw, e["_points"], color, 2, e["_style"], "open")
    for n in act["nodes"]:
        x, y, w, h = n["_box"]
        kind = n["kind"]
        if kind in ("initial", "final"):
            _uml_terminal(ex, draw, n["_box"], kind)
        elif kind in ("fork", "join"):
            draw_rect(ex, draw, x, y, w, h, THEME["white"], THEME["white"], 1, 3)
        elif kind == "decision":
            draw_diamond(ex, draw, x, y, w, h, THEME["amber"], THEME["decision_fill"], 2)
            draw_text(ex, draw, n.get("label", ""), x + 18, y + h / 2 - 14, w - 36, 28, 12,
                      THEME["white"], "center", fit=True, min_size=9)
        else:
            accent = THEME.get(n["_accent"], THEME["green"])
            fill = THEME.get(graph_model.GRAPH_FILLS.get(n["_accent"], "icon_fill"), THEME["icon_fill"])
            draw_rect(ex, draw, x, y, w, h, accent, fill, 2, 26)
            draw_text(ex, draw, n.get("label", ""), x + 12, y + 10, w - 24, h - 20, 14,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
    for e in act["edges"]:
        if e["label"]:
            color = THEME["muted"] if e["_back"] else THEME["white"]
            mx, my, horiz = _edge_label_anchor(e["_points"])
            draw_edge_label(ex, draw, e["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=color, min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def render_state(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    st = plan["state"]
    for t in st["transitions"]:
        color = THEME["muted"] if t["_back"] else THEME["white"]
        draw_line(ex, draw, t["_points"], color, 2, t["_style"], "open")
    for s in st["states"]:
        x, y, w, h = s["_box"]
        if s["kind"] in ("initial", "final"):
            _uml_terminal(ex, draw, s["_box"], s["kind"])
            continue
        accent = THEME.get(s["_accent"], THEME["green"])
        fill = THEME.get(graph_model.GRAPH_FILLS.get(s["_accent"], "icon_fill"), THEME["icon_fill"])
        draw_rect(ex, draw, x, y, w, h, accent, fill, 2, RADIUS_LG)
        draw_text(ex, draw, s.get("label", ""), x + 10, y + 3, w - 20, graph_model.STATE_HEADER_H - 4, 15,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
        if s["_body"]:
            sep_y = y + graph_model.STATE_HEADER_H + 4
            draw_line(ex, draw, [(x + 10, sep_y), (x + w - 10, sep_y)], accent, 1.5)
            by = sep_y + 6
            for row in s["_body"].split("\n"):
                if row.strip():
                    draw_text(ex, draw, row.strip(), x + 12, by, w - 24, graph_model.STATE_BODY_H, 11,
                              THEME["muted"], "left", fit=True, min_size=8)
                    by += graph_model.STATE_BODY_H
    for t in st["transitions"]:
        if t["label"]:
            mx, my, horiz = _edge_label_anchor(t["_points"])
            draw_edge_label(ex, draw, t["label"], mx, my, horiz, lw=160, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def render_dfd(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    dfd = plan["dfd"]
    for f in dfd["flows"]:
        color = THEME["muted"] if f["_back"] else THEME["white"]
        draw_line(ex, draw, f["_points"], color, 2, f["_style"], "open")
    for n in dfd["nodes"]:
        x, y, w, h = n["_box"]
        accent = THEME.get(n["_accent"], THEME["green"])
        fill = THEME.get(graph_model.GRAPH_FILLS.get(n["_accent"], "icon_fill"), THEME["icon_fill"])
        if n["kind"] == "external":
            draw_rect(ex, draw, x, y, w, h, accent, fill, 2, RADIUS_MD)
            draw_text(ex, draw, n.get("label", ""), x + 10, y + 10, w - 20, h - 20, 14,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
        elif n["kind"] == "process":
            draw_ellipse(ex, draw, x, y, w, h, accent, fill, 2)
            if n["_number"]:
                draw_text(ex, draw, n["_number"], x + 14, y + 14, w - 28, 18, 12,
                          accent, "center", bold=True, fit=True, min_size=9)
                draw_text(ex, draw, n.get("label", ""), x + 12, y + 36, w - 24, h - 48, 14,
                          THEME["white"], "center", bold=True, fit=True, min_size=10)
            else:
                draw_text(ex, draw, n.get("label", ""), x + 12, y + 18, w - 24, h - 36, 14,
                          THEME["white"], "center", bold=True, fit=True, min_size=10)
        else:  # store: open rectangle (left vertical + top/bottom horizontals)
            draw_line(ex, draw, [(x, y), (x + w, y)], accent, 2)
            draw_line(ex, draw, [(x, y), (x, y + h)], accent, 2)
            draw_line(ex, draw, [(x, y + h), (x + w, y + h)], accent, 2)
            draw_text(ex, draw, n.get("label", ""), x + 12, y + 8, w - 24, h - 16, 13,
                      THEME["white"], "center", fit=True, min_size=9)
    for f in dfd["flows"]:
        if f["label"]:
            mx, my, horiz = _edge_label_anchor(f["_points"])
            draw_edge_label(ex, draw, f["label"], mx, my, horiz, lw=140, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14, THEME["muted"], "center")


def _box_fill(accent_key):
    return THEME.get(graph_model.GRAPH_FILLS.get(accent_key, "icon_fill"), THEME["icon_fill"])


def _cube_lines(x, y, w, h, d=12):
    """3D deployment-node illusion: top + right faces around the front rect."""
    return [
        [(x, y + d), (x + d, y), (x + w, y), (x + w, y + h - d), (x + w - d, y + h), (x, y + h), (x, y + d)],
        [(x + w - d, y + d), (x + w, y)],
        [(x + w - d, y + d), (x + w - d, y + h)],
    ]


def render_deployment(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    dep = plan["deployment"]
    parents = [n for n in dep["nodes"] if not n.get("_parent")]
    children = [n for n in dep["nodes"] if n.get("_parent")]
    for n in parents + children:
        x, y, w, h = n["_box"]
        accent = THEME.get(n["_accent"], THEME["green"])
        if n["kind"] == "artifact":
            draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 1.5, RADIUS_SM)
            draw_text(ex, draw, n["_stereo"], x + 8, y + 4, w - 16, 14, 9, THEME["muted"], "center")
            draw_text(ex, draw, n.get("label", ""), x + 8, y + 18, w - 16, h - 24, 13,
                      THEME["white"], "center", bold=True, fit=True, min_size=9)
            continue
        d = 12
        draw_rect(ex, draw, x, y + d, w - d, h - d, accent, THEME["icon_fill"], 2, RADIUS_MD)
        for face in _cube_lines(x, y, w, h, d)[:1]:
            draw_line(ex, draw, face, accent, 1.5)
        if n["_stereo"]:
            draw_text(ex, draw, n["_stereo"], x + 10, y + d + 4, w - d - 20, 14, 9,
                      THEME["muted"], "center", fit=True, min_size=8)
            draw_text(ex, draw, n.get("label", ""), x + 10, y + d + 18, w - d - 20, 24, 15,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
        else:
            draw_text(ex, draw, n.get("label", ""), x + 10, y + d + 6, w - d - 20, 26, 15,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
    for c in dep["connections"]:
        draw_line(ex, draw, c["_points"], THEME["white"], 1.5, c["_style"], c["_arrow"])
        if c["label"]:
            mx, my, horiz = _edge_label_anchor(c["_points"])
            draw_edge_label(ex, draw, c["label"], mx, my, horiz, lw=140, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_component(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    cmp_plan = plan["component"]
    for c in cmp_plan["components"]:
        x, y, w, h = c["_box"]
        accent = THEME.get(c["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        # UML component glyph: small box with two tabs, top-right corner.
        gx, gy = x + w - 30, y + 8
        draw_rect(ex, draw, gx, gy, 20, 14, accent, None, 1.5, 2)
        draw_rect(ex, draw, gx - 4, gy + 2, 5, 4, accent, None, 1, 1)
        draw_rect(ex, draw, gx - 4, gy + 8, 5, 4, accent, None, 1, 1)
        draw_text(ex, draw, c["_stereo"], x + 8, y + 6, w - 46, 14, 9, THEME["muted"], "center",
                  fit=True, min_size=8)
        draw_text(ex, draw, c.get("label", ""), x + 10, y + 24, w - 20, 26, 15,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
        body = [r for r in str(c.get("body", "")).split("\n") if r.strip()]
        by = y + 54
        for row in body:
            draw_text(ex, draw, row.strip(), x + 14, by, w - 28, 18, 11,
                      THEME["muted"], "left", fit=True, min_size=8)
            by += 18
    for r in cmp_plan["relations"]:
        draw_line(ex, draw, r["_points"], THEME["white"], 1.5, r["_style"], r["_arrow"])
        if r["label"]:
            mx, my, horiz = _edge_label_anchor(r["_points"])
            draw_edge_label(ex, draw, r["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    for itf in cmp_plan["interfaces"]:
        r = graph_model.COMPONENT_IF_R
        cx, cy = itf["_cx"], itf["_cy"]
        if itf["kind"] == "provided":
            draw_ellipse(ex, draw, cx - r, cy - r, 2 * r, 2 * r, THEME["white"], THEME["bg"], 2)
        else:
            # Required "socket": outer semicircle (inner half covered with bg).
            draw_ellipse(ex, draw, cx - r, cy - r, 2 * r, 2 * r, THEME["white"], None, 2)
            draw_rect(ex, draw, cx - r - 2, cy - r - 2, r + 2, 2 * r + 4, THEME["bg"], THEME["bg"], 0, 0)
        lx = cx + r + 6 if itf["kind"] == "provided" else cx - r - 116
        draw_text(ex, draw, itf["label"], lx, cy - 9, 110, 18, 11,
                  THEME["white"], "left" if itf["kind"] == "provided" else "right",
                  fit=True, min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_package(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    pkg = plan["package"]
    tab_h, tab_w = 18, 96
    parents = [p for p in pkg["packages"] if not p.get("_parent")]
    children = [p for p in pkg["packages"] if p.get("_parent")]
    for p in parents + children:
        x, y, w, h = p["_box"]
        accent = THEME.get(p["_accent"], THEME["green"])
        is_container = bool(pkg["children"].get(p["id"]))
        body_y = y + tab_h
        draw_rect(ex, draw, x, body_y, w, h - tab_h, accent, _box_fill(p["_accent"]), 2, RADIUS_MD)
        draw_rect(ex, draw, x, y, tab_w, tab_h, accent, _box_fill(p["_accent"]), 2, RADIUS_SM)
        if p["_stereo"]:
            draw_text(ex, draw, p["_stereo"], x + tab_w + 6, y + 2, w - tab_w - 12, 14, 9,
                      THEME["muted"], "left", fit=True, min_size=8)
        if is_container:
            draw_text(ex, draw, p.get("label", ""), x + tab_w + 8, y + tab_h + 4,
                      w - tab_w - 16, 22, 14, THEME["white"], "left", bold=True, fit=True, min_size=10)
        else:
            draw_text(ex, draw, p.get("label", ""), x + 8, body_y + 6, w - 16, h - tab_h - 12, 14,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
    for r in pkg["relations"]:
        draw_line(ex, draw, r["_points"], THEME["white"], 1.5, "dashed", "open")
        label = r["label"] or (f"«{r['kind']}»" if r["kind"] != "dependency" else "")
        if label:
            mx, my, horiz = _edge_label_anchor(r["_points"])
            draw_edge_label(ex, draw, label, mx, my, horiz, lw=110, lh=18, size=11,
                            color=THEME["muted"], min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_object(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    obj = plan["object"]
    for o in obj["objects"]:
        x, y, w, h = o["_box"]
        accent = THEME.get(o["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        draw_rect(ex, draw, x, y, w, graph_model.OBJECT_HEADER_H, accent, _box_fill(o["_accent"]), 2, RADIUS_MD)
        draw_text(ex, draw, o["_title"], x + 8, y + 3, w - 16, graph_model.OBJECT_HEADER_H - 8, 14,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
        # UML instance names are underlined.
        draw_line(ex, draw, [(x + 24, y + graph_model.OBJECT_HEADER_H - 6),
                             (x + w - 24, y + graph_model.OBJECT_HEADER_H - 6)], accent, 1)
        ay = y + graph_model.OBJECT_HEADER_H + 8
        for a in o["_attrs"] or [{"name": "", "value": ""}]:
            text = a["name"] + (f" = {a['value']}" if a["value"] else "")
            draw_text(ex, draw, text, x + 12, ay, w - 24, graph_model.OBJECT_ROW_H, 11,
                      THEME["white"], "left", fit=True, min_size=8)
            ay += graph_model.OBJECT_ROW_H
    for l in obj["links"]:
        draw_line(ex, draw, l["_points"], THEME["white"], 1.5, "solid", False)
        if l["label"]:
            mx, my, horiz = _edge_label_anchor(l["_points"])
            draw_edge_label(ex, draw, l["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_composite(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    comp = plan["composite"]
    b = comp["boundary"]
    draw_rect(ex, draw, b["x"], b["y"], b["w"], b["h"], THEME["frame"], None, 2, RADIUS_LG)
    if b["label"]:
        draw_text(ex, draw, b["label"], b["x"] + b["w"] - 220, b["y"] + 8, 200, 26, 15,
                  THEME["muted"], "right", bold=True, fit=True, min_size=10)
    for c in comp["connectors"]:
        draw_line(ex, draw, c["_points"], THEME["white"], 1.5, "solid", False)
    for p in comp["parts"]:
        x, y, w, h = p["_box"]
        accent = THEME.get(p["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        title = p.get("label", "") + (f": {p['_type']}" if p["_type"] else "")
        draw_text(ex, draw, title, x + 10, y + 12, w - 20, h - 24, 14,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
    for po in comp["ports"]:
        x, y, w, h = po["_box"]
        draw_rect(ex, draw, x, y, w, h, THEME["white"], THEME["bg"], 2, 2)
        if po["label"]:
            if po["side"] == "right":
                draw_text(ex, draw, po["label"], x + w + 6, y, 90, 18, 10, THEME["muted"], "left",
                          fit=True, min_size=8)
            elif po["side"] == "left":
                draw_text(ex, draw, po["label"], x - 96, y, 90, 18, 10, THEME["muted"], "right",
                          fit=True, min_size=8)
            elif po["side"] == "top":
                draw_text(ex, draw, po["label"], x - 36, y - 22, 90, 18, 10, THEME["muted"], "center",
                          fit=True, min_size=8)
            else:
                draw_text(ex, draw, po["label"], x - 36, y + h + 4, 90, 18, 10, THEME["muted"], "center",
                          fit=True, min_size=8)
    # Connector labels last: part boxes must not clip the mask chips.
    for c in comp["connectors"]:
        if c["label"]:
            mx, my, horiz = _edge_label_anchor(c["_points"])
            draw_edge_label(ex, draw, c["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_profile(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    prof = plan["profile"]
    for it in prof["items"]:
        x, y, w, h = it["_box"]
        accent = THEME.get(it["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        header_h = graph_model.PROFILE_HEADER_H + graph_model.PROFILE_STEREO_H
        draw_rect(ex, draw, x, y, w, header_h, accent, _box_fill(it["_accent"]), 2, RADIUS_MD)
        draw_text(ex, draw, it["_stereo"], x + 8, y + 2, w - 16, graph_model.PROFILE_STEREO_H, 10,
                  THEME["muted"], "center", fit=True, min_size=8)
        draw_text(ex, draw, it.get("label", ""), x + 8, y + graph_model.PROFILE_STEREO_H + 3,
                  w - 16, graph_model.PROFILE_HEADER_H - 8, 15, THEME["white"], "center",
                  bold=True, fit=True, min_size=10)
        ay = y + header_h + 8
        for a in it["_attrs"]:
            draw_text(ex, draw, a, x + 12, ay, w - 24, graph_model.PROFILE_ROW_H, 11,
                      THEME["white"], "left", fit=True, min_size=8)
            ay += graph_model.PROFILE_ROW_H
    for r in prof["relations"]:
        draw_line(ex, draw, r["_points"], THEME["white"], 1.5, r["_style"], r["_arrow"])
        if r["label"]:
            mx, my, horiz = _edge_label_anchor(r["_points"])
            draw_edge_label(ex, draw, r["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=THEME["white"], min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_communication(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    comm = plan["communication"]
    for o in comm["objects"]:
        x, y, w, h = o["_box"]
        accent = THEME.get(o["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        draw_text(ex, draw, o.get("label", ""), x + 10, y + 10, w - 20, h - 20, 14,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
    for l in comm["links"]:
        pts = l["_points"]
        draw_line(ex, draw, pts, THEME["white"], 1.5, "solid", False)
        if not l["messages"]:
            continue
        mx, my, horiz = _edge_label_anchor(pts)
        # Message stack near the link midpoint, each with a direction tick.
        a, b = pts[0], pts[-1]
        fwd_sign = 1 if (b[0] - a[0] if horiz else b[1] - a[1]) >= 0 else -1
        for k, m in enumerate(l["messages"]):
            ly = my - 26 * (k + 1) if horiz else my - 13 + 26 * (k - len(l["messages"]) / 2)
            draw_text(ex, draw, f"{m['num']}: {m['label']}", mx - 75, ly - 9, 150, 18, 11,
                      THEME["white"], "center", fit=True, min_size=8, mask=True, role="edge-label")
            sign = fwd_sign if m["dir"] == "forward" else -fwd_sign
            if horiz:
                x0 = mx - 106 if sign > 0 else mx + 92
                draw_line(ex, draw, [(x0, ly), (x0 + 14 * sign, ly)], THEME["white"], 1.5, "solid", "open")
            else:
                y0 = ly - 16 if sign > 0 else ly + 2
                draw_line(ex, draw, [(mx - 94, y0), (mx - 94, y0 + 10 * sign)], THEME["white"], 1.5, "solid", "open")
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_timing(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    tim = plan["timing"]
    axis = tim["axis"]
    for tick in tim["ticks"]:
        draw_line(ex, draw, [(tick["x"], 200), (tick["x"], axis["y"])], THEME["frame"], 1, "dashed")
        draw_text(ex, draw, str(tick["t"]), tick["x"] - 30, axis["y"] + 8, 60, 18, 11,
                  THEME["muted"], "center")
    draw_line(ex, draw, [(axis["x0"], axis["y"]), (axis["x1"], axis["y"])], THEME["muted"], 2, "solid", "open")
    for l in tim["lifelines"]:
        accent = THEME.get(l["_accent"], THEME["green"])
        band_y, band_h = l["_band"]
        draw_text(ex, draw, l.get("label", ""), graph_model.TIMING_LABEL_X, band_y - 24, 170, 20, 14,
                  THEME["white"], "left", bold=True, fit=True, min_size=10)
        for s in l["_states"]:
            draw_text(ex, draw, s, graph_model.TIMING_LABEL_X + 96, l["_level_y"][s] - 9, 76, 18, 11,
                      THEME["muted"], "right", fit=True, min_size=8)
        draw_line(ex, draw, l["_points"], accent, 2.5)
    for m in tim["messages"]:
        draw_line(ex, draw, m["_points"], THEME["muted"], 1.5, "dashed", "open")
        if m["label"]:
            mx = (m["_points"][0][0] + m["_points"][1][0]) / 2
            my = min(m["_points"][0][1], m["_points"][1][1]) - 24
            draw_text(ex, draw, m["label"], mx - 70, my, 140, 20, 11, THEME["white"], "center",
                      fit=True, min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_interaction(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    inter = plan["interaction"]
    for e in inter["edges"]:
        color = THEME["muted"] if e["_back"] else THEME["white"]
        draw_line(ex, draw, e["_points"], color, 2, e["_style"], "open")
    for n in inter["nodes"]:
        x, y, w, h = n["_box"]
        kind = n["kind"]
        if kind in ("initial", "final"):
            _uml_terminal(ex, draw, n["_box"], kind)
        elif kind == "decision":
            draw_diamond(ex, draw, x, y, w, h, THEME["amber"], THEME["decision_fill"], 2)
            draw_text(ex, draw, n.get("label", ""), x + 18, y + h / 2 - 14, w - 36, 28, 12,
                      THEME["white"], "center", fit=True, min_size=9)
        else:
            accent = THEME.get(n["_accent"], THEME["green"])
            draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
            # UML frame tab: pentagon tag with the ref keyword (sd / ref).
            tab_w = 56
            draw_line(ex, draw, [(x, y + 22), (x, y), (x + tab_w - 12, y), (x + tab_w, y + 11),
                                 (x + tab_w - 12, y + 22)], accent, 1.5)
            draw_text(ex, draw, n["_ref_kind"] or "sd", x + 4, y + 2, tab_w - 18, 18, 11,
                      accent, "center", bold=True)
            draw_text(ex, draw, n.get("label", ""), x + 12, y + 34, w - 24, h - 44, 15,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
    for e in inter["edges"]:
        if e["label"]:
            color = THEME["muted"] if e["_back"] else THEME["white"]
            mx, my, horiz = _edge_label_anchor(e["_points"])
            draw_edge_label(ex, draw, e["label"], mx, my, horiz, lw=120, lh=20, size=12,
                            color=color, min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_c4(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    c4 = plan["c4"]
    for b in c4["boundaries"]:
        if not b["_box"]:
            continue
        x, y, w, h = b["_box"]
        draw_rect(ex, draw, x, y, w, h, THEME["muted"], None, 1.5, RADIUS_MD)
        if b["label"]:
            draw_text(ex, draw, b["label"], x + 12, y + h - 26, w - 24, 20, 12,
                      THEME["muted"], "left", fit=True, min_size=9)
    for r in c4["relations"]:
        draw_line(ex, draw, r["_points"], THEME["white"], 1.5, r["_style"], "open")
    stereo_of = {"person": "«person»", "system": "«system»", "ext_system": "«external system»",
                 "container": "«container»", "database": "«database»", "queue": "«queue»"}
    for e in c4["elements"]:
        x, y, w, h = e["_box"]
        accent = THEME.get(e["_accent"], THEME["green"])
        if e["kind"] == "database":
            # Cylinder approximation: ellipse lid + body rect + bottom arc line.
            draw_ellipse(ex, draw, x, y, w, 26, accent, _box_fill(e["_accent"]), 2)
            draw_rect(ex, draw, x, y + 13, w, h - 26, accent, THEME["icon_fill"], 2, RADIUS_SM)
            draw_ellipse(ex, draw, x, y + h - 26, w, 26, accent, None, 2)
        else:
            radius = RADIUS_FRAME if e["kind"] == "person" else RADIUS_MD
            draw_rect(ex, draw, x, y, w, h, accent,
                      _box_fill(e["_accent"]) if e["kind"] != "ext_system" else THEME["icon_fill"],
                      2, radius)
        if e["kind"] == "person":
            _stick_actor(ex, draw, x + w / 2, y + 26, accent)
            text_top = y + 50
        else:
            draw_text(ex, draw, stereo_of[e["kind"]], x + 8, y + 8, w - 16, 14, 9,
                      THEME["muted"], "center", fit=True, min_size=8)
            text_top = y + 22
        draw_text(ex, draw, e.get("label", ""), x + 10, text_top, w - 20, 24, 15,
                  THEME["white"], "center", bold=True, fit=True, min_size=10)
        if e["_tech"] and e["kind"] != "person":
            draw_text(ex, draw, f"[{e['_tech']}]", x + 10, text_top + 26, w - 20, 16, 10,
                      THEME["muted"], "center", fit=True, min_size=8)
        if e["_desc"]:
            draw_text(ex, draw, e["_desc"], x + 12, text_top + 44, w - 24, h - (text_top - y) - 50, 10,
                      THEME["muted"], "center", spacing=2, fit=True, min_size=8)
    # Relation labels last: element boxes must not clip the mask chips.
    for r in c4["relations"]:
        label = r["label"] + (f" [{r['technology']}]" if r["technology"] else "")
        if label:
            mx, my, horiz = _edge_label_anchor(r["_points"])
            draw_edge_label(ex, draw, label, mx, my, horiz, lw=160, lh=20, size=11,
                            color=THEME["white"], min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_gantt(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    ga = plan["gantt"]
    axis = ga["axis"]
    for tick in ga["ticks"]:
        draw_line(ex, draw, [(tick["x"], 208), (tick["x"], axis["y"])], THEME["frame"], 1, "dashed")
        draw_text(ex, draw, tick["label"], tick["x"] - 40, axis["y"] + 10, 80, 18, 11,
                  THEME["muted"], "center")
    draw_line(ex, draw, [(axis["x0"], axis["y"]), (axis["x1"], axis["y"])], THEME["muted"], 2, "solid", "open")
    for s in ga["sections"]:
        draw_text(ex, draw, s["label"], graph_model.GANTT_LABEL_X, s["_y"] + 6,
                  graph_model.GANTT_LABEL_W + 60, 26, 16, THEME["white"], "left", hand=True, bold=True,
                  fit=True, min_size=11)
        draw_line(ex, draw, [(graph_model.GANTT_LABEL_X, s["_y"] + graph_model.GANTT_SECTION_H - 4),
                             (axis["x1"], s["_y"] + graph_model.GANTT_SECTION_H - 4)],
                  THEME["frame"], 1.5)
        for t in s["tasks"]:
            draw_text(ex, draw, t["label"], graph_model.GANTT_LABEL_X + 16, t["_y"] + 4,
                      graph_model.GANTT_LABEL_W - 16, graph_model.GANTT_ROW_H - 10, 12,
                      THEME["white"], "left", fit=True, min_size=9)
            bar_y = t["_y"] + (graph_model.GANTT_ROW_H - 18) / 2
            if t["kind"] == "milestone":
                draw_diamond(ex, draw, t["_x0"] - 10, bar_y - 1, 22, 22, THEME["pink"], THEME["pink"], 2)
                continue
            w = max(20, t["_x1"] - t["_x0"])
            if t["kind"] == "done":
                stroke, fill = THEME["muted"], THEME["icon_fill"]
            elif t["kind"] == "active":
                stroke, fill = THEME["green"], THEME["green_fill"]
            elif t["kind"] == "crit":
                stroke, fill = THEME["pink"], THEME["icon_fill"]
            else:
                stroke, fill = THEME["cyan"], THEME["blue_fill"]
            draw_rect(ex, draw, t["_x0"], bar_y, w, 18, stroke, fill, 2, RADIUS_MD)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_bpmn(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    bp = plan["bpmn"]
    for lane in bp["lanes"]:
        y, h = lane["_y"], lane["_h"]
        draw_rect(ex, draw, 70, y, 1080, h, THEME["frame"], None, 1.5, RADIUS_MD)
        if lane["label"] or lane["pool"]:
            label = (lane["pool"] + " / " if lane["pool"] else "") + lane["label"]
            draw_text(ex, draw, label, 80, y + 6, 200, 22, 13, THEME["muted"], "left",
                      bold=True, fit=True, min_size=9)
    for f in bp["flows"]:
        color = THEME["muted"] if f["kind"] == "message" else THEME["white"]
        draw_line(ex, draw, f["_points"], color, 1.5, f["_style"], "open")
        if f["label"]:
            mx, my, horiz = _edge_label_anchor(f["_points"])
            draw_edge_label(ex, draw, f["label"], mx, my, horiz, lw=120, lh=20, size=11,
                            color=color, min_size=8)
    for e in bp["elements"]:
        x, y, w, h = e["_box"]
        accent = THEME.get(e["_accent"], THEME["green"])
        kind = e["kind"]
        if kind in ("start", "intermediate", "end"):
            width = 4 if kind == "end" else 2
            draw_ellipse(ex, draw, x, y, w, h, accent, THEME["bg"], width)
            if kind in ("intermediate", "end"):
                pad = 5
                draw_ellipse(ex, draw, x + pad, y + pad, w - 2 * pad, h - 2 * pad, accent, None, 1.5)
            if e.get("label"):
                draw_text(ex, draw, e["label"], x - 40, y + h + 6, w + 80, 18, 11,
                          THEME["white"], "center", fit=True, min_size=8)
        elif kind in ("gateway", "gateway_parallel"):
            draw_diamond(ex, draw, x, y, w, h, THEME["amber"], THEME["decision_fill"], 2)
            cx, cy = x + w / 2, y + h / 2
            if kind == "gateway_parallel":
                draw_line(ex, draw, [(cx - 10, cy), (cx + 10, cy)], THEME["white"], 2.5)
                draw_line(ex, draw, [(cx, cy - 10), (cx, cy + 10)], THEME["white"], 2.5)
            else:
                draw_line(ex, draw, [(cx - 8, cy - 8), (cx + 8, cy + 8)], THEME["white"], 2.5)
                draw_line(ex, draw, [(cx - 8, cy + 8), (cx + 8, cy - 8)], THEME["white"], 2.5)
            if e.get("label"):
                draw_text(ex, draw, e["label"], x - 30, y + h + 4, w + 60, 18, 11,
                          THEME["white"], "center", fit=True, min_size=8)
        else:
            draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_LG)
            draw_text(ex, draw, e.get("label", ""), x + 10, y + 10, w - 20, h - 20, 13,
                      THEME["white"], "center", bold=True, fit=True, min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_orgchart(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    org = plan["orgchart"]
    for edge in plan["edges"]:
        draw_line(ex, draw, [tuple(p) for p in edge["points"]], THEME["white"], 1.5, "solid", False)
    for n in org["nodes"]:
        x, y, w, h = n["_box"]
        accent = THEME.get(n["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, _box_fill(n["_accent"]), 2, RADIUS_MD)
        if n["_role"]:
            draw_text(ex, draw, n.get("label", ""), x + 8, y + 8, w - 16, 24, 14,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
            draw_text(ex, draw, n["_role"], x + 8, y + 34, w - 16, 18, 11,
                      THEME["muted"], "center", fit=True, min_size=8)
        else:
            draw_text(ex, draw, n.get("label", ""), x + 8, y + 10, w - 16, h - 20, 14,
                      THEME["white"], "center", bold=True, fit=True, min_size=10)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_mindmap(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    mm = plan["mindmap"]
    for edge in plan["edges"]:
        draw_line(ex, draw, [tuple(p) for p in edge["points"]],
                  THEME.get(edge.get("color"), THEME["white"]), 1.5, "solid", False)
    root = mm["root"]
    x, y, w, h = root["_box"]
    draw_rect(ex, draw, x, y, w, h, THEME["green"], THEME["green_fill"], 2.5, RADIUS_FRAME)
    draw_text(ex, draw, root["label"], x + 10, y + 10, w - 20, h - 20, 16,
              THEME["white"], "center", hand=True, bold=True, fit=True, min_size=11)
    for t in mm["topics"]:
        x, y, w, h = t["_box"]
        accent = THEME.get(t["_accent"], THEME["green"])
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_LG)
        draw_text(ex, draw, t.get("label", ""), x + 8, y + 8, w - 16, h - 16, 13,
                  THEME["white"], "center", bold=True, fit=True, min_size=9)
    # Leaves are the terminal pills in the interaction node list.
    for n in plan["nodes"]:
        if n["kind"] != "terminal":
            continue
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        draw_rect(ex, draw, x, y, w, h, THEME["muted"], THEME["icon_fill"], 1.5, min(w, h) // 2)
        draw_text(ex, draw, n["label"], x + 10, y + 6, w - 20, h - 12, 12,
                  THEME["white"], "center", fit=True, min_size=9)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_timeline(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    tl = plan["timeline"]
    axis = tl["axis"]
    draw_line(ex, draw, [(axis["x0"], axis["y"]), (axis["x1"], axis["y"])], THEME["muted"], 2.5, "solid", "open")
    for e in tl["events"]:
        accent = THEME.get(e["_accent"], THEME["green"])
        dx, dy = e["_dot"]
        draw_line(ex, draw, e["_stem"], THEME["frame"], 1.5)
        draw_ellipse(ex, draw, dx - 6, dy - 6, 12, 12, accent, accent, 2)
        x, y, w, h = e["_box"]
        draw_rect(ex, draw, x, y, w, h, accent, THEME["icon_fill"], 2, RADIUS_MD)
        if e.get("time"):
            draw_text(ex, draw, str(e["time"]), x + 8, y + 6, w - 16, 16, 10,
                      accent, "center", bold=True, fit=True, min_size=8)
            draw_text(ex, draw, e.get("label", ""), x + 8, y + 24, w - 16, h - 32, 13,
                      THEME["white"], "center", bold=True, fit=True, min_size=9)
        else:
            draw_text(ex, draw, e.get("label", ""), x + 8, y + 10, w - 16, h - 20, 13,
                      THEME["white"], "center", bold=True, fit=True, min_size=9)
        if e.get("detail"):
            dy2 = y + h + 6 if not e["_above"] else y - 22
            draw_text(ex, draw, e["detail"], x - 5, dy2, w + 10, 18, 10,
                      THEME["muted"], "center", fit=True, min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


def render_fishbone(ex, draw, spec, plan):
    if spec.get("subtitle"):
        draw_text(ex, draw, spec["subtitle"], 105, 145, 1000, 30, 17, THEME["muted"], "center")
    fb = plan["fishbone"]
    spine = fb["spine"]
    draw_line(ex, draw, [(spine["x0"], spine["y"]), (spine["x1"], spine["y"])], THEME["white"], 3, "solid", "open")
    head = fb["head"]
    draw_rect(ex, draw, head["x"], head["y"], head["w"], head["h"], THEME["pink"], THEME["icon_fill"], 2, RADIUS_MD)
    draw_text(ex, draw, fb["problem"], head["x"] + 12, head["y"] + 14, head["w"] - 24, head["h"] - 28, 15,
              THEME["white"], "center", bold=True, fit=True, min_size=10)
    for c in fb["categories"]:
        accent = THEME.get(c["_accent"], THEME["green"])
        draw_line(ex, draw, [c["_base"], c["_tip"]], accent, 2)
        lx, ly, lw, lh = c["_label_box"]
        draw_text(ex, draw, c.get("label", ""), lx, ly, lw, lh, 16, accent, "left",
                  hand=True, bold=True, fit=True, min_size=11)
        for tick in c["_ticks"]:
            draw_line(ex, draw, tick["points"], THEME["muted"], 1.5)
            tx, ty = tick["points"][1]
            draw_text(ex, draw, tick["text"], tx + 6, ty - 16, 150, 18, 11,
                      THEME["white"], "left", fit=True, min_size=8)
    if spec.get("footer"):
        draw_text(ex, draw, spec["footer"], 105, plan["canvas"]["height"] - 40, 1000, 26, 14,
                  THEME["muted"], "center")


LAYOUT_PAINTERS = {
    "panorama": render_panorama,
    "swimlane": render_swimlane,
    "graph": render_graph,
    "grid": render_grid,
    "sequence": render_sequence,
    "er": render_er,
    "usecase": render_usecase,
    "class": render_class,
    "activity": render_activity,
    "state": render_state,
    "dfd": render_dfd,
    "deployment": render_deployment,
    "component": render_component,
    "package": render_package,
    "object": render_object,
    "composite": render_composite,
    "profile": render_profile,
    "communication": render_communication,
    "timing": render_timing,
    "interaction": render_interaction,
    "c4": render_c4,
    "gantt": render_gantt,
    "bpmn": render_bpmn,
    "orgchart": render_orgchart,
    "mindmap": render_mindmap,
    "timeline": render_timeline,
    "fishbone": render_fishbone,
}

# Plan of the most recent render_static call: geometry, animation paths and
# graph topology for the active layout (see scripts/graph_model.py).
CURRENT_PLAN = None


def render_static(spec):
    global CURRENT_PLAN
    plan = graph_model.build_plan(spec)
    if plan["layout"] in ("graph", "sequence", "er", "usecase", "class", "activity", "state", "dfd",
                          "deployment", "component", "package", "object", "composite", "profile",
                          "communication", "timing", "interaction",
                          "c4", "gantt", "bpmn", "orgchart", "mindmap", "timeline", "fishbone"):
        width = plan["canvas"]["width"]
        height = plan["canvas"]["height"]
    else:
        width = spec.get("canvas", {}).get("width", plan["canvas"]["width"])
        height = spec.get("canvas", {}).get("height", plan["canvas"]["height"])
        if plan["layout"] in ("swimlane", "grid"):
            # Content cannot compress; a shorter forced canvas would clip the
            # bottom rows, so the natural planned height is the floor.
            height = max(height, plan["canvas"]["height"])
    plan["canvas"] = {"width": width, "height": height}
    CURRENT_PLAN = plan

    ex = Excal(width, height)
    img = Image.new("RGBA", (width * SCALE, height * SCALE), hex_rgba(THEME["bg"]))
    draw = ImageDraw.Draw(img)
    draw_chrome(ex, draw, spec, plan)
    LAYOUT_PAINTERS[plan["layout"]](ex, draw, spec, plan)
    return ex, img.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")


def finish_glow_rects(plan, mode=None):
    """Resolve the plan's glow rectangles for the requested finish mode."""
    mode = mode or FINISH_MODE
    key = "light" if mode == "light" else "color"
    return [(tuple(item["box"]), item[key], item["width"]) for item in plan["glow_rects"]]


def render_static_with_ops(spec):
    """Run render_static while recording the primitive op stream.

    Returns (excal_builder, raster_image, ops_document). The ops document is
    JSON-friendly and consumed by scripts/svg_renderer.py, which replays it
    with rough.js inside Chromium so both renderers share one layout.
    """
    global OPS_SINK
    ops = []
    OPS_SINK = ops
    try:
        ex, img = render_static(spec)
    finally:
        OPS_SINK = None
    plan = CURRENT_PLAN
    return ex, img, {
        "canvas": {
            "width": plan["canvas"]["width"],
            "height": plan["canvas"]["height"],
            "fps": spec.get("canvas", {}).get("fps", DEFAULT_FPS),
            "frames": spec.get("canvas", {}).get("frames", DEFAULT_FRAMES),
        },
        "style": CURRENT_STYLE,
        "sketch": SKETCH,
        "layout": plan["layout"],
        "title": spec.get("title", {}) if isinstance(spec.get("title"), dict) else {},
        "bg": THEME["bg"],
        "finish": {
            "mode": FINISH_MODE,
            "glow_rects": [] if (not SKETCH and FINISH_MODE == "light") else [
                {"box": list(box), "color": THEME[color_key], "width": w}
                for box, color_key, w in finish_glow_rects(plan)
            ],
        },
        "theme": dict(THEME),
        "animation": {
            "flow_paths": [
                # Snap to the 4px grid so the animated overlay tracks the
                # (snapped) static connector exactly.
                {"points": [[snap4(px), snap4(py)] for px, py in fp["points"]], "color": THEME[fp["color"]], "offset": fp["offset"]}
                for fp in plan["flow_paths"]
            ],
            "pulse_targets": [
                {"box": [snap4(v) for v in pt["box"]], "color": THEME[pt["color"]]} for pt in plan["pulse_targets"]
            ],
        },
        "graph": {"canvas": plan["canvas"], "nodes": plan["nodes"], "edges": _json_edges(plan["edges"])},
        "ops": ops,
    }


def _json_edges(edges):
    return [dict(edge, points=[list(p) for p in edge["points"]]) for edge in edges]


def light_finish(base, plan):
    """Finish for light styles. Formal: print-clean, nothing added. Sketch:
    soft colored frame glow, no grain/vignette."""
    if not SKETCH:
        return base.convert("RGB")
    width, height = base.size
    img = base.convert("RGBA")
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for rect, color_key, line_width in finish_glow_rects(plan, "light"):
        g.rounded_rectangle(rect, radius=18, outline=hex_rgba(THEME[color_key], 70), width=line_width)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
    return img.convert("RGB")


def premium_finish(base, plan=None):
    plan = plan or CURRENT_PLAN
    if FINISH_MODE == "light":
        return light_finish(base, plan)
    width, height = base.size
    img = base.convert("RGBA")
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for rect, color_key, line_width in finish_glow_rects(plan, "dark"):
        g.rounded_rectangle(rect, radius=18, outline=hex_rgba(THEME[color_key], 70), width=line_width)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(4)))
    return img.convert("RGB")


def draw_glow_dot(draw, x, y, color, strength=1.0):
    for radius, alpha in [(15, 34), (9, 90), (4.5, 205)]:
        a = int(alpha * strength)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=hex_rgba(color, a))
    core = 2.4 * (0.6 + 0.4 * strength)
    draw.ellipse((x - core, y - core, x + core, y + core), fill=hex_rgba(THEME["white"], int(235 * min(1.0, strength + 0.15))))


def draw_flow_segment(draw, points, color, head_t, length_frac=0.18, width=6, samples=16):
    """Draw a bright 'energy segment' that travels along the polyline (effect A).

    The lit portion runs from the head position backwards by `length_frac` of the
    total path length, brightest at the head and fading toward the tail. Distances
    are clamped to the path so the segment never wraps across the start/end seam.
    """
    total = path_len(points)
    if total <= 0:
        return
    head_d = (head_t % 1.0) * total
    seg_len = length_frac * total
    prev = None
    for i in range(samples + 1):
        d = head_d - seg_len * (i / samples)
        if d < 0:
            break
        pt = point_at_distance(points, d)
        if prev is not None:
            frac = 1.0 - (i - 0.5) / samples
            alpha = int(165 * frac)
            w = max(1, int(round(width * (0.35 + 0.65 * frac))))
            draw.line([prev, pt], fill=hex_rgba(color, alpha), width=w)
        prev = pt


def pulse_rect(draw, rect, color, phase, radius=10):
    x1, y1, x2, y2 = rect
    alpha = int(36 + 42 * (0.5 + 0.5 * math.sin(phase)))
    for grow, width in [(0, 2), (4, 1)]:
        draw.rounded_rectangle((x1 - grow, y1 - grow, x2 + grow, y2 + grow), radius=radius + grow, outline=hex_rgba(color, max(18, alpha - grow * 7)), width=width)


def icon_center(kind, x, y, scale=1.0):
    tile = ICON_TILE * scale
    return x + tile / 2, y + tile / 2


def collect_icon_instances(spec, plan=None):
    """Icon instances (kind/x/y/color/ordinal) for the icon-motion layer.

    Geometry comes from the layout plan so every layout is covered; the
    ordinals stay stable within one plan, which is all the effects need.
    """
    plan = plan or graph_model.build_plan(spec or {})
    instances = []
    for entry in plan["icons"]:
        instances.append(
            {
                "kind": entry["kind"],
                "x": entry["x"],
                "y": entry["y"],
                "scale": entry.get("scale", 1.0),
                "color": entry.get("color") or THEME["cyan"],
                "group": entry["group"],
                "ordinal": entry["ordinal"],
            }
        )
    return instances


def draw_icon_halo(draw, cx, cy, color, phase, active=False):
    if not active:
        return
    pulse = 0.5 + 0.5 * math.sin(phase)
    base_alpha = 48 + int(32 * pulse)
    for radius, alpha_scale, width in [(24, 0.72, 1), (30, 0.28, 1)]:
        alpha = min(150, int(base_alpha * alpha_scale))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=hex_rgba(color, alpha), width=width)


def draw_orbit_dot(draw, cx, cy, color, progress, ordinal, active=False):
    if not active:
        return
    speed = 1.35
    radius = 24
    angle = math.tau * ((progress * speed + ordinal * 0.071) % 1.0)
    x = cx + radius * math.cos(angle)
    y = cy + radius * math.sin(angle)
    draw.ellipse((x - 2.5, y - 2.5, x + 2.5, y + 2.5), fill=hex_rgba(THEME["white"], 220))
    draw.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=hex_rgba(color, 230))


def draw_icon_specific_motion(draw, kind, x, y, scale, color, progress, phase, active=False):
    if not active:
        return
    if kind == "scan":
        cx, cy = icon_center(kind, x, y, scale)
        radius = 22 * scale
        start = int((progress * 360 * 1.4 + 50) % 360)
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start=start, end=start + 95, fill=hex_rgba(THEME["cyan"], 150), width=2)
        sweep = math.radians(start + 115)
        draw.line((cx, cy, cx + radius * math.cos(sweep), cy + radius * math.sin(sweep)), fill=hex_rgba(THEME["white"], 95), width=1)
    elif kind == "shield":
        shine = (math.sin(phase * 1.3) + 1) / 2
        alpha = 65 + int(90 * shine)
        draw.line((x + 17 * scale, y + 15 * scale, x + 43 * scale, y + 41 * scale), fill=hex_rgba(THEME["white"], alpha), width=1)
    elif kind == "db":
        offset = 2.5 * math.sin(phase)
        for yy, alpha in [(y + 15 * scale + offset, 88), (y + 27 * scale - offset, 70), (y + 39 * scale + offset, 88)]:
            draw.arc((x + 10 * scale, yy - 6 * scale, x + 44 * scale, yy + 6 * scale), 0, 180, fill=hex_rgba(THEME["white"], alpha), width=1)
    elif kind == "package":
        pulse = 0.5 + 0.5 * math.sin(phase)
        points = [(x + 27 * scale, y + 7 * scale), (x + 45 * scale, y + 18 * scale), (x + 45 * scale, y + 38 * scale), (x + 27 * scale, y + 48 * scale), (x + 9 * scale, y + 38 * scale), (x + 9 * scale, y + 18 * scale)]
        target = points[int((progress * len(points) + 0.5) % len(points))]
        draw_glow_dot(draw, target[0], target[1], THEME["amber"], 0.28 + 0.12 * pulse)
    elif kind == "folder":
        tab_alpha = 80 + int(80 * (0.5 + 0.5 * math.sin(phase)))
        draw.line((x + 8 * scale, y + 18 * scale, x + 40 * scale, y + 18 * scale), fill=hex_rgba(color, tab_alpha), width=1)
    elif kind == "file":
        cursor_y = y + 14 * scale + 14 * scale * ((progress * 1.3) % 1.0)
        draw.line((x + 13 * scale, cursor_y, x + 34 * scale, cursor_y), fill=hex_rgba(THEME["white"], 120), width=1)
    elif kind == "hash":
        shift = 2 * math.sin(phase)
        draw.line((x + 12 * scale, y + 22 * scale + shift, x + 42 * scale, y + 22 * scale + shift), fill=hex_rgba(THEME["amber"], 140), width=1)
        draw.line((x + 12 * scale, y + 34 * scale - shift, x + 42 * scale, y + 34 * scale - shift), fill=hex_rgba(THEME["white"], 110), width=1)


def draw_icon_motion_layer(draw, spec, progress, idx, plan=None):
    icons = collect_icon_instances(spec, plan)
    if not icons:
        return
    active = (idx // 4) % len(icons)
    for instance in icons:
        kind = instance["kind"]
        x = instance["x"]
        y = instance["y"]
        scale = instance.get("scale", 1.0)
        color = instance.get("color", THEME["cyan"])
        ordinal = instance.get("ordinal", 0)
        cx, cy = icon_center(kind, x, y, scale)
        phase = math.tau * (progress * 2.0 + ordinal * 0.083)
        is_active = ordinal == active
        draw_icon_halo(draw, cx, cy, color, phase, is_active)
        draw_orbit_dot(draw, cx, cy, color, progress, ordinal, is_active)
        draw_icon_specific_motion(draw, kind, x, y, scale, color, progress, phase, is_active)


def animate_frame(base, idx, total, spec=None, icon_motion=True, plan=None):
    plan = plan or CURRENT_PLAN or graph_model.build_plan(spec or {})
    frame = base.convert("RGBA")
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    progress = idx / total
    paths = [[(snap4(px), snap4(py)) for px, py in fp["points"]] for fp in plan["flow_paths"]]
    paths = [(pts, THEME[fp["color"]], fp["offset"]) for pts, fp in zip(paths, plan["flow_paths"])]
    flow_speed = 1          # integer loops per GIF -> seamless; keep slow & readable
    heads_per_path = 2      # multiple dots streaming along each arrow (effect B)
    trail_dots = 6          # comet tail length (effect C)
    trail_step = 0.020
    for points, color, offset in paths:
        for h in range(heads_per_path):
            head_t = (progress * flow_speed + offset + h / heads_per_path) % 1.0
            draw_flow_segment(draw, points, color, head_t)   # effect A
            for k in range(trail_dots):                       # effect C + D
                tt = head_t - k * trail_step
                if tt < 0:
                    continue
                strength = 0.95 * (1.0 - k / trail_dots) ** 1.25
                x, y = point_at_fraction(points, tt)
                draw_glow_dot(draw, x, y, color, strength)
    if icon_motion:
        draw_icon_motion_layer(draw, spec, progress, idx, plan)
    pulse_targets = [(tuple(pt["box"]), THEME[pt["color"]]) for pt in plan["pulse_targets"]]
    if pulse_targets:
        active = (idx // 6) % len(pulse_targets)
        for pos, (rect, color) in enumerate(pulse_targets):
            if pos == active:
                pulse_rect(draw, rect, color, progress * math.tau * 2, 12)
    frame.alpha_composite(overlay)
    return frame.convert("RGB")


ICON_GLYPH_FRAMES = 24


def icon_requests(spec, plan=None):
    seen = []
    for inst in collect_icon_instances(spec, plan):
        if is_custom_icon(inst["kind"]):
            # Custom icons are painted statically by icon(); the browser glyph
            # engine only serves the bundled Tabler set.
            continue
        key = (resolve_icon_name(inst["kind"]), inst.get("color", THEME["cyan"]))
        if key not in seen:
            seen.append(key)
    return seen


def stamp_glyphs(base_rgb, spec, glyph_frames, gif_t, plan=None):
    if not glyph_frames:
        return base_rgb
    total = ICON_GLYPH_FRAMES
    pick = int(round(gif_t * total)) % total
    canvas = base_rgb.convert("RGBA")
    for inst in collect_icon_instances(spec, plan):
        key = (resolve_icon_name(inst["kind"]), inst.get("color", THEME["cyan"]))
        seq = glyph_frames.get(key)
        if not seq:
            continue
        scale = inst.get("scale", 1.0)
        glyph_side = int(round((ICON_TILE - 2 * ICON_PAD) * scale))
        if glyph_side <= 0:
            continue
        glyph = seq[pick % len(seq)]
        if glyph.size != (glyph_side, glyph_side):
            glyph = glyph.resize((glyph_side, glyph_side), Image.Resampling.LANCZOS)
        ox = int(round(inst["x"] + ICON_PAD * scale))
        oy = int(round(inst["y"] + ICON_PAD * scale))
        canvas.alpha_composite(glyph, (ox, oy))
    return canvas.convert("RGB")


def render_browser_glyphs(spec, plan=None):
    if icon_browser is None or not icon_browser.is_available():
        return {}
    glyph_px = int(round((ICON_TILE - 2 * ICON_PAD)))
    requests = icon_requests(spec, plan)
    if not requests:
        return {}
    return icon_browser.render_glyph_frames(
        requests,
        glyph_px=max(28, glyph_px),
        frames=ICON_GLYPH_FRAMES,
        base_color=THEME["white"],
        stroke=2.0,
    )


def spec_uses_illustrations(node):
    if isinstance(node, dict):
        return node.get("icon_style") in ("illustrated", "hero") or any(spec_uses_illustrations(v) for v in node.values())
    if isinstance(node, list):
        return any(spec_uses_illustrations(v) for v in node)
    return False


def write_outputs(spec, outdir, basename, icon_engine="pillow", formats=("gif", "png", "excalidraw")):
    global ICON_GLYPH_MODE
    outdir.mkdir(parents=True, exist_ok=True)
    canvas_frames = spec.get("canvas", {}).get("frames", DEFAULT_FRAMES)

    glyph_frames = {}
    use_browser = False
    if icon_engine in ("browser", "auto") and not spec_uses_illustrations(spec):
        glyph_frames = render_browser_glyphs(spec)
        use_browser = bool(glyph_frames)
        if icon_engine == "browser" and not use_browser:
            print("warning: browser icon engine unavailable, falling back to pillow", file=sys.stderr)

    ICON_GLYPH_MODE = "skip" if use_browser else "draw"
    try:
        ex, static, ops_doc = render_static_with_ops(spec)
        plan = CURRENT_PLAN
        final = premium_finish(static, plan)
    finally:
        ICON_GLYPH_MODE = "draw"

    png_path = outdir / f"{basename}.png"
    gif_path = outdir / f"{basename}.gif"
    excalidraw_path = outdir / f"{basename}.excalidraw"

    want = set(formats)
    need_animation = "gif" in want
    if use_browser and ("png" in want or need_animation):
        png_img = stamp_glyphs(final, spec, glyph_frames, 0.0, plan)
        if "png" in want:
            png_img.save(png_path, "PNG")
        frames = [] if not need_animation else [
            animate_frame(stamp_glyphs(final, spec, glyph_frames, i / canvas_frames, plan), i, canvas_frames, spec, icon_motion=False, plan=plan)
            for i in range(canvas_frames)
        ]
    else:
        if "png" in want:
            final.save(png_path, "PNG")
        frames = [animate_frame(final, i, canvas_frames, spec, plan=plan) for i in range(canvas_frames)] if need_animation else []

    duration = int(1000 / spec.get("canvas", {}).get("fps", DEFAULT_FPS))
    if "gif" in want:
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=duration, loop=0, optimize=False)
    if "excalidraw" in want:
        ex.write(excalidraw_path)
    if "drawio" in want:
        drawio_path = outdir / f"{basename}.drawio"
        drawio_export.export_drawio(ops_doc, drawio_path)
    result = {
        "elements": len(ex.elements),
        "canvas": dict(plan["canvas"]),
        "icon_engine": "browser" if use_browser else "pillow",
        "geometry_lint": lint_geometry.lint_doc(ops_doc),
    }
    if "png" in want:
        result["png"] = str(png_path)
    if "gif" in want:
        result["gif"] = str(gif_path)
    if "excalidraw" in want:
        result["excalidraw"] = str(excalidraw_path)
    if "drawio" in want:
        result["drawio"] = str(drawio_path)
    return result


def write_outputs_browser(spec, outdir, basename, animation="flow", formats=("gif", "mp4", "png", "excalidraw")):
    """Render via the rough.js/Chromium pipeline (scripts/svg_renderer.py)."""
    global ICON_GLYPH_MODE
    outdir.mkdir(parents=True, exist_ok=True)
    ICON_GLYPH_MODE = "skip"  # ops carry the icon; skip Pillow glyph work
    try:
        ex, _static, doc = render_static_with_ops(spec)
    finally:
        ICON_GLYPH_MODE = "draw"
    geometry_lint = lint_geometry.lint_doc(doc)

    # Cache: if every requested artifact for this exact doc + animation preset
    # is already on disk, skip Chromium entirely (a no-op re-render becomes
    # near-instant). Misses fall through to the full browser pipeline.
    # The salt must cover every spec-level option that changes output without
    # altering the ops document — text_outlines (font-free SVG) and
    # fast_capture (rAF frame path) — or a cached run collides across options.
    text_outlines = bool(spec.get("text_outlines"))
    fast_capture = bool(spec.get("fast_capture"))
    cache_salt = f"{animation}|to={int(text_outlines)}|fc={int(fast_capture)}"
    if render_cache is not None:
        cached = render_cache.lookup(doc, outdir, basename, formats, salt=cache_salt)
        if cached is not None:
            cached["geometry_lint"] = geometry_lint
            return cached

    browser_formats = [f for f in formats if f in ("png", "gif", "mp4", "svg", "html", "webp", "avif", "pdf")]
    result = svg_renderer.render_all(doc, outdir, basename, animation=animation,
                                     formats=browser_formats, text_outlines=text_outlines,
                                     fast_capture=fast_capture)

    if "excalidraw" in formats:
        excalidraw_path = outdir / f"{basename}.excalidraw"
        ex.write(excalidraw_path)
        result["excalidraw"] = str(excalidraw_path)
    if "drawio" in formats:
        drawio_path = outdir / f"{basename}.drawio"
        drawio_export.export_drawio(doc, drawio_path)
        result["drawio"] = str(drawio_path)
    if "lottie" in formats and lottie_export is not None:
        lottie_path = outdir / f"{basename}.json"
        try:
            lottie_export.export_lottie(doc, lottie_path)
            result["lottie"] = str(lottie_path)
        except Exception as exc:  # never let lottie failure abort the pipeline
            result["lottie_skipped"] = str(exc)[:200]
    result["elements"] = len(ex.elements)
    result["canvas"] = dict(doc["canvas"])
    result["renderer"] = "browser"
    result["geometry_lint"] = geometry_lint
    if render_cache is not None:
        render_cache.store(doc, outdir, basename, result, formats, salt=cache_salt)
    return result


def frame_diff_report(gif_path):
    with Image.open(gif_path) as im:
        picks = [0, max(1, im.n_frames // 4), max(2, im.n_frames // 2), max(3, 3 * im.n_frames // 4), im.n_frames - 1]
        frames = []
        for idx in picks:
            im.seek(idx)
            frames.append(im.convert("RGB"))
        frame_count = im.n_frames
    diffs = []
    for left, right, a, b in zip(frames, frames[1:], picks, picks[1:]):
        diff = ImageChops.difference(left, right)
        bbox = diff.getbbox()
        changed = 0
        if bbox:
            cropped = diff.crop(bbox)
            data = cropped.get_flattened_data() if hasattr(cropped, "get_flattened_data") else cropped.getdata()
            changed = sum(1 for px in data if px != (0, 0, 0))
        diffs.append({"from": a, "to": b, "changed_pixels": changed})
    return {"frames": frame_count, "diffs": diffs}


def _probe_mp4(mp4_path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,pix_fmt,nb_frames,r_frame_rate",
        "-of", "json", str(mp4_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    streams = json.loads(proc.stdout).get("streams", [])
    return streams[0] if streams else None


def _graph_content_bounds(plan):
    xs, ys = [], []
    for node in plan.get("graph_nodes", []):
        x, y, w, h = node["_box"]
        xs.extend([x, x + w])
        ys.extend([y, y + h])
    for grp in plan.get("graph_groups", []):
        x, y, w, h = grp["box"]
        xs.extend([x, x + w])
        ys.extend([y, y + h])
    for edge in plan.get("graph_edges", []):
        for x, y in edge.get("points", []):
            xs.append(x)
            ys.append(y)
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def graph_layout_checks(spec):
    if graph_model.get_layout(spec) != "graph":
        return []
    plan = graph_model.build_plan(spec)
    width, height = plan["canvas"]["width"], plan["canvas"]["height"]
    bounds = _graph_content_bounds(plan)
    checks = []
    if bounds:
        left, top, right, bottom = bounds
        pad = 18
        checks.append({
            "name": "graph_content_inside_canvas",
            "ok": left >= pad and top >= 117 and right <= width - pad and bottom <= height - 96,
            "bounds": [round(left), round(top), round(right), round(bottom)],
            "canvas": {"width": width, "height": height},
            "fix": "switch to direction:'down', reduce graph nodes, or let graph use its natural canvas",
        })
        content_h = bottom - top
        # Measure against the usable content area (canvas minus title zone and
        # bottom margin), not the raw canvas, so legitimately shallow graphs
        # (e.g. imported Mermaid chains) aren't flagged as top-heavy.
        usable_h = max(1, height - 117 - 96)
        checks.append({
            "name": "graph_vertical_balance",
            "ok": content_h / usable_h >= 0.40,
            "content_ratio": round(content_h / usable_h, 3),
            "fix": "avoid forcing a tall canvas for a shallow graph; graph now ignores width/height overrides",
        })
    meta = plan.get("graph_meta", {})
    checks.append({
        "name": "graph_long_chain_orientation",
        "ok": not (meta.get("requested_direction") == "right" and meta.get("n_layers", 0) > 7 and not meta.get("auto_stacked")),
        "layers": meta.get("n_layers"),
        "actual_direction": "right" if meta.get("horizontal") else "down",
        "fix": "use direction:'down' for more than 7 sequential layers",
    })
    return checks


def check_outputs(result, spec):
    """Validate whichever artifacts are present in the render result.

    GIF/PNG/Excalidraw checks preserve the classic contract; MP4 is
    validated when produced. Missing artifact keys are simply skipped so the
    same checker covers every --formats combination.
    """
    canvas = spec.get("canvas", {})
    result_canvas = result.get("canvas", {})
    expected_width = result_canvas.get("width") or canvas.get("width", DEFAULT_W)
    expected_height = result_canvas.get("height") or canvas.get("height", DEFAULT_H)
    expected_frames = result.get("frames", canvas.get("frames", DEFAULT_FRAMES))
    expected_fps = canvas.get("fps", DEFAULT_FPS)

    checks = []

    if "gif" in result:
        gif_path = Path(result["gif"])
        with Image.open(gif_path) as gif:
            gif_width = gif.width
            gif_height = gif.height
            gif_frames = gif.n_frames
            duration_ms = gif.info.get("duration")
        actual_fps = round(1000 / duration_ms, 3) if duration_ms else None
        checks.extend(
            [
                {"name": "gif_exists", "ok": gif_path.is_file()},
                {"name": "gif_width", "ok": gif_width == expected_width, "expected": expected_width, "actual": gif_width},
                {"name": "gif_height", "ok": gif_height == expected_height, "expected": expected_height, "actual": gif_height},
                {"name": "gif_frames", "ok": gif_frames == expected_frames, "expected": expected_frames, "actual": gif_frames},
                {"name": "gif_fps", "ok": duration_ms == int(1000 / expected_fps), "expected": expected_fps, "actual": actual_fps},
            ]
        )

        diff_report = frame_diff_report(gif_path)
        checks.append(
            {
                "name": "gif_has_motion",
                "ok": any(item["changed_pixels"] > 0 for item in diff_report["diffs"]),
                "diffs": diff_report["diffs"],
            }
        )

    if "mp4" in result:
        mp4_path = Path(result["mp4"])
        checks.append({"name": "mp4_exists", "ok": mp4_path.is_file() and mp4_path.stat().st_size > 0})
        stream = _probe_mp4(mp4_path)
        if stream is not None:
            checks.extend(
                [
                    {"name": "mp4_width", "ok": int(stream.get("width", 0)) in (expected_width, expected_width - 1), "expected": expected_width, "actual": stream.get("width")},
                    {"name": "mp4_height", "ok": int(stream.get("height", 0)) in (expected_height, expected_height - 1), "expected": expected_height, "actual": stream.get("height")},
                    {"name": "mp4_pix_fmt", "ok": stream.get("pix_fmt") == "yuv420p", "actual": stream.get("pix_fmt")},
                ]
            )

    if "svg" in result:
        svg_path = Path(result["svg"])
        svg_ok = svg_path.is_file() and svg_path.stat().st_size > 0
        checks.append({"name": "svg_exists", "ok": svg_ok})
        if svg_ok:
            svg_text = svg_path.read_text(encoding="utf-8")
            if spec.get("text_outlines"):
                # Font-free mode: text must be outline paths, no @font-face left.
                checks.append({"name": "svg_text_outlined", "ok": "<text" not in svg_text and "@font-face" not in svg_text and "<path" in svg_text})
            else:
                checks.append({"name": "svg_fonts_embedded", "ok": "@font-face" in svg_text and "Excalifont" in svg_text})
            # Accessible SVG contract: role="img"; aria-labelledby resolving to
            # this diagram's prefixed <title>/<desc>; <title> as first child.
            checks.append({"name": "svg_role_img", "ok": 'role="img"' in svg_text})
            labelledby = re.search(r'aria-labelledby="([^"]+)"', svg_text)
            checks.append({
                "name": "svg_accessible_name_resolves",
                "ok": bool(labelledby) and all(f'id="{ref}"' in svg_text for ref in labelledby.group(1).split()),
            })
            checks.append({"name": "svg_title_first_child", "ok": bool(re.search(r"<svg\b[^>]*>\s*<title\b", svg_text))})

    if "html" in result:
        html_path = Path(result["html"])
        html_ok = html_path.is_file() and html_path.stat().st_size > 0
        checks.append({"name": "html_exists", "ok": html_ok})
        if html_ok:
            html_text = html_path.read_text(encoding="utf-8")
            expected_nodes = len(graph_model.build_graph(spec)["nodes"])
            hotspots = html_text.count('class="hotspot"')
            checks.extend(
                [
                    {"name": "html_hotspots", "ok": hotspots == expected_nodes, "expected": expected_nodes, "actual": hotspots},
                    {"name": "html_graph_embedded", "ok": "DIAGRAMFORGE_GRAPH" in html_text},
                    {"name": "html_fonts_embedded", "ok": "@font-face" in html_text},
                ]
            )

    if "excalidraw" in result:
        excalidraw_path = Path(result["excalidraw"])
        excalidraw = json.loads(excalidraw_path.read_text(encoding="utf-8"))
        elements = excalidraw.get("elements", [])
        ids = [element.get("id") for element in elements]
        text_elements = [element for element in elements if element.get("type") == "text"]
        checks.extend(
            [
                {"name": "excalidraw_exists", "ok": excalidraw_path.is_file()},
                {"name": "excalidraw_unique_ids", "ok": len(ids) == len(set(ids))},
                {"name": "excalidraw_text_font_family", "ok": all(element.get("fontFamily") == 5 for element in text_elements)},
                {"name": "excalidraw_files_empty", "ok": excalidraw.get("files") == {}},
            ]
        )

    if "drawio" in result:
        drawio_path = Path(result["drawio"])
        drawio_ok = drawio_path.is_file() and drawio_path.stat().st_size > 0
        checks.append({"name": "drawio_exists", "ok": drawio_ok})
        if drawio_ok:
            try:
                drawio_root = ET.parse(drawio_path).getroot()
                drawio_parsed = drawio_root.tag == "mxfile"
            except ET.ParseError:
                drawio_parsed = False
            cells = list(drawio_root.iter("mxCell")) if drawio_parsed else []
            ids = [c.get("id") for c in cells if c.get("id")]
            checks.extend(
                [
                    {"name": "drawio_valid_xml", "ok": drawio_parsed},
                    {"name": "drawio_has_content", "ok": any(c.get("vertex") == "1" or c.get("edge") == "1" for c in cells)},
                    {"name": "drawio_unique_ids", "ok": len(ids) == len(set(ids))},
                    {"name": "drawio_page_size", "ok": drawio_parsed and (
                        int(drawio_root.find(".//mxGraphModel").get("pageWidth", "0")) == expected_width
                        and int(drawio_root.find(".//mxGraphModel").get("pageHeight", "0")) == expected_height),
                        "expected": [expected_width, expected_height]},
                ]
            )

    if "lottie" in result:
        lottie_path = Path(result["lottie"])
        lottie_ok = lottie_path.is_file() and lottie_path.stat().st_size > 0
        checks.append({"name": "lottie_exists", "ok": lottie_ok})
        if lottie_ok:
            lottie_data = json.loads(lottie_path.read_text(encoding="utf-8"))
            checks.extend(
                [
                    {"name": "lottie_schema", "ok": "v" in lottie_data and "layers" in lottie_data and "fr" in lottie_data},
                    {"name": "lottie_layers", "ok": len(lottie_data.get("layers", [])) >= 1, "actual": len(lottie_data.get("layers", []))},
                    {"name": "lottie_width", "ok": lottie_data.get("w") == expected_width, "expected": expected_width, "actual": lottie_data.get("w")},
                    {"name": "lottie_height", "ok": lottie_data.get("h") == expected_height, "expected": expected_height, "actual": lottie_data.get("h")},
                ]
            )

    if "png" in result:
        png_path = Path(result["png"])
        with Image.open(png_path) as png:
            png_width = png.width
            png_height = png.height
        checks.extend(
            [
                {"name": "png_exists", "ok": png_path.is_file()},
                {"name": "png_width", "ok": png_width == expected_width, "expected": expected_width, "actual": png_width},
                {"name": "png_height", "ok": png_height == expected_height, "expected": expected_height, "actual": png_height},
            ]
        )

    if "webp" in result:
        webp_path = Path(result["webp"])
        webp_ok = webp_path.is_file() and webp_path.stat().st_size > 0
        checks.append({"name": "webp_exists", "ok": webp_ok})
        if webp_ok:
            with Image.open(webp_path) as webp:
                checks.append({"name": "webp_width", "ok": webp.width == expected_width, "expected": expected_width, "actual": webp.width})
                checks.append({"name": "webp_height", "ok": webp.height == expected_height, "expected": expected_height, "actual": webp.height})

    if "avif" in result:
        avif_path = Path(result["avif"])
        avif_ok = avif_path.is_file() and avif_path.stat().st_size > 0
        checks.append({"name": "avif_exists", "ok": avif_ok})
        if avif_ok:
            with Image.open(avif_path) as avif:
                checks.append({"name": "avif_width", "ok": avif.width == expected_width, "expected": expected_width, "actual": avif.width})
                checks.append({"name": "avif_height", "ok": avif.height == expected_height, "expected": expected_height, "actual": avif.height})

    if "pdf" in result:
        pdf_path = Path(result["pdf"])
        checks.append({"name": "pdf_exists", "ok": pdf_path.is_file() and pdf_path.stat().st_size > 0})

    checks.extend(graph_layout_checks(spec))

    # Connector-geometry contract (scripts/lint_geometry.py), computed on the
    # op stream by write_outputs*/write_outputs_browser.
    if "geometry_lint" in result:
        by_cat = {}
        for v in result["geometry_lint"]:
            by_cat.setdefault(v["category"], []).append(v)
        for cat in ("diagonal-connector", "label-mask-covered", "attach-point-fan",
                    "connector-through-node", "label-line-gap", "off-grid"):
            found = by_cat.get(cat, [])
            checks.append({
                "name": f"geometry_{cat.replace('-', '_')}",
                "ok": not found,
                "violations": [v["message"] for v in found[:5]],
            })

    return {"ok": all(check["ok"] for check in checks), "checks": checks}


KNOWN_ICONS = set(ICON_ALIASES) | {"folder", "file", "scan", "shield", "db", "hash", "package"}

CUSTOM_ICON_SUFFIXES = {".svg", ".png"}


def resolve_icon_file(value, spec_dir=None):
    """Resolve an icon_file/badge_file value to an absolute Path.

    Relative paths are resolved against the spec file's directory (falling
    back to the current working directory).
    """
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (Path(spec_dir) if spec_dir else Path.cwd()) / path
    return path.resolve()


def resolve_custom_icons(spec, spec_dir=None):
    """Rewrite icon_file/badge_file entries into the internal '@<abs path>' form.

    Called once after the spec is loaded; everything downstream (layout plan,
    painters, op stream, browser renderer) only sees the '@' convention.
    """
    def walk(node):
        if isinstance(node, dict):
            if node.get("icon_file"):
                node["icon"] = "@" + str(resolve_icon_file(node["icon_file"], spec_dir))
            if node.get("badge_file"):
                node["badge_file"] = str(resolve_icon_file(node["badge_file"], spec_dir))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
    return spec

# Top-level spec keys accepted per layout; anything else earns a warning so
# agent typos ("output s", "stage") surface immediately instead of silently
# rendering defaults.
# Note: density / aspect_ratio / motion_level are accepted for forward
# compatibility but currently have no rendering effect (reserved no-ops).
COMMON_SPEC_KEYS = {"layout", "style", "sketch", "animation", "title", "subtitle", "signature", "canvas", "density", "aspect_ratio", "motion_level", "theme_file"}
LAYOUT_SPEC_KEYS = {
    "panorama": COMMON_SPEC_KEYS | {
        "input_title", "input_style", "inputs", "core", "decision", "output", "loop_label", "retry_label",
        "left_panel", "center_panel", "right_panel",
    },
    "swimlane": COMMON_SPEC_KEYS | {"lanes", "connections", "legend", "footer"},
    "graph": COMMON_SPEC_KEYS | {"nodes", "edges", "direction", "groups", "legend", "footer"},
    "grid": COMMON_SPEC_KEYS | {"cells", "columns", "legend", "footer"},
    "sequence": COMMON_SPEC_KEYS | {"participants", "messages", "fragments", "footer"},
    "er": COMMON_SPEC_KEYS | {"entities", "relations", "footer"},
    "usecase": COMMON_SPEC_KEYS | {"actors", "system", "usecases", "links", "footer"},
    "class": COMMON_SPEC_KEYS | {"classes", "relations", "footer"},
    "activity": COMMON_SPEC_KEYS | {"nodes", "edges", "direction", "footer"},
    "state": COMMON_SPEC_KEYS | {"states", "transitions", "footer"},
    "dfd": COMMON_SPEC_KEYS | {"nodes", "flows", "footer"},
    "deployment": COMMON_SPEC_KEYS | {"nodes", "connections", "footer"},
    "component": COMMON_SPEC_KEYS | {"components", "interfaces", "relations", "footer"},
    "package": COMMON_SPEC_KEYS | {"packages", "relations", "footer"},
    "object": COMMON_SPEC_KEYS | {"objects", "links", "footer"},
    "composite": COMMON_SPEC_KEYS | {"classifier", "parts", "ports", "connectors", "footer"},
    "profile": COMMON_SPEC_KEYS | {"stereotypes", "metaclasses", "extensions", "relations", "footer"},
    "communication": COMMON_SPEC_KEYS | {"objects", "links", "footer"},
    "timing": COMMON_SPEC_KEYS | {"lifelines", "messages", "footer"},
    "interaction": COMMON_SPEC_KEYS | {"nodes", "edges", "footer"},
    "c4": COMMON_SPEC_KEYS | {"elements", "boundaries", "relations", "footer"},
    "gantt": COMMON_SPEC_KEYS | {"sections", "footer"},
    "bpmn": COMMON_SPEC_KEYS | {"pools", "elements", "flows", "lane_label", "footer"},
    "orgchart": COMMON_SPEC_KEYS | {"nodes", "footer"},
    "mindmap": COMMON_SPEC_KEYS | {"root", "footer"},
    "timeline": COMMON_SPEC_KEYS | {"events", "footer"},
    "fishbone": COMMON_SPEC_KEYS | {"problem", "categories", "footer"},
}


def validate_spec(spec, spec_dir=None):
    """Pre-flight validation with agent-actionable messages.

    Errors block rendering (wrong shapes, missing required sections).
    Warnings render fine but flag likely mistakes (unknown keys/icons,
    overlong labels that will shrink or wrap).
    """
    errors, warnings = [], []

    def err(path, message, fix):
        errors.append({"path": path, "message": message, "fix": fix})

    def warn(path, message, fix):
        warnings.append({"path": path, "message": message, "fix": fix})

    if not isinstance(spec, dict):
        err("$", "spec must be a JSON object", "wrap the content in an object: {\"layout\": ..., ...}")
        return {"ok": False, "errors": errors, "warnings": warnings}

    for key in ("title", "canvas"):
        if key in spec and not isinstance(spec[key], dict):
            err(f"$.{key}", "must be an object", f'use "{key}": {{...}}')
    for key in ("core", "decision", "output", "left_panel", "center_panel", "right_panel", "center"):
        if key in spec and spec[key] is not None and not isinstance(spec[key], dict):
            err(f"$.{key}", "must be an object", f'use "{key}": {{...}}')
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

    canvas = spec.get("canvas", {})
    preset = canvas.get("preset")
    if preset is not None and preset not in CANVAS_PRESETS:
        err("$.canvas.preset", f"unknown canvas preset '{preset}'",
            f"use one of: {', '.join(sorted(CANVAS_PRESETS))} (or set width/height explicitly)")
    limits = {"width": (480, 4096), "height": (360, 4096), "fps": (1, 60), "frames": (2, 600)}
    for key, (lo, hi) in limits.items():
        if key in canvas and (not isinstance(canvas[key], (int, float)) or isinstance(canvas[key], bool) or not lo <= canvas[key] <= hi):
            err(f"$.canvas.{key}", f"must be a number from {lo} to {hi}", f"set {key} within {lo}..{hi}")
    if spec.get("density", "balanced") not in ("airy", "balanced", "compact"):
        err("$.density", "unknown density", "use airy, balanced, or compact")
    if spec.get("aspect_ratio", "auto") not in ("auto", "landscape", "portrait", "square"):
        err("$.aspect_ratio", "unknown aspect_ratio", "use auto, landscape, portrait, or square")
    if spec.get("motion_level", "standard") not in ("none", "subtle", "standard", "cinematic"):
        err("$.motion_level", "unknown motion_level", "use none, subtle, standard, or cinematic")

    layout = spec.get("layout", "panorama")
    if layout not in graph_model.LAYOUTS:
        err("$.layout", f"unknown layout '{layout}'", f"use one of: {', '.join(graph_model.LAYOUTS)}")
        layout = "panorama"

    style = spec.get("style", "slate")
    if style not in STYLE_THEMES and style != "custom":
        err("$.style", f"unknown style '{style}'", f"use one of: {', '.join(STYLE_THEMES)}, or custom")
    if style == "custom":
        theme_file = spec.get("theme_file")
        if theme_file is not None and not isinstance(theme_file, str):
            err("$.theme_file", "must be a path string", "point it at a theme JSON file")
        elif isinstance(theme_file, str) and spec_dir is not None and not (Path(spec_dir) / theme_file).is_file():
            err("$.theme_file", f"theme file not found: {theme_file}",
                "check the path; relative paths resolve against the spec file's folder")
        elif theme_file is None and spec_dir is not None and theme_loader.find_marker(spec_dir) is None:
            err("$.style", "style 'custom' needs a theme source",
                "set theme_file in the spec, or add a .diagramforge marker containing 'theme: <slug>'")
        elif theme_file is None and spec_dir is None:
            warn("$.style", "style 'custom' without theme_file cannot be verified here",
                 "validate via the CLI with the spec file path so the .diagramforge marker can be found")
    if "sketch" in spec and not isinstance(spec["sketch"], bool):
        err("$.sketch", "must be true or false", "set sketch to true for the hand-drawn look, or drop it for formal output")
    animation = spec.get("animation", "flow")
    if animation not in ANIMATION_CHOICES:
        err("$.animation", f"unknown animation '{animation}'", f"use one of: {', '.join(ANIMATION_CHOICES)}")

    for key in sorted(set(spec) - LAYOUT_SPEC_KEYS[layout]):
        warn(f"$.{key}", f"unknown key for layout '{layout}' (ignored)",
             f"valid keys: {', '.join(sorted(LAYOUT_SPEC_KEYS[layout]))}")

    if len(str(spec.get("signature", ""))) > 28:
        warn("$.signature", "is very long; the brand block will shift far into the title area",
             "keep the signature under ~28 chars")

    def check_icon_file(path, value):
        file_path = resolve_icon_file(value, spec_dir)
        if file_path.suffix.lower() not in CUSTOM_ICON_SUFFIXES:
            err(path, f"unsupported icon file type '{file_path.suffix or value}'",
                "use a local .svg or .png file")
        elif not file_path.is_file():
            err(path, f"file not found: {file_path}",
                "check the path; relative paths resolve against the spec file's folder")

    def check_icon(path, item):
        if item.get("icon_style", "outline") not in ("outline", "illustrated", "hero"):
            err(f"{path}.icon_style", "unknown icon style", "use outline, illustrated, or hero")
        if item.get("icon_size", "standard") not in ("compact", "standard", "hero"):
            err(f"{path}.icon_size", "unknown icon size", "use compact, standard, or hero")
        allowed_motion = ("auto", "none", "think-pulse", "gear-spin", "eye-scan", "memory-write",
                          "shield-check", "scope-scan", "budget-gauge", "trigger-ping", "tool-spark", "output-pop")
        if item.get("icon_motion", "auto") not in allowed_motion:
            err(f"{path}.icon_motion", "unknown icon motion", f"use one of: {', '.join(allowed_motion)}")
        if item.get("icon_file"):
            check_icon_file(f"{path}.icon_file", item["icon_file"])
            return
        icon_name = item.get("icon")
        if is_custom_icon(icon_name):
            return
        if icon_name and resolve_icon_name(icon_name) not in KNOWN_ICONS and (
            find_icon_svg(resolve_icon_name(icon_name)) is None
        ):
            warn(f"{path}.icon", f"unknown icon '{icon_name}' (a plain circle will be drawn)",
                 "pick one from assets/icons/tabler/, assets/icons/vendor/<pack>/, or the aliases in references/spec-format.md")

    def check_legend():
        legend = spec.get("legend")
        if legend is None:
            return
        if not isinstance(legend, list):
            err("$.legend", "must be a list", 'use [{"color": "green", "label": "reused"}, ...] (up to 6)')
            return
        for i, item in enumerate(legend[:6]):
            if not isinstance(item, dict):
                continue
            if item.get("color") not in THEME:
                warn(f"$.legend[{i}].color", f"unknown color '{item.get('color')}' (muted used)",
                     f"use a THEME key such as: green, purple, amber, pink, cyan, muted")
            if len(str(item.get("label", ""))) > 24:
                warn(f"$.legend[{i}].label", "is long; legend text will shrink to fit",
                     "keep legend labels under ~24 chars")
        if len(legend) > 6:
            warn("$.legend", f"has {len(legend)} items; only the first 6 are rendered", "trim to 6")

    def check_items(path, items, min_n, max_n, label_key, label_max, required):
        if not isinstance(items, list):
            err(path, "must be a list", f"provide {min_n}-{max_n} objects")
            return
        if required and len(items) < min_n:
            err(path, f"needs at least {min_n} items (got {len(items)})", "add more items or switch layout")
        if len(items) > max_n:
            dropped = [str(x.get(label_key, "?")) if isinstance(x, dict) else "?" for x in items[max_n:]]
            warn(path, f"has {len(items)} items; only the first {max_n} are rendered "
                       f"(dropped: {', '.join(dropped)})", f"trim to {max_n}")
        for i, item in enumerate(items[:max_n]):
            if not isinstance(item, dict):
                err(f"{path}[{i}]", "must be an object", f'use {{"{label_key}": "...", "icon": "..."}}')
                continue
            text = item.get(label_key, "")
            if not text:
                warn(f"{path}[{i}].{label_key}", "is empty", "add a short label so the box is not blank")
            elif len(str(text)) > label_max:
                warn(f"{path}[{i}].{label_key}", f"is long ({len(str(text))} chars); text will shrink to fit",
                     f"keep it under ~{label_max} chars")
            check_icon(f"{path}[{i}]", item)

    if layout == "panorama":
        input_style = spec.get("input_style", "boxed")
        if input_style not in ("boxed", "plain"):
            err("$.input_style", f"unknown input_style '{input_style}'",
                "use 'boxed' (default, framed tiles) or 'plain' (frameless colored icons)")
        check_items("$.inputs", spec.get("inputs", []), 2, 6, "label", 16, required=True)
        cards = spec.get("core", {}).get("cards", [])
        check_items("$.core.cards", cards, 2, 4, "title", 18, required=True)
        if spec.get("left_panel", {}).get("badge_file"):
            check_icon_file("$.left_panel.badge_file", spec["left_panel"]["badge_file"])
        for panel in ("left_panel", "center_panel", "right_panel"):
            if panel in spec and not spec.get(panel, {}).get("cards"):
                warn(f"$.{panel}.cards", "is empty, so the whole panel is omitted",
                     "add 1-4 cards or drop the panel key")
            max_cards = 4 if panel == "center_panel" else 3
            check_items(f"$.{panel}.cards", spec.get(panel, {}).get("cards", []), 0, max_cards, "title", 16, required=False)
    elif layout == "swimlane":
        lanes = spec.get("lanes", [])
        if "lanes" not in spec:
            err("$.lanes", "is required for the swimlane layout",
                'add "lanes": [{"title": ..., "subtitle": ..., "steps": [...]}, ...] (2-8 items)')
        check_items("$.lanes", lanes, 2, 8, "title", 20, required=True)
        if isinstance(lanes, list):
            for i, lane in enumerate(lanes[:8]):
                if isinstance(lane, dict):
                    check_items(f"$.lanes[{i}].steps", lane.get("steps", []), 1, 8, "title", 22, required=True)
                    if len(str(lane.get("subtitle", ""))) > 60:
                        warn(f"$.lanes[{i}].subtitle", "is long; the title column will shrink it hard",
                             "keep lane subtitles under ~60 chars")
                    if len(str(lane.get("caption", ""))) > 120:
                        warn(f"$.lanes[{i}].caption", "is long; the caption row will shrink it hard",
                             "keep lane captions under ~120 chars")
                    if lane.get("accent") is not None and lane["accent"] not in ("green", "purple", "amber"):
                        warn(f"$.lanes[{i}].accent", f"unknown accent '{lane['accent']}' (alternating tint used)",
                             "use green, purple, or amber")
                    for j, step in enumerate(lane.get("steps", [])[:8]):
                        if isinstance(step, dict) and len(str(step.get("note", ""))) > 40:
                            warn(f"$.lanes[{i}].steps[{j}].note", "is long; the note under the card will shrink hard",
                                 "keep step notes under ~40 chars")
        if "connections" in spec and not isinstance(spec["connections"], list):
            err("$.connections", "must be a list", 'use [{"from": "step-id", "to": "step-id"}]')
        check_legend()
    elif layout == "grid":
        cells = spec.get("cells", [])
        if "cells" not in spec:
            err("$.cells", "is required for the grid layout",
                'add "cells": [{"title": ..., "steps": [{"title": ..., "icon": ...}]}, ...] (2-9 items)')
        check_items("$.cells", cells, 2, 9, "title", 20, required=True)
        if spec.get("columns") is not None and spec["columns"] not in (2, 3):
            err("$.columns", "must be 2 or 3", "omit for automatic columns (2 up to 4 cells, else 3)")
        if isinstance(cells, list):
            for i, cell in enumerate(cells[:9]):
                if isinstance(cell, dict):
                    check_items(f"$.cells[{i}].steps", cell.get("steps", []), 1, 6, "title", 20, required=True)
                    if cell.get("accent") is not None and cell["accent"] not in ("green", "purple", "amber"):
                        warn(f"$.cells[{i}].accent", f"unknown accent '{cell['accent']}' (alternating tint used)",
                             "use green, purple, or amber")
        check_legend()
    elif layout == "graph":
        if spec.get("direction", "right") not in ("right", "down"):
            err("$.direction", "unknown direction", "use 'right' (default) or 'down'")
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the graph layout",
                'add "nodes": [{"id": "plan", "label": "Plan", "icon": "plan"}, ...] (2-24 items)')
        check_items("$.nodes", nodes, 2, 24, "label", 20, required=True)
        groups = spec.get("groups", [])
        check_items("$.groups", groups, 0, 4, "label", 24, required=False)
        group_ids = {g.get("id") for g in groups if isinstance(g, dict)} if isinstance(groups, list) else set()
        node_ids = set()
        if isinstance(nodes, list):
            if spec.get("direction", "right") == "right" and len(nodes) > 8 and not any(
                isinstance(node, dict) and isinstance(node.get("x"), (int, float)) and isinstance(node.get("y"), (int, float))
                for node in nodes
            ):
                warn("$.direction", "long graph chains are auto-stacked downward",
                     "use direction:'down' explicitly, or reduce to 8 or fewer sequential nodes for a rightward graph")
            if any(key in canvas for key in ("width", "height")):
                warn("$.canvas", "graph layout owns width/height to prevent clipping or dead space",
                     "use canvas fps/frames for animation timing; omit width/height unless you also pin node coordinates")
            for i, node in enumerate(nodes[:24]):
                if not isinstance(node, dict):
                    continue
                nid = node.get("id")
                if not nid:
                    warn(f"$.nodes[{i}].id", "is missing; an auto id will be assigned",
                         "give every node a short stable id so edges can reference it")
                elif str(nid) in node_ids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                node_ids.add(str(nid) if nid else f"n{i}")
                if node.get("kind", "card") not in graph_model.GRAPH_NODE_KINDS:
                    err(f"$.nodes[{i}].kind", f"unknown kind '{node.get('kind')}'",
                        "use card (default), decision, or terminal")
                if node.get("accent") is not None and node["accent"] not in graph_model.GRAPH_ACCENTS:
                    warn(f"$.nodes[{i}].accent", f"unknown accent '{node['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.GRAPH_ACCENTS))}")
                has_x, has_y = isinstance(node.get("x"), (int, float)), isinstance(node.get("y"), (int, float))
                if has_x != has_y:
                    warn(f"$.nodes[{i}]", "has only one of x/y; the node falls back to auto layout",
                         "give both x and y (box center) or neither")
                if node.get("parent") is not None and node.get("parent") not in group_ids:
                    err(f"$.nodes[{i}].parent", f"unknown group '{node.get('parent')}'",
                        'declare it in "groups": [{"id": "...", "label": "..."}]')
                if has_x and has_y:
                    if node["y"] < 165:
                        warn(f"$.nodes[{i}]", "pinned inside the title zone (y < 165); text will collide with the title",
                             "keep pinned node centers at y >= 165")
                    elif node["x"] > 930 and node["y"] < 215:
                        warn(f"$.nodes[{i}]", "pinned inside the signature zone (top right); it will collide with the brand signature",
                             "keep the x > 930 / y < 215 corner clear of pinned nodes")
        edges = spec.get("edges", [])
        if not isinstance(edges, list):
            err("$.edges", "must be a list",
                'use [{"from": "plan", "to": "act"}, {"from": "check", "to": "plan", "kind": "loop"}]')
        else:
            if len(edges) > 40:
                warn("$.edges", f"has {len(edges)} edges; only the first 40 are rendered", "trim to 40")
            for i, edge in enumerate(edges[:40]):
                if not isinstance(edge, dict):
                    err(f"$.edges[{i}]", "must be an object", 'use {"from": "id", "to": "id"}')
                    continue
                for end in ("from", "to"):
                    if not edge.get(end):
                        err(f"$.edges[{i}].{end}", "is required", "reference a node id")
                    elif node_ids and str(edge[end]) not in node_ids:
                        err(f"$.edges[{i}].{end}", f"references unknown node '{edge[end]}'",
                            f"use one of: {', '.join(sorted(node_ids))}")
                if edge.get("kind", "flow") not in ("flow", "loop"):
                    err(f"$.edges[{i}].kind", f"unknown kind '{edge.get('kind')}'",
                        "use flow (default) or loop (dashed return channel)")
                if edge.get("accent") is not None and edge["accent"] not in graph_model.GRAPH_ACCENTS:
                    warn(f"$.edges[{i}].accent", f"unknown accent '{edge['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.GRAPH_ACCENTS))}")
                if edge.get("label") and len(str(edge["label"])) > 24:
                    warn(f"$.edges[{i}].label", "is long; edge labels shrink to fit",
                         "keep edge labels under ~24 chars")
        check_legend()
    elif layout == "sequence":
        fragments = spec.get("fragments", [])
        participants = spec.get("participants", [])
        if "participants" not in spec:
            err("$.participants", "is required for the sequence layout",
                'add "participants": [{"id": "user", "label": "用户", "kind": "actor"}, ...] (2-8 items)')
        check_items("$.participants", participants, 2, 8, "label", 16, required=True)
        pids = []
        if isinstance(participants, list):
            for i, p in enumerate(participants[:8]):
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                if not pid:
                    err(f"$.participants[{i}].id", "is required",
                        "give each participant a short stable id so messages can reference it")
                elif str(pid) in pids:
                    err(f"$.participants[{i}].id", f"duplicate id '{pid}'", "make participant ids unique")
                pids.append(str(pid) if pid else f"p{i}")
                if p.get("kind", "system") not in graph_model.SEQUENCE_PARTICIPANT_KINDS:
                    err(f"$.participants[{i}].kind", f"unknown kind '{p.get('kind')}'",
                        "use actor (person) or system (default)")
                if p.get("accent") is not None and p["accent"] not in graph_model.SEQUENCE_ACCENTS:
                    warn(f"$.participants[{i}].accent", f"unknown accent '{p['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.SEQUENCE_ACCENTS))}")
        messages = spec.get("messages", [])
        if "messages" not in spec:
            err("$.messages", "is required for the sequence layout",
                'add "messages": [{"from": "user", "to": "gw", "label": "提交订单", "kind": "sync"}, ...]')
        if not isinstance(messages, list):
            err("$.messages", "must be a list", 'use [{"from": "a", "to": "b", "label": "..."}]')
        else:
            if not messages:
                err("$.messages", "needs at least 1 message", "add the first call between two participants")
            if len(messages) > 30:
                warn("$.messages", f"has {len(messages)} messages; only the first 30 are rendered",
                     "trim to 30 or split the scenario into two diagrams")
            for i, m in enumerate(messages[:30]):
                if not isinstance(m, dict):
                    err(f"$.messages[{i}]", "must be an object", 'use {"from": "a", "to": "b", "label": "..."}')
                    continue
                kind = m.get("kind", "sync")
                if kind not in graph_model.SEQUENCE_MESSAGE_KINDS:
                    err(f"$.messages[{i}].kind", f"unknown kind '{kind}'",
                        "use sync, async, return, self, or note")
                    continue
                if kind == "note":
                    if not m.get("text"):
                        warn(f"$.messages[{i}].text", "is empty", "add the note text")
                    targets = m.get("target")
                    if isinstance(targets, str):
                        targets = [targets]
                    if not isinstance(targets, list) or not targets:
                        err(f"$.messages[{i}].target", "is required for a note",
                            'use "target": "participant-id" or ["id-a", "id-b"] (spans both)')
                    else:
                        if len(targets) > 2:
                            warn(f"$.messages[{i}].target", "spans more than 2 participants; only the first 2 are used",
                                 "split into two notes")
                        for t in targets[:2]:
                            if pids and str(t) not in pids:
                                err(f"$.messages[{i}].target", f"references unknown participant '{t}'",
                                    f"use one of: {', '.join(pids)}")
                else:
                    for end in (("from",) if kind == "self" else ("from", "to")):
                        if not m.get(end):
                            err(f"$.messages[{i}].{end}", "is required", "reference a participant id")
                        elif pids and str(m[end]) not in pids:
                            err(f"$.messages[{i}].{end}", f"references unknown participant '{m[end]}'",
                                f"use one of: {', '.join(pids)}")
                    if kind == "self" and m.get("to") and str(m.get("to")) != str(m.get("from")):
                        warn(f"$.messages[{i}].to", "is ignored for a self message",
                             'a self message only needs "from"')
                    if m.get("label") and len(str(m["label"])) > 30:
                        warn(f"$.messages[{i}].label", "is long; message labels shrink to fit",
                             "keep message labels under ~30 chars")
            # Activation pairing: a return should answer an earlier sync call.
            # Returns inside an alt fragment are exempt: only one branch runs,
            # so a second branch return legitimately has no live call.
            alt_spans = []
            for f in (fragments if isinstance(fragments, list) else []):
                if isinstance(f, dict) and f.get("kind") == "alt":
                    rng = f.get("range")
                    if (isinstance(rng, list) and len(rng) == 2
                            and all(isinstance(v, int) and not isinstance(v, bool) for v in rng)
                            and 0 <= rng[0] <= rng[1] < len(messages)):
                        alt_spans.append((rng[0], rng[1]))
            stack = []
            for i, m in enumerate(messages[:30]):
                if not isinstance(m, dict):
                    continue
                kind = m.get("kind", "sync")
                auto = kind == "sync" and m.get("activate", True) is not False
                explicit = kind == "async" and m.get("activate") is True
                if (auto or explicit) and (str(m.get("from")) != str(m.get("to")) or m.get("activate") is True):
                    stack.append((str(m.get("to")), i))
                elif kind == "self" and m.get("activate"):
                    stack.append((str(m.get("from")), i))
                elif kind == "return":
                    for j in range(len(stack) - 1, -1, -1):
                        if stack[j][0] == str(m.get("from")):
                            stack.pop(j)
                            break
                    else:
                        if not any(a <= i <= b for a, b in alt_spans):
                            warn(f"$.messages[{i}]", "return answers no earlier call; its sender shows no activation bar",
                                 "add the matching sync/async message first, or check the from/to direction")
            for _, i in stack:
                warn(f"$.messages[{i}]", "call never gets a matching return; its activation bar runs to the bottom",
                     "add a return message, or set \"activate\": false to suppress the bar")
        if "fragments" in spec and not isinstance(fragments, list):
            err("$.fragments", "must be a list",
                'use [{"kind": "alt", "label": "...", "range": [start, end], "dividers": [{"at": i, "label": "..."}]}]')
        elif isinstance(fragments, list):
            if len(fragments) > 6:
                warn("$.fragments", f"has {len(fragments)} fragments; only the first 6 are rendered", "trim to 6")
            ranges = []
            for i, f in enumerate(fragments[:6]):
                if not isinstance(f, dict):
                    err(f"$.fragments[{i}]", "must be an object", 'use {"kind": "alt", "label": "...", "range": [a, b]}')
                    continue
                kind = f.get("kind", "alt")
                if kind not in graph_model.SEQUENCE_FRAGMENT_KINDS:
                    err(f"$.fragments[{i}].kind", f"unknown kind '{kind}'", "use alt, loop, or opt")
                    continue
                rng = f.get("range")
                valid_range = (isinstance(rng, list) and len(rng) == 2
                               and all(isinstance(v, int) and not isinstance(v, bool) for v in rng))
                if not valid_range:
                    err(f"$.fragments[{i}].range", "must be [start, end] message indices (0-based)",
                        f'example: "range": [0, {max(0, len(messages) - 1)}] covers all messages')
                else:
                    a, b = rng
                    if a < 0 or b >= len(messages) or a > b:
                        err(f"$.fragments[{i}].range", f"[{a}, {b}] is outside the message list (0..{max(0, len(messages) - 1)})",
                            "use 0-based indices into $.messages")
                    elif isinstance(messages[a], dict) and isinstance(messages[b], dict) and (
                        messages[a].get("kind") == "note" or messages[b].get("kind") == "note"
                    ):
                        err(f"$.fragments[{i}].range", "must start and end on a real message, not a note",
                            "move the note outside the range or adjust the indices")
                    else:
                        ranges.append((a, b, i))
                dividers = f.get("dividers", [])
                if kind == "alt":
                    if not dividers:
                        warn(f"$.fragments[{i}].dividers", "alt has no else divider; it renders as a single branch",
                             'add "dividers": [{"at": message-index, "label": "else case"}] or use opt')
                    elif not isinstance(dividers, list):
                        err(f"$.fragments[{i}].dividers", "must be a list", 'use [{"at": 2, "label": "..."}]')
                    elif valid_range:
                        for j, d in enumerate(dividers):
                            if not isinstance(d, dict) or not isinstance(d.get("at"), int):
                                err(f"$.fragments[{i}].dividers[{j}]", 'must look like {"at": 2, "label": "..."}', "")
                                continue
                            a, b = rng
                            if not a < d["at"] <= b:
                                err(f"$.fragments[{i}].dividers[{j}].at",
                                    f"{d['at']} is not inside the range ({a}, {b}]",
                                    "a divider starts a new branch, so it must sit after the range start")
                elif dividers:
                    warn(f"$.fragments[{i}].dividers", f"dividers are ignored for kind '{kind}'",
                         "only alt fragments take dividers")
            for x in range(len(ranges)):
                for y2 in range(x + 1, len(ranges)):
                    a1, b1, i1 = ranges[x]
                    a2, b2, j2 = ranges[y2]
                    overlap = a1 <= b2 and a2 <= b1
                    nested = (a1 <= a2 and b2 <= b1) or (a2 <= a1 and b1 <= b2)
                    if overlap and not nested:
                        err(f"$.fragments[{j2}].range", f"[{a2}, {b2}] crosses fragment {i1}'s range [{a1}, {b1}]",
                            "combined fragments must nest fully or not overlap at all")
            for a1, b1, i1 in ranges:
                depth = sum(1 for a2, b2, j2 in ranges if j2 != i1 and a2 <= a1 and b1 <= b2)
                if depth > 2:
                    err(f"$.fragments[{i1}].range", "is nested deeper than 2 levels",
                        "flatten the scenario or split it into two diagrams")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "sequence layout owns width/height to keep lifeline spacing readable",
                 "use canvas fps/frames for animation timing; omit width/height")
    elif layout == "er":
        entities = spec.get("entities", [])
        if "entities" not in spec:
            err("$.entities", "is required for the er layout",
                'add "entities": [{"id": "user", "label": "用户", "attributes": [...]}, ...] (2-12 items)')
        check_items("$.entities", entities, 2, 12, "label", 16, required=True)
        eids = []
        if isinstance(entities, list):
            for i, e in enumerate(entities[:12]):
                if not isinstance(e, dict):
                    continue
                eid = e.get("id")
                if not eid:
                    err(f"$.entities[{i}].id", "is required", "give each entity a short stable id")
                elif str(eid) in eids:
                    err(f"$.entities[{i}].id", f"duplicate id '{eid}'", "make entity ids unique")
                eids.append(str(eid) if eid else f"e{i}")
                attrs = e.get("attributes", [])
                if "attributes" in e and not isinstance(attrs, list):
                    err(f"$.entities[{i}].attributes", "must be a list",
                        'use [{"name": "id", "type": "int", "key": "pk"}, ...]')
                elif isinstance(attrs, list):
                    if len(attrs) > 8:
                        warn(f"$.entities[{i}].attributes", f"has {len(attrs)} attributes; only the first 8 render",
                             "trim to 8 or split the entity")
                    for j, a in enumerate(attrs[:8]):
                        if not isinstance(a, (dict, str)):
                            err(f"$.entities[{i}].attributes[{j}]", "must be an object or a string",
                                'use {"name": "id", "type": "int", "key": "pk"}')
                        elif isinstance(a, dict) and a.get("key") is not None and a.get("key") not in ("pk", "fk"):
                            err(f"$.entities[{i}].attributes[{j}].key", f"unknown key '{a.get('key')}'",
                                "use pk, fk, or omit")
                if e.get("accent") is not None and e["accent"] not in graph_model.BOX_ACCENTS:
                    warn(f"$.entities[{i}].accent", f"unknown accent '{e['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.BOX_ACCENTS))}")
        relations = spec.get("relations", [])
        if not isinstance(relations, list):
            err("$.relations", "must be a list", 'use [{"from": "user", "to": "order", "cardinality": "1:N"}]')
        else:
            if len(relations) > 16:
                warn("$.relations", f"has {len(relations)} relations; only the first 16 render", "trim to 16")
            for i, r in enumerate(relations[:16]):
                if not isinstance(r, dict):
                    err(f"$.relations[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.relations[{i}].{end}", "is required", "reference an entity id")
                    elif eids and str(r[end]) not in eids:
                        err(f"$.relations[{i}].{end}", f"references unknown entity '{r[end]}'",
                            f"use one of: {', '.join(eids)}")
                if r.get("cardinality") is not None and str(r["cardinality"]) not in graph_model.ER_CARDINALITIES:
                    err(f"$.relations[{i}].cardinality", f"unknown cardinality '{r['cardinality']}'",
                        "use 1:1, 1:N, N:1, or M:N (or set from_card/to_card directly)")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "er layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "usecase":
        actors = spec.get("actors", [])
        if "actors" not in spec:
            err("$.actors", "is required for the usecase layout",
                'add "actors": [{"id": "user", "label": "用户"}, ...] (1-6 items)')
        check_items("$.actors", actors, 1, 6, "label", 12, required=True)
        usecases = spec.get("usecases", [])
        if "usecases" not in spec:
            err("$.usecases", "is required for the usecase layout",
                'add "usecases": [{"id": "buy", "label": "下单"}, ...] (2-16 items)')
        check_items("$.usecases", usecases, 2, 16, "label", 14, required=True)
        known = []
        for group, path in ((actors, "$.actors"), (usecases, "$.usecases")):
            if isinstance(group, list):
                for i, item in enumerate(group):
                    if isinstance(item, dict):
                        iid = item.get("id")
                        if not iid:
                            err(f"{path}[{i}].id", "is required", "give every actor/usecase a stable id")
                        elif str(iid) in known:
                            err(f"{path}[{i}].id", f"duplicate id '{iid}'", "ids must be unique across actors and usecases")
                        known.append(str(iid) if iid else f"x{i}")
        if isinstance(actors, list):
            for i, a in enumerate(actors[:6]):
                if isinstance(a, dict) and a.get("side", "left") not in ("left", "right"):
                    err(f"$.actors[{i}].side", f"unknown side '{a.get('side')}'", "use left (default) or right")
        links = spec.get("links", [])
        if not isinstance(links, list):
            err("$.links", "must be a list", 'use [{"from": "user", "to": "buy"}]')
        else:
            if len(links) > 24:
                warn("$.links", f"has {len(links)} links; only the first 24 render", "trim to 24")
            uc_ids = [str(u.get("id")) for u in usecases if isinstance(u, dict) and u.get("id")] if isinstance(usecases, list) else []
            for i, l in enumerate(links[:24]):
                if not isinstance(l, dict):
                    err(f"$.links[{i}]", "must be an object", 'use {"from": "user", "to": "buy"}')
                    continue
                for end in ("from", "to"):
                    if not l.get(end):
                        err(f"$.links[{i}].{end}", "is required", "reference an actor or usecase id")
                    elif known and str(l[end]) not in known:
                        err(f"$.links[{i}].{end}", f"references unknown id '{l[end]}'",
                            f"use one of: {', '.join(known)}")
                kind = l.get("kind", "association")
                if kind not in graph_model.USECASE_LINK_KINDS:
                    err(f"$.links[{i}].kind", f"unknown kind '{kind}'", "use association, include, or extend")
                elif kind in ("include", "extend") and (
                    str(l.get("from")) not in uc_ids or str(l.get("to")) not in uc_ids
                ):
                    warn(f"$.links[{i}].kind", f"'{kind}' only applies between use cases; rendered as association",
                         "point both ends at usecase ids")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "usecase layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "class":
        classes = spec.get("classes", [])
        if "classes" not in spec:
            err("$.classes", "is required for the class layout",
                'add "classes": [{"id": "order", "label": "Order", "attributes": [...], "methods": [...]}, ...] (2-10 items)')
        check_items("$.classes", classes, 2, 10, "label", 20, required=True)
        cids = []
        if isinstance(classes, list):
            for i, c in enumerate(classes[:10]):
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if not cid:
                    err(f"$.classes[{i}].id", "is required", "give each class a stable id")
                elif str(cid) in cids:
                    err(f"$.classes[{i}].id", f"duplicate id '{cid}'", "make class ids unique")
                cids.append(str(cid) if cid else f"c{i}")
                if c.get("kind", "class") not in graph_model.CLASS_KINDS:
                    err(f"$.classes[{i}].kind", f"unknown kind '{c.get('kind')}'",
                        "use class (default), interface, abstract, or enum")
                for field, cap in (("attributes", 8), ("methods", 8)):
                    members = c.get(field, [])
                    if field in c and not isinstance(members, list):
                        err(f"$.classes[{i}].{field}", "must be a list",
                            'use [{"name": "id", "type": "Long", "visibility": "+"}, ...]')
                    elif isinstance(members, list) and len(members) > cap:
                        warn(f"$.classes[{i}].{field}", f"has {len(members)} members; only the first {cap} render",
                             f"trim to {cap} or split the class")
                if c.get("accent") is not None and c["accent"] not in graph_model.BOX_ACCENTS:
                    warn(f"$.classes[{i}].accent", f"unknown accent '{c['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.BOX_ACCENTS))}")
        relations = spec.get("relations", [])
        if not isinstance(relations, list):
            err("$.relations", "must be a list", 'use [{"from": "order", "to": "item", "kind": "composition"}]')
        else:
            if len(relations) > 16:
                warn("$.relations", f"has {len(relations)} relations; only the first 16 render", "trim to 16")
            for i, r in enumerate(relations[:16]):
                if not isinstance(r, dict):
                    err(f"$.relations[{i}]", "must be an object", 'use {"from": "a", "to": "b", "kind": "association"}')
                    continue
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.relations[{i}].{end}", "is required", "reference a class id")
                    elif cids and str(r[end]) not in cids:
                        err(f"$.relations[{i}].{end}", f"references unknown class '{r[end]}'",
                            f"use one of: {', '.join(cids)}")
                if r.get("kind", "association") not in graph_model.CLASS_RELATION_KINDS:
                    err(f"$.relations[{i}].kind", f"unknown kind '{r.get('kind')}'",
                        "use association, inheritance, realization, composition, aggregation, or dependency")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "class layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "activity":
        if spec.get("direction", "down") not in ("down", "right"):
            err("$.direction", "unknown direction", "use 'down' (default) or 'right'")
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the activity layout",
                'add "nodes": [{"id": "start", "kind": "initial"}, {"id": "a1", "label": "...", "kind": "action"}, ...]')
        if isinstance(nodes, list) and len(nodes) > 24:
            warn("$.nodes", f"has {len(nodes)} nodes; only the first 24 render", "trim to 24")
        aids = []
        initials = 0
        if isinstance(nodes, list):
            for i, n in enumerate(nodes[:24]):
                if not isinstance(n, dict):
                    continue
                kind = n.get("kind", "action")
                if kind not in graph_model.ACTIVITY_NODE_KINDS:
                    err(f"$.nodes[{i}].kind", f"unknown kind '{kind}'",
                        "use initial, final, action, decision, fork, or join")
                initials += kind == "initial"
                nid = n.get("id")
                if not nid:
                    err(f"$.nodes[{i}].id", "is required", "give every node a stable id so edges can reference it")
                elif str(nid) in aids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                aids.append(str(nid) if nid else f"n{i}")
                if kind == "action" and not n.get("label"):
                    warn(f"$.nodes[{i}].label", "is empty", "actions need a verb-phrase label")
                if kind in ("initial", "final", "fork", "join") and n.get("label"):
                    warn(f"$.nodes[{i}].label", f"is ignored on kind '{kind}'",
                         "only action and decision nodes render labels")
            if initials > 1:
                err("$.nodes", f"has {initials} initial nodes; UML allows one",
                    "keep a single kind:'initial' node")
        edges = spec.get("edges", [])
        if not isinstance(edges, list):
            err("$.edges", "must be a list", 'use [{"from": "start", "to": "a1"}]')
        else:
            if len(edges) > 40:
                warn("$.edges", f"has {len(edges)} edges; only the first 40 render", "trim to 40")
            for i, e in enumerate(edges[:40]):
                if not isinstance(e, dict):
                    err(f"$.edges[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not e.get(end):
                        err(f"$.edges[{i}].{end}", "is required", "reference a node id")
                    elif aids and str(e[end]) not in aids:
                        err(f"$.edges[{i}].{end}", f"references unknown node '{e[end]}'",
                            f"use one of: {', '.join(aids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "activity layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "state":
        states = spec.get("states", [])
        if "states" not in spec:
            err("$.states", "is required for the state layout",
                'add "states": [{"id": "idle", "label": "空闲"}, {"id": "start", "kind": "initial"}, ...] (2-20 items)')
        if isinstance(states, list):
            if len(states) < 2:
                err("$.states", f"needs at least 2 states (got {len(states)})", "add more states or switch layout")
            if len(states) > 20:
                warn("$.states", f"has {len(states)} states; only the first 20 render", "trim to 20")
            for i, s in enumerate(states[:20]):
                if isinstance(s, dict) and len(str(s.get("label", ""))) > 16:
                    warn(f"$.states[{i}].label", "is long; the state box will shrink it",
                         "keep state labels under ~16 chars")
        sids = []
        initials = 0
        if isinstance(states, list):
            for i, s in enumerate(states[:20]):
                if not isinstance(s, dict):
                    continue
                kind = s.get("kind", "state")
                if kind not in graph_model.STATE_NODE_KINDS:
                    err(f"$.states[{i}].kind", f"unknown kind '{kind}'", "use state (default), initial, or final")
                initials += kind == "initial"
                sid = s.get("id")
                if not sid:
                    err(f"$.states[{i}].id", "is required", "give every state a stable id")
                elif str(sid) in sids:
                    err(f"$.states[{i}].id", f"duplicate id '{sid}'", "make state ids unique")
                sids.append(str(sid) if sid else f"s{i}")
                if kind == "state" and not s.get("label"):
                    warn(f"$.states[{i}].label", "is empty", "states need a short name")
                if kind in ("initial", "final") and (s.get("label") or s.get("body")):
                    warn(f"$.states[{i}]", f"label/body are ignored on kind '{kind}'",
                         "only regular states render text")
                if s.get("accent") is not None and s["accent"] not in graph_model.BOX_ACCENTS:
                    warn(f"$.states[{i}].accent", f"unknown accent '{s['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.BOX_ACCENTS))}")
            if initials > 1:
                err("$.states", f"has {initials} initial pseudostates; UML allows one",
                    "keep a single kind:'initial' state")
        transitions = spec.get("transitions", [])
        if not isinstance(transitions, list):
            err("$.transitions", "must be a list", 'use [{"from": "idle", "to": "run", "label": "启动"}]')
        else:
            if len(transitions) > 30:
                warn("$.transitions", f"has {len(transitions)} transitions; only the first 30 render", "trim to 30")
            for i, t in enumerate(transitions[:30]):
                if not isinstance(t, dict):
                    err(f"$.transitions[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not t.get(end):
                        err(f"$.transitions[{i}].{end}", "is required", "reference a state id")
                    elif sids and str(t[end]) not in sids:
                        err(f"$.transitions[{i}].{end}", f"references unknown state '{t[end]}'",
                            f"use one of: {', '.join(sids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "state layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "dfd":
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the dfd layout",
                'add "nodes": [{"id": "c1", "label": "顾客", "kind": "external"}, {"id": "p1", "label": "...", "kind": "process"}, ...]')
        check_items("$.nodes", nodes, 2, 20, "label", 16, required=True)
        dids = []
        if isinstance(nodes, list):
            for i, n in enumerate(nodes[:20]):
                if not isinstance(n, dict):
                    continue
                if n.get("kind", "process") not in graph_model.DFD_NODE_KINDS:
                    err(f"$.nodes[{i}].kind", f"unknown kind '{n.get('kind')}'",
                        "use external (rectangle), process (circle), or store (open rectangle)")
                nid = n.get("id")
                if not nid:
                    err(f"$.nodes[{i}].id", "is required", "give every node a stable id")
                elif str(nid) in dids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                dids.append(str(nid) if nid else f"d{i}")
                if n.get("accent") is not None and n["accent"] not in graph_model.BOX_ACCENTS:
                    warn(f"$.nodes[{i}].accent", f"unknown accent '{n['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.BOX_ACCENTS))}")
        flows = spec.get("flows", [])
        if not isinstance(flows, list):
            err("$.flows", "must be a list", 'use [{"from": "c1", "to": "p1", "label": "订单"}]')
        else:
            if len(flows) > 30:
                warn("$.flows", f"has {len(flows)} flows; only the first 30 render", "trim to 30")
            for i, f in enumerate(flows[:30]):
                if not isinstance(f, dict):
                    err(f"$.flows[{i}]", "must be an object", 'use {"from": "a", "to": "b", "label": "..."}')
                    continue
                for end in ("from", "to"):
                    if not f.get(end):
                        err(f"$.flows[{i}].{end}", "is required", "reference a node id")
                    elif dids and str(f[end]) not in dids:
                        err(f"$.flows[{i}].{end}", f"references unknown node '{f[end]}'",
                            f"use one of: {', '.join(dids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "dfd layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "deployment":
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the deployment layout",
                'add "nodes": [{"id": "srv", "label": "App Server", "kind": "node"}, ...] (2-16 items)')
        check_items("$.nodes", nodes, 2, 16, "label", 20, required=True)
        dids = []
        if isinstance(nodes, list):
            for i, n in enumerate(nodes[:16]):
                if not isinstance(n, dict):
                    continue
                if n.get("kind", "node") not in graph_model.DEPLOYMENT_NODE_KINDS:
                    err(f"$.nodes[{i}].kind", f"unknown kind '{n.get('kind')}'",
                        "use node (default), device, execution, or artifact")
                nid = n.get("id")
                if not nid:
                    err(f"$.nodes[{i}].id", "is required", "give every node a stable id")
                elif str(nid) in dids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                dids.append(str(nid) if nid else f"n{i}")
                if n.get("parent") and str(n["parent"]) not in dids and \
                        not any(isinstance(m, dict) and str(m.get("id")) == str(n["parent"]) for m in nodes[:16]):
                    err(f"$.nodes[{i}].parent", f"references unknown node '{n['parent']}'",
                        "parent must be another node's id")
                if n.get("accent") is not None and n["accent"] not in graph_model.BOX_ACCENTS:
                    warn(f"$.nodes[{i}].accent", f"unknown accent '{n['accent']}' (auto color used)",
                         f"use one of: {', '.join(sorted(graph_model.BOX_ACCENTS))}")
        conns = spec.get("connections", [])
        if not isinstance(conns, list):
            err("$.connections", "must be a list", 'use [{"from": "a", "to": "b", "label": "HTTP"}]')
        else:
            if len(conns) > 20:
                warn("$.connections", f"has {len(conns)} connections; only the first 20 render", "trim to 20")
            for i, c in enumerate(conns[:20]):
                if not isinstance(c, dict):
                    err(f"$.connections[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                if c.get("kind", "path") not in graph_model.DEPLOYMENT_CONN_KINDS:
                    err(f"$.connections[{i}].kind", f"unknown kind '{c.get('kind')}'",
                        "use path (solid, default) or dependency (dashed)")
                for end in ("from", "to"):
                    if not c.get(end):
                        err(f"$.connections[{i}].{end}", "is required", "reference a node id")
                    elif dids and str(c[end]) not in dids:
                        err(f"$.connections[{i}].{end}", f"references unknown node '{c[end]}'",
                            f"use one of: {', '.join(dids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "deployment layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "component":
        comps = spec.get("components", [])
        if "components" not in spec:
            err("$.components", "is required for the component layout",
                'add "components": [{"id": "order", "label": "OrderService"}, ...] (2-12 items)')
        check_items("$.components", comps, 2, 12, "label", 20, required=True)
        cids = []
        if isinstance(comps, list):
            for i, c in enumerate(comps[:12]):
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if not cid:
                    err(f"$.components[{i}].id", "is required", "give every component a stable id")
                elif str(cid) in cids:
                    err(f"$.components[{i}].id", f"duplicate id '{cid}'", "make component ids unique")
                cids.append(str(cid) if cid else f"c{i}")
        itfs = spec.get("interfaces", [])
        if "interfaces" in spec and not isinstance(itfs, list):
            err("$.interfaces", "must be a list",
                'use [{"id": "pay", "label": "IPay", "kind": "provided", "component": "order"}]')
        ifids = []
        if isinstance(itfs, list):
            if len(itfs) > 12:
                warn("$.interfaces", f"has {len(itfs)} interfaces; only the first 12 render", "trim to 12")
            for i, itf in enumerate(itfs[:12]):
                if not isinstance(itf, dict):
                    continue
                if itf.get("kind", "provided") not in graph_model.COMPONENT_IF_KINDS:
                    err(f"$.interfaces[{i}].kind", f"unknown kind '{itf.get('kind')}'",
                        "use provided (ball) or required (socket)")
                if not itf.get("component") or str(itf["component"]) not in cids:
                    err(f"$.interfaces[{i}].component", "must reference a component id",
                        f"use one of: {', '.join(cids)}")
                ifids.append(str(itf.get("id") or f"if{i}"))
        rels = spec.get("relations", [])
        if not isinstance(rels, list):
            err("$.relations", "must be a list", 'use [{"from": "a", "to": "b", "kind": "dependency"}]')
        else:
            known = cids + ifids
            if len(rels) > 16:
                warn("$.relations", f"has {len(rels)} relations; only the first 16 render", "trim to 16")
            for i, r in enumerate(rels[:16]):
                if not isinstance(r, dict):
                    err(f"$.relations[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                if r.get("kind", "dependency") not in graph_model.COMPONENT_REL_KINDS:
                    err(f"$.relations[{i}].kind", f"unknown kind '{r.get('kind')}'",
                        "use dependency, realization, or assembly")
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.relations[{i}].{end}", "is required", "reference a component or interface id")
                    elif known and str(r[end]) not in known:
                        err(f"$.relations[{i}].{end}", f"references unknown id '{r[end]}'",
                            f"use one of: {', '.join(known)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "component layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "package":
        pkgs = spec.get("packages", [])
        if "packages" not in spec:
            err("$.packages", "is required for the package layout",
                'add "packages": [{"id": "ui", "label": "UI"}, {"id": "core", "label": "Core"}, ...] (2-14 items)')
        check_items("$.packages", pkgs, 2, 14, "label", 20, required=True)
        pids = []
        if isinstance(pkgs, list):
            for i, p in enumerate(pkgs[:14]):
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                if not pid:
                    err(f"$.packages[{i}].id", "is required", "give every package a stable id")
                elif str(pid) in pids:
                    err(f"$.packages[{i}].id", f"duplicate id '{pid}'", "make package ids unique")
                pids.append(str(pid) if pid else f"p{i}")
                if p.get("parent") and not any(isinstance(m, dict) and str(m.get("id")) == str(p["parent"])
                                               for m in pkgs[:14]):
                    err(f"$.packages[{i}].parent", f"references unknown package '{p['parent']}'",
                        "parent must be another package's id (one nesting level)")
        rels = spec.get("relations", [])
        if not isinstance(rels, list):
            err("$.relations", "must be a list", 'use [{"from": "ui", "to": "core", "kind": "import"}]')
        else:
            if len(rels) > 16:
                warn("$.relations", f"has {len(rels)} relations; only the first 16 render", "trim to 16")
            for i, r in enumerate(rels[:16]):
                if not isinstance(r, dict):
                    err(f"$.relations[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                if r.get("kind", "dependency") not in graph_model.PACKAGE_REL_KINDS:
                    err(f"$.relations[{i}].kind", f"unknown kind '{r.get('kind')}'",
                        "use import, access, or dependency")
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.relations[{i}].{end}", "is required", "reference a package id")
                    elif pids and str(r[end]) not in pids:
                        err(f"$.relations[{i}].{end}", f"references unknown package '{r[end]}'",
                            f"use one of: {', '.join(pids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "package layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "object":
        objects = spec.get("objects", [])
        if "objects" not in spec:
            err("$.objects", "is required for the object layout",
                'add "objects": [{"id": "o1", "name": "cart1", "class": "Cart"}, ...] (2-12 items)')
        oids = []
        if isinstance(objects, list):
            if len(objects) < 2:
                err("$.objects", f"needs at least 2 objects (got {len(objects)})", "add more objects or switch layout")
            if len(objects) > 12:
                warn("$.objects", f"has {len(objects)} objects; only the first 12 render", "trim to 12")
            for i, o in enumerate(objects[:12]):
                if not isinstance(o, dict):
                    err(f"$.objects[{i}]", "must be an object", 'use {"id": "o1", "name": "...", "class": "..."}')
                    continue
                oid = o.get("id")
                if not oid:
                    err(f"$.objects[{i}].id", "is required", "give every object a stable id")
                elif str(oid) in oids:
                    err(f"$.objects[{i}].id", f"duplicate id '{oid}'", "make object ids unique")
                oids.append(str(oid) if oid else f"o{i}")
                if not o.get("name") and not o.get("class"):
                    warn(f"$.objects[{i}].name", "and class are both empty", "objects read as 'name: Class'")
        else:
            err("$.objects", "must be a list", "provide 2-12 objects")
        links = spec.get("links", [])
        if not isinstance(links, list):
            err("$.links", "must be a list", 'use [{"from": "o1", "to": "o2", "label": "contains"}]')
        else:
            if len(links) > 16:
                warn("$.links", f"has {len(links)} links; only the first 16 render", "trim to 16")
            for i, l in enumerate(links[:16]):
                if not isinstance(l, dict):
                    err(f"$.links[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not l.get(end):
                        err(f"$.links[{i}].{end}", "is required", "reference an object id")
                    elif oids and str(l[end]) not in oids:
                        err(f"$.links[{i}].{end}", f"references unknown object '{l[end]}'",
                            f"use one of: {', '.join(oids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "object layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "composite":
        parts = spec.get("parts", [])
        if "parts" not in spec:
            err("$.parts", "is required for the composite layout",
                'add "parts": [{"id": "p1", "label": "Engine", "type": "Motor"}, ...] (2-10 items)')
        check_items("$.parts", parts, 2, 10, "label", 20, required=True)
        ptids = []
        if isinstance(parts, list):
            for i, p in enumerate(parts[:10]):
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                if not pid:
                    err(f"$.parts[{i}].id", "is required", "give every part a stable id")
                elif str(pid) in ptids:
                    err(f"$.parts[{i}].id", f"duplicate id '{pid}'", "make part ids unique")
                ptids.append(str(pid) if pid else f"pt{i}")
        ports = spec.get("ports", [])
        if "ports" in spec and not isinstance(ports, list):
            err("$.ports", "must be a list", 'use [{"id": "po1", "part": "p1", "side": "right"}]')
        poids = []
        if isinstance(ports, list):
            if len(ports) > 12:
                warn("$.ports", f"has {len(ports)} ports; only the first 12 render", "trim to 12")
            for i, po in enumerate(ports[:12]):
                if not isinstance(po, dict):
                    continue
                if not po.get("part") or str(po["part"]) not in ptids:
                    err(f"$.ports[{i}].part", "must reference a part id", f"use one of: {', '.join(ptids)}")
                if po.get("side", "right") not in ("left", "right", "top", "bottom"):
                    err(f"$.ports[{i}].side", f"unknown side '{po.get('side')}'",
                        "use left, right, top, or bottom")
                poids.append(str(po.get("id") or f"po{i}"))
        conns = spec.get("connectors", [])
        if not isinstance(conns, list):
            err("$.connectors", "must be a list", 'use [{"from": "p1", "to": "p2"}]')
        else:
            known = ptids + poids
            if len(conns) > 16:
                warn("$.connectors", f"has {len(conns)} connectors; only the first 16 render", "trim to 16")
            for i, c in enumerate(conns[:16]):
                if not isinstance(c, dict):
                    err(f"$.connectors[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not c.get(end):
                        err(f"$.connectors[{i}].{end}", "is required", "reference a part or port id")
                    elif known and str(c[end]) not in known:
                        err(f"$.connectors[{i}].{end}", f"references unknown id '{c[end]}'",
                            f"use one of: {', '.join(known)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "composite layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "profile":
        stereos = spec.get("stereotypes", [])
        metas = spec.get("metaclasses", [])
        if "stereotypes" not in spec and "metaclasses" not in spec:
            err("$.stereotypes", "is required for the profile layout",
                'add "stereotypes": [{"id": "s1", "label": "Entity"}], "metaclasses": [{"id": "m1", "label": "Class"}]')
        pfids = []
        for key, cap in (("stereotypes", 8), ("metaclasses", 6)):
            items = spec.get(key, [])
            if not isinstance(items, list):
                err(f"$.{key}", "must be a list", f'provide up to {cap} objects with id + label')
                continue
            if len(items) > cap:
                warn(f"$.{key}", f"has {len(items)} items; only the first {cap} render", f"trim to {cap}")
            for i, it in enumerate(items[:cap]):
                if not isinstance(it, dict):
                    continue
                iid = it.get("id")
                if not iid:
                    err(f"$.{key}[{i}].id", "is required", "give every item a stable id")
                elif str(iid) in pfids:
                    err(f"$.{key}[{i}].id", f"duplicate id '{iid}'", "ids must be unique across the profile")
                pfids.append(str(iid) if iid else f"pf{i}")
        for key, cap in (("extensions", 12), ("relations", 8)):
            rels = spec.get(key, [])
            if not isinstance(rels, list):
                err(f"$.{key}", "must be a list", 'use [{"from": "s1", "to": "m1"}]')
                continue
            if len(rels) > cap:
                warn(f"$.{key}", f"has {len(rels)} items; only the first {cap} render", f"trim to {cap}")
            for i, r in enumerate(rels[:cap]):
                if not isinstance(r, dict):
                    continue
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.{key}[{i}].{end}", "is required", "reference a stereotype or metaclass id")
                    elif pfids and str(r[end]) not in pfids:
                        err(f"$.{key}[{i}].{end}", f"references unknown id '{r[end]}'",
                            f"use one of: {', '.join(pfids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "profile layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "communication":
        objects = spec.get("objects", [])
        if "objects" not in spec:
            err("$.objects", "is required for the communication layout",
                'add "objects": [{"id": "ui", "label": "订单窗口"}, ...] (2-12 items)')
        check_items("$.objects", objects, 2, 12, "label", 18, required=True)
        oids = []
        if isinstance(objects, list):
            for i, o in enumerate(objects[:12]):
                if not isinstance(o, dict):
                    continue
                oid = o.get("id")
                if not oid:
                    err(f"$.objects[{i}].id", "is required", "give every object a stable id")
                elif str(oid) in oids:
                    err(f"$.objects[{i}].id", f"duplicate id '{oid}'", "make object ids unique")
                oids.append(str(oid) if oid else f"o{i}")
        links = spec.get("links", [])
        if not isinstance(links, list):
            err("$.links", "must be a list",
                'use [{"from": "a", "to": "b", "messages": [{"num": "1", "label": "submit()"}]}]')
        else:
            if len(links) > 20:
                warn("$.links", f"has {len(links)} links; only the first 20 render", "trim to 20")
            for i, l in enumerate(links[:20]):
                if not isinstance(l, dict):
                    err(f"$.links[{i}]", "must be an object", 'use {"from": "a", "to": "b", "messages": [...]}')
                    continue
                for end in ("from", "to"):
                    if not l.get(end):
                        err(f"$.links[{i}].{end}", "is required", "reference an object id")
                    elif oids and str(l[end]) not in oids:
                        err(f"$.links[{i}].{end}", f"references unknown object '{l[end]}'",
                            f"use one of: {', '.join(oids)}")
                msgs = l.get("messages", [])
                if "messages" in l and not isinstance(msgs, list):
                    err(f"$.links[{i}].messages", "must be a list",
                        'use [{"num": "1", "label": "submit()", "dir": "forward"}]')
                elif isinstance(msgs, list) and len(msgs) > 6:
                    warn(f"$.links[{i}].messages", f"has {len(msgs)} messages; only the first 6 render",
                         "trim to 6")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "communication layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "timing":
        lifelines = spec.get("lifelines", [])
        if "lifelines" not in spec:
            err("$.lifelines", "is required for the timing layout",
                'add "lifelines": [{"id": "web", "label": "Web", "states": ["空闲", "加载"], '
                '"events": [{"t": 0, "state": "空闲"}, {"t": 3, "state": "加载"}]}] (1-5 items)')
        lids = []
        if not isinstance(lifelines, list):
            err("$.lifelines", "must be a list", "provide 1-5 lifelines")
        else:
            if not lifelines:
                err("$.lifelines", "needs at least 1 lifeline", "add a lifeline or switch layout")
            if len(lifelines) > 5:
                warn("$.lifelines", f"has {len(lifelines)} lifelines; only the first 5 render", "trim to 5")
            for i, l in enumerate(lifelines[:5]):
                if not isinstance(l, dict):
                    continue
                lid = l.get("id")
                if not lid:
                    err(f"$.lifelines[{i}].id", "is required", "give every lifeline a stable id")
                elif str(lid) in lids:
                    err(f"$.lifelines[{i}].id", f"duplicate id '{lid}'", "make lifeline ids unique")
                lids.append(str(lid) if lid else f"l{i}")
                events = l.get("events", [])
                if not isinstance(events, list) or not events:
                    warn(f"$.lifelines[{i}].events", "is empty; a flat line renders",
                         'add [{"t": 0, "state": "..."}, ...] with increasing t')
                states = l.get("states", [])
                if isinstance(states, list) and len(states) > 5:
                    warn(f"$.lifelines[{i}].states", f"has {len(states)} states; only the first 5 render",
                         "trim to 5")
        msgs = spec.get("messages", [])
        if "messages" in spec and not isinstance(msgs, list):
            err("$.messages", "must be a list", 'use [{"from": "web", "to": "db", "t": 2, "label": "SQL"}]')
        if isinstance(msgs, list):
            if len(msgs) > 10:
                warn("$.messages", f"has {len(msgs)} messages; only the first 10 render", "trim to 10")
            for i, m in enumerate(msgs[:10]):
                if not isinstance(m, dict):
                    continue
                for end in ("from", "to"):
                    if not m.get(end):
                        err(f"$.messages[{i}].{end}", "is required", "reference a lifeline id")
                    elif lids and str(m[end]) not in lids:
                        err(f"$.messages[{i}].{end}", f"references unknown lifeline '{m[end]}'",
                            f"use one of: {', '.join(lids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "timing layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "interaction":
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the interaction layout",
                'add "nodes": [{"id": "login", "label": "用户登录", "kind": "interaction"}, ...] (1-16 items)')
        iids = []
        initials = 0
        if not isinstance(nodes, list):
            err("$.nodes", "must be a list", "provide 1-16 nodes")
        else:
            if not nodes:
                err("$.nodes", "needs at least 1 node", "add an interaction frame or switch layout")
            if len(nodes) > 16:
                warn("$.nodes", f"has {len(nodes)} nodes; only the first 16 render", "trim to 16")
            for i, n in enumerate(nodes[:16]):
                if not isinstance(n, dict):
                    continue
                kind = n.get("kind", "interaction")
                if kind not in graph_model.INTERACTION_NODE_KINDS:
                    err(f"$.nodes[{i}].kind", f"unknown kind '{kind}'",
                        "use initial, final, interaction, or decision")
                initials += kind == "initial"
                nid = n.get("id")
                if not nid:
                    err(f"$.nodes[{i}].id", "is required", "give every node a stable id")
                elif str(nid) in iids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                iids.append(str(nid) if nid else f"n{i}")
                if kind == "interaction" and not n.get("label"):
                    warn(f"$.nodes[{i}].label", "is empty", "frames need the referenced diagram name")
                if n.get("ref", "sd") not in ("sd", "ref"):
                    warn(f"$.nodes[{i}].ref", f"unknown ref '{n.get('ref')}' (sd used)", "use sd or ref")
            if initials > 1:
                err("$.nodes", f"has {initials} initial nodes; UML allows one",
                    "keep a single kind:'initial' node")
        edges = spec.get("edges", [])
        if not isinstance(edges, list):
            err("$.edges", "must be a list", 'use [{"from": "login", "to": "order"}]')
        else:
            if len(edges) > 24:
                warn("$.edges", f"has {len(edges)} edges; only the first 24 render", "trim to 24")
            for i, e in enumerate(edges[:24]):
                if not isinstance(e, dict):
                    err(f"$.edges[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not e.get(end):
                        err(f"$.edges[{i}].{end}", "is required", "reference a node id")
                    elif iids and str(e[end]) not in iids:
                        err(f"$.edges[{i}].{end}", f"references unknown node '{e[end]}'",
                            f"use one of: {', '.join(iids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "interaction layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "c4":
        elements = spec.get("elements", [])
        if "elements" not in spec:
            err("$.elements", "is required for the c4 layout",
                'add "elements": [{"id": "u", "label": "用户", "kind": "person"}, ...] (2-16 items)')
        check_items("$.elements", elements, 2, 16, "label", 20, required=True)
        eids = []
        if isinstance(elements, list):
            for i, e in enumerate(elements[:16]):
                if not isinstance(e, dict):
                    continue
                if e.get("kind", "system") not in graph_model.C4_KINDS:
                    err(f"$.elements[{i}].kind", f"unknown kind '{e.get('kind')}'",
                        "use person, system, ext_system, container, database, or queue")
                eid = e.get("id")
                if not eid:
                    err(f"$.elements[{i}].id", "is required", "give every element a stable id")
                elif str(eid) in eids:
                    err(f"$.elements[{i}].id", f"duplicate id '{eid}'", "make element ids unique")
                eids.append(str(eid) if eid else f"e{i}")
        bounds = spec.get("boundaries", [])
        bids = []
        if "boundaries" in spec and not isinstance(bounds, list):
            err("$.boundaries", "must be a list", 'use [{"id": "b1", "label": "内部系统"}]')
        if isinstance(bounds, list):
            if len(bounds) > 4:
                warn("$.boundaries", f"has {len(bounds)} boundaries; only the first 4 render", "trim to 4")
            for i, b in enumerate(bounds[:4]):
                if isinstance(b, dict):
                    if not b.get("id"):
                        err(f"$.boundaries[{i}].id", "is required", "elements reference boundaries by id")
                    bids.append(str(b.get("id") or f"b{i}"))
            if isinstance(elements, list):
                for i, e in enumerate(elements[:16]):
                    if isinstance(e, dict) and e.get("boundary") and str(e["boundary"]) not in bids:
                        err(f"$.elements[{i}].boundary", f"references unknown boundary '{e['boundary']}'",
                            f"use one of: {', '.join(bids)}")
        rels = spec.get("relations", [])
        if not isinstance(rels, list):
            err("$.relations", "must be a list", 'use [{"from": "u", "to": "web", "label": "使用"}]')
        else:
            if len(rels) > 20:
                warn("$.relations", f"has {len(rels)} relations; only the first 20 render", "trim to 20")
            for i, r in enumerate(rels[:20]):
                if not isinstance(r, dict):
                    err(f"$.relations[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                for end in ("from", "to"):
                    if not r.get(end):
                        err(f"$.relations[{i}].{end}", "is required", "reference an element id")
                    elif eids and str(r[end]) not in eids:
                        err(f"$.relations[{i}].{end}", f"references unknown element '{r[end]}'",
                            f"use one of: {', '.join(eids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "c4 layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "gantt":
        sections = spec.get("sections", [])
        if "sections" not in spec:
            err("$.sections", "is required for the gantt layout",
                'add "sections": [{"label": "设计", "tasks": [{"label": "评审", "start": "2026-08-01", '
                '"end": "2026-08-05", "kind": "done"}]}] (1-8 sections)')
        if not isinstance(sections, list):
            err("$.sections", "must be a list", "provide 1-8 sections with tasks")
        else:
            if not sections:
                err("$.sections", "needs at least 1 section", "add a section with tasks")
            if len(sections) > 8:
                warn("$.sections", f"has {len(sections)} sections; only the first 8 render", "trim to 8")
            total = 0
            for i, s in enumerate(sections[:8]):
                if not isinstance(s, dict):
                    continue
                tasks = s.get("tasks", [])
                if not isinstance(tasks, list) or not tasks:
                    warn(f"$.sections[{i}].tasks", "is empty; the section renders as a bare header",
                         "add 1-10 tasks")
                    continue
                if len(tasks) > 10:
                    warn(f"$.sections[{i}].tasks", f"has {len(tasks)} tasks; only the first 10 render",
                         "trim to 10")
                total += len(tasks[:10])
                for j, t in enumerate(tasks[:10]):
                    if not isinstance(t, dict):
                        continue
                    if t.get("kind", "task") not in graph_model.GANTT_TASK_KINDS:
                        err(f"$.sections[{i}].tasks[{j}].kind", f"unknown kind '{t.get('kind')}'",
                            "use task, done, active, crit, or milestone")
                    if t.get("start") is None:
                        err(f"$.sections[{i}].tasks[{j}].start", "is required",
                            'use "YYYY-MM-DD" or a day number, plus "end" or "duration"')
                    if not t.get("label"):
                        warn(f"$.sections[{i}].tasks[{j}].label", "is empty", "add a short task label")
            if isinstance(sections, list) and sections and total > 30:
                warn("$.sections", f"has {total} tasks in total; charts over ~30 get crowded",
                     "split into two diagrams")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "gantt layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "bpmn":
        elements = spec.get("elements", [])
        if "elements" not in spec:
            err("$.elements", "is required for the bpmn layout",
                'add "elements": [{"id": "s", "kind": "start"}, {"id": "t1", "label": "审核", "kind": "task"}, ...]')
        eids = []
        lane_ids = []
        pools = spec.get("pools", [])
        if "pools" in spec and not isinstance(pools, list):
            err("$.pools", "must be a list", 'use [{"label": "系统", "lanes": [{"id": "l1", "label": "客服"}]}]')
        if isinstance(pools, list):
            if len(pools) > 3:
                warn("$.pools", f"has {len(pools)} pools; only the first 3 render", "trim to 3")
            for i, p in enumerate(pools[:3]):
                if not isinstance(p, dict):
                    continue
                for j, ln in enumerate((p.get("lanes") or [])[:4]):
                    if isinstance(ln, dict):
                        lane_ids.append(str(ln.get("id") or f"lane{i}{j}"))
        if not isinstance(elements, list):
            err("$.elements", "must be a list", "provide 2-24 elements")
        else:
            if len(elements) < 2:
                err("$.elements", f"needs at least 2 elements (got {len(elements)})",
                    "add more elements or switch layout")
            if len(elements) > 24:
                warn("$.elements", f"has {len(elements)} elements; only the first 24 render", "trim to 24")
            for i, e in enumerate(elements[:24]):
                if not isinstance(e, dict):
                    continue
                if e.get("kind", "task") not in graph_model.BPMN_ELEMENT_KINDS:
                    err(f"$.elements[{i}].kind", f"unknown kind '{e.get('kind')}'",
                        "use start, intermediate, end, task, gateway, or gateway_parallel")
                eid = e.get("id")
                if not eid:
                    err(f"$.elements[{i}].id", "is required", "give every element a stable id")
                elif str(eid) in eids:
                    err(f"$.elements[{i}].id", f"duplicate id '{eid}'", "make element ids unique")
                eids.append(str(eid) if eid else f"el{i}")
                if e.get("lane") and lane_ids and str(e["lane"]) not in lane_ids:
                    err(f"$.elements[{i}].lane", f"references unknown lane '{e['lane']}'",
                        f"use one of: {', '.join(lane_ids)}")
        flows = spec.get("flows", [])
        if not isinstance(flows, list):
            err("$.flows", "must be a list", 'use [{"from": "s", "to": "t1", "kind": "sequence"}]')
        else:
            if len(flows) > 30:
                warn("$.flows", f"has {len(flows)} flows; only the first 30 render", "trim to 30")
            for i, f in enumerate(flows[:30]):
                if not isinstance(f, dict):
                    err(f"$.flows[{i}]", "must be an object", 'use {"from": "a", "to": "b"}')
                    continue
                if f.get("kind", "sequence") not in graph_model.BPMN_FLOW_KINDS:
                    err(f"$.flows[{i}].kind", f"unknown kind '{f.get('kind')}'", "use sequence or message")
                for end in ("from", "to"):
                    if not f.get(end):
                        err(f"$.flows[{i}].{end}", "is required", "reference an element id")
                    elif eids and str(f[end]) not in eids:
                        err(f"$.flows[{i}].{end}", f"references unknown element '{f[end]}'",
                            f"use one of: {', '.join(eids)}")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "bpmn layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "orgchart":
        nodes = spec.get("nodes", [])
        if "nodes" not in spec:
            err("$.nodes", "is required for the orgchart layout",
                'add "nodes": [{"id": "ceo", "label": "CEO"}, {"id": "cto", "label": "CTO", "parent": "ceo"}]')
        check_items("$.nodes", nodes, 2, 24, "label", 18, required=True)
        oids = []
        if isinstance(nodes, list):
            for i, n in enumerate(nodes[:24]):
                if not isinstance(n, dict):
                    continue
                nid = n.get("id")
                if not nid:
                    err(f"$.nodes[{i}].id", "is required", "give every node a stable id")
                elif str(nid) in oids:
                    err(f"$.nodes[{i}].id", f"duplicate id '{nid}'", "make node ids unique")
                oids.append(str(nid) if nid else f"o{i}")
            for i, n in enumerate(nodes[:24]):
                if isinstance(n, dict) and n.get("parent") and str(n["parent"]) not in oids:
                    err(f"$.nodes[{i}].parent", f"references unknown node '{n['parent']}'",
                        f"use one of: {', '.join(oids)}")
            roots = [n for n in nodes[:24] if isinstance(n, dict) and not n.get("parent")]
            if not roots:
                err("$.nodes", "has no root (every node has a parent)",
                    "leave 'parent' off the top-level node(s)")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "orgchart layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "mindmap":
        root = spec.get("root")
        if not isinstance(root, dict):
            err("$.root", "is required for the mindmap layout",
                'add "root": {"label": "主题", "children": [{"label": "分支", "children": [{"label": "叶子"}]}]}')
        else:
            if not root.get("label"):
                warn("$.root.label", "is empty", "the central topic needs a short label")
            topics = root.get("children", [])
            if not isinstance(topics, list):
                err("$.root.children", "must be a list", 'use [{"label": "分支", "children": [...]}]')
            else:
                if len(topics) < 2:
                    warn("$.root.children", "has fewer than 2 branches; the radial layout looks empty",
                         "add 2-10 branches")
                if len(topics) > 10:
                    warn("$.root.children", f"has {len(topics)} branches; only the first 10 render", "trim to 10")
                for i, t in enumerate(topics[:10]):
                    if not isinstance(t, dict):
                        continue
                    leaves = t.get("children", [])
                    if isinstance(leaves, list) and len(leaves) > 5:
                        warn(f"$.root.children[{i}].children",
                             f"has {len(leaves)} leaves; only the first 5 render", "trim to 5")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "mindmap layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "timeline":
        events = spec.get("events", [])
        if "events" not in spec:
            err("$.events", "is required for the timeline layout",
                'add "events": [{"label": "立项", "time": "1月"}, ...] (2-12 items)')
        check_items("$.events", events, 2, 12, "label", 22, required=True)
        if isinstance(events, list):
            for i, e in enumerate(events[:12]):
                if isinstance(e, dict) and e.get("side") is not None and e["side"] not in ("above", "below"):
                    err(f"$.events[{i}].side", f"unknown side '{e['side']}'",
                        "use above or below (default alternates)")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "timeline layout owns width/height", "omit width/height; use fps/frames for timing")
    elif layout == "fishbone":
        if not spec.get("problem"):
            warn("$.problem", "is empty", "the head box needs the problem statement")
        categories = spec.get("categories", [])
        if "categories" not in spec:
            err("$.categories", "is required for the fishbone layout",
                'add "categories": [{"label": "人员", "causes": ["新人上手慢"]}, ...] (2-6 items)')
        if not isinstance(categories, list):
            err("$.categories", "must be a list", "provide 2-6 categories")
        else:
            if len(categories) < 2:
                err("$.categories", f"needs at least 2 categories (got {len(categories)})",
                    "add more categories or switch layout")
            if len(categories) > 6:
                warn("$.categories", f"has {len(categories)} categories; only the first 6 render", "trim to 6")
            for i, c in enumerate(categories[:6]):
                if not isinstance(c, dict):
                    continue
                if not c.get("label"):
                    warn(f"$.categories[{i}].label", "is empty", "each bone needs a category name")
                causes = c.get("causes", [])
                if isinstance(causes, list) and len(causes) > 5:
                    warn(f"$.categories[{i}].causes", f"has {len(causes)} causes; only the first 5 render",
                         "trim to 5")
        if any(key in canvas for key in ("width", "height")):
            warn("$.canvas", "fishbone layout owns width/height", "omit width/height; use fps/frames for timing")


    output = spec.get("output")
    if isinstance(output, dict) and output.get("icon_file"):
        check_icon_file("$.output.icon_file", output["icon_file"])

    title = spec.get("title", {})
    if isinstance(title, dict):
        highlight = str(title.get("highlight", ""))
        if len(highlight) > 16:
            warn("$.title.highlight", f"is long ({len(highlight)} chars) for the highlight box",
                 "keep it under ~16 chars; move detail into title.subtitle")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


DEFAULT_FORMATS_BROWSER = "gif,mp4,png,excalidraw"
DEFAULT_FORMATS_PILLOW = "gif,png,excalidraw"
ALL_FORMATS = {"gif", "mp4", "png", "excalidraw", "svg", "html", "webp", "avif", "pdf", "lottie", "drawio"}
BROWSER_ONLY_FORMATS = {"mp4", "svg", "html", "webp", "avif", "pdf", "lottie"}


def missing_requested_formats(result, formats):
    return [fmt for fmt in formats if fmt not in result]


def main():
    parser = argparse.ArgumentParser(description="Render a premium hand-drawn animated diagram from a JSON spec.")
    parser.add_argument("--spec", required=True, help="Path to spec JSON.")
    parser.add_argument("--outdir", required=True, help="Output directory.")
    parser.add_argument("--basename", default="animated-diagram", help="Output basename.")
    parser.add_argument("--verify", action="store_true", help="Print frame-diff verification after rendering.")
    parser.add_argument("--check", action="store_true", help="Validate the produced output contracts; exits nonzero on failure.")
    parser.add_argument(
        "--renderer",
        choices=["auto", "browser", "pillow"],
        default="auto",
        help="Diagram renderer: 'browser' replays the layout with rough.js in headless Chromium "
        "(hand-drawn shapes, webfonts, animation presets, MP4); 'pillow' is the classic dependency-light "
        "raster pipeline; 'auto' prefers browser when available.",
    )
    parser.add_argument(
        "--animation",
        choices=list(ANIMATION_CHOICES),
        default=None,
        help="Animation preset (browser renderer): 'flow' eased energy beams (default), "
        "'draw' whiteboard build-up, 'relay' narrative hand-off. Overrides the spec 'animation' field.",
    )
    parser.add_argument(
        "--formats",
        default=None,
        help="Comma-separated outputs. Browser renderer default: gif,mp4,png,excalidraw "
        "(svg, html, webp, avif, pdf, lottie also available). Pillow renderer default: gif,png,excalidraw.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the spec and exit without rendering (exit 2 on errors). "
        "Prints field-level errors/warnings as JSON.",
    )
    parser.add_argument(
        "--icon-engine",
        choices=["auto", "browser", "pillow"],
        default="auto",
        help="Icon renderer for the pillow pipeline: 'browser' uses headless Chromium for crisp animated icons, "
        "'pillow' stays dependency-light, 'auto' prefers browser when available.",
    )
    parser.add_argument(
        "--style",
        choices=[*STYLE_THEMES, "custom"],
        default=None,
        help="Visual style/palette. 'custom' reads spec theme_file or a .diagramforge marker. Overrides the spec 'style' field. Defaults to the spec value or 'slate'.",
    )
    parser.add_argument(
        "--sketch",
        action="store_true",
        default=False,
        help="Hand-drawn rendering (rough strokes, Excalifont display type, icon plates, "
             "'@diagramforge' brand block). Default is formal: clean strokes, sans text, no branding.",
    )
    parser.add_argument(
        "--strict-formats",
        action="store_true",
        help="Fail if any requested format is not produced. Use this for publishing runs.",
    )
    args = parser.parse_args()

    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_dir = spec_path.resolve().parent

    resolve_canvas_preset(spec)
    validation = validate_spec(spec, spec_dir=spec_dir)
    if args.validate_only:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        sys.exit(0 if validation["ok"] else 2)
    for warning in validation["warnings"]:
        print(f"warning: {warning['path']} {warning['message']} -> {warning['fix']}", file=sys.stderr)
    if not validation["ok"]:
        print(json.dumps(validation, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("spec validation failed; fix the errors above and rerun (see references/spec-format.md)")

    resolve_custom_icons(spec, spec_dir)

    style = args.style or spec.get("style", "slate")
    if style == "custom":
        apply_custom_theme(theme_loader.resolve_theme(spec, spec_dir, _THEME_KEYS))
    else:
        apply_style(style)
    set_sketch(args.sketch or spec.get("sketch", False))

    browser_ready = svg_renderer is not None and svg_renderer.is_available()
    renderer = args.renderer
    if renderer == "auto":
        renderer = "browser" if browser_ready else "pillow"
    if renderer == "browser" and not browser_ready:
        print("warning: browser renderer unavailable (playwright/rough.js missing), falling back to pillow", file=sys.stderr)
        renderer = "pillow"

    animation = args.animation or spec.get("animation", "flow")
    if animation not in ANIMATION_CHOICES:
        choices = ", ".join(ANIMATION_CHOICES)
        raise SystemExit(f"unknown animation '{animation}'. choices: {choices}")

    default_formats = DEFAULT_FORMATS_BROWSER if renderer == "browser" else DEFAULT_FORMATS_PILLOW
    formats = tuple(dict.fromkeys(f.strip() for f in (args.formats or default_formats).split(",") if f.strip()))
    unknown_formats = sorted(set(formats) - ALL_FORMATS)
    if unknown_formats:
        raise SystemExit(f"unknown format(s): {', '.join(unknown_formats)}. choices: {', '.join(sorted(ALL_FORMATS))}")
    if args.strict_formats and renderer != "browser":
        unsupported = sorted(set(formats) & BROWSER_ONLY_FORMATS)
        if unsupported:
            raise SystemExit(
                f"requested format(s) require the browser renderer under --strict-formats: "
                f"{', '.join(unsupported)}"
            )

    if renderer == "browser":
        result = write_outputs_browser(spec, Path(args.outdir), args.basename, animation=animation, formats=formats)
    else:
        if animation != "flow":
            print(f"warning: animation preset '{animation}' requires the browser renderer; using classic flow", file=sys.stderr)
        unsupported = [f for f in formats if f in ("mp4", "svg", "html")]
        if unsupported:
            print(f"warning: format(s) {', '.join(unsupported)} require the browser renderer; skipped", file=sys.stderr)
        result = write_outputs(spec, Path(args.outdir), args.basename, icon_engine=args.icon_engine,
                               formats=tuple(f for f in formats if f in {"gif", "png", "excalidraw", "drawio"}))
        result["renderer"] = "pillow"

    result["style"] = style
    if args.verify and "gif" in result:
        result["verification"] = frame_diff_report(result["gif"])
    if args.check:
        result["checks"] = check_outputs(result, spec)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict_formats:
        missing = missing_requested_formats(result, formats)
        if missing:
            print(f"missing requested format(s): {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
    if args.check and not result["checks"]["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
