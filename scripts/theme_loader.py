#!/usr/bin/env python3
"""Custom theme loading for DiagramForge (``style: "custom"``).

A theme JSON maps every required theme key to a ``#rgb``/``#rrggbb`` color.
Resolution order for a spec:

1. ``spec["theme_file"]`` — path resolved relative to the spec file
2. a ``.diagramforge`` marker in the spec's directory or any parent,
   containing ``theme: <slug>`` → ``~/.diagramforge/themes/<slug>.json``
3. otherwise — an explicit error; never a silent fallback to a default style

Validation is load-time and hard-failing (``theme_error:<what>``, exit 2):
exactly the required keys, valid hex colors, and WCAG contrast floors
(ink-on-bg >= 4.5:1, muted-on-bg >= 3:1) with an adjusted-value suggestion.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MARKER_NAME = ".diagramforge"

CONTRAST_RULES = (
    # (foreground key, background key, minimum ratio, label)
    ("white", "bg", 4.5, "ink on paper (WCAG AA normal text)"),
    ("muted", "bg", 3.0, "secondary text on paper"),
)


def _fail(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def _expand_hex(value):
    """#rgb -> #rrggbb; lowercase."""
    value = value.lower()
    if len(value) == 4:
        return "#" + "".join(ch * 2 for ch in value[1:])
    return value


def hex_to_rgb(value):
    value = _expand_hex(value)
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _channel_luminance(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    r, g, b = (_channel_luminance(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg_rgb, bg_rgb):
    l1, l2 = relative_luminance(fg_rgb), relative_luminance(bg_rgb)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def suggest_contrast_fix(fg_rgb, bg_rgb, minimum):
    """Nudge the foreground toward white or black (whichever helps) until the
    ratio passes. Returns the suggested #hex, or None when nothing helps."""
    if contrast_ratio(fg_rgb, bg_rgb) >= minimum:
        return rgb_to_hex(fg_rgb)
    bg_lum = relative_luminance(bg_rgb)
    target = (255, 255, 255) if bg_lum < 0.5 else (0, 0, 0)
    for step in range(1, 21):
        t = step / 20
        candidate = tuple(fg + (tgt - fg) * t for fg, tgt in zip(fg_rgb, target))
        if contrast_ratio(candidate, bg_rgb) >= minimum:
            return rgb_to_hex(candidate)
    return None


def validate_theme(theme, required_keys):
    """Return a list of problems; empty means the theme is usable."""
    problems = []
    if not isinstance(theme, dict):
        return ["theme_error:not_a_mapping — theme JSON must be an object of key -> #hex"]
    keys = set(theme)
    missing = sorted(set(required_keys) - keys)
    extra = sorted(keys - set(required_keys))
    if missing:
        problems.append(f"theme_error:missing_keys — {missing}")
    if extra:
        problems.append(f"theme_error:unknown_keys — {extra} (every key must be one of the required theme keys)")
    for key, value in sorted(theme.items()):
        if not isinstance(value, str) or not HEX_RE.match(value):
            problems.append(f"theme_error:bad_hex — {key}={value!r} is not #rgb/#rrggbb")
    if problems:
        return problems
    for fg_key, bg_key, minimum, label in CONTRAST_RULES:
        fg, bg = hex_to_rgb(theme[fg_key]), hex_to_rgb(theme[bg_key])
        ratio = contrast_ratio(fg, bg)
        if ratio < minimum:
            fix = suggest_contrast_fix(fg, bg, minimum)
            hint = f"; suggested {fg_key}={fix}" if fix else ""
            problems.append(
                f"theme_error:contrast — {label}: {fg_key}={theme[fg_key]} on {bg_key}={theme[bg_key]} "
                f"is {ratio:.2f}:1 (min {minimum}:1){hint}"
            )
    return problems


def load_theme_file(path, required_keys):
    path = Path(path)
    if not path.is_file():
        _fail(f"theme_error:not_found — {path}")
    try:
        theme = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"theme_error:invalid_json — {path}: {exc}")
    problems = validate_theme(theme, required_keys)
    if problems:
        _fail("invalid custom theme:\n  " + "\n  ".join(problems))
    return {key: _expand_hex(value) for key, value in theme.items()}


def find_marker(spec_dir):
    """Nearest .diagramforge marker walking up from the spec's directory."""
    current = Path(spec_dir).resolve()
    for candidate in (current, *current.parents):
        marker = candidate / MARKER_NAME
        if marker.is_file():
            return marker
    return None


def parse_marker(marker_path):
    """A marker is ``key: value`` lines; the only supported key is ``theme``."""
    text = Path(marker_path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^theme\s*:\s*([\w.-]+)\s*$", line)
        if match:
            return match.group(1)
    _fail(
        f"theme_error:marker_malformed — {marker_path} must contain a line "
        "'theme: <slug>'; fix the marker or remove it"
    )


def themes_dir():
    return Path.home() / ".diagramforge" / "themes"


def resolve_theme(spec, spec_dir, required_keys):
    """Resolve the custom theme dict for a spec, or fail explicitly."""
    theme_file = spec.get("theme_file")
    if theme_file:
        return load_theme_file(Path(spec_dir) / theme_file, required_keys)
    marker = find_marker(spec_dir)
    if marker:
        slug = parse_marker(marker)
        return load_theme_file(themes_dir() / f"{slug}.json", required_keys)
    _fail(
        "theme_error:no_source — style \"custom\" needs spec[\"theme_file\"] or a "
        f".diagramforge marker with 'theme: <slug>' resolving to ~/.diagramforge/themes/<slug>.json"
    )


def finish_mode(theme):
    """Light/dark finish derived from the paper color's luminance."""
    return "dark" if relative_luminance(hex_to_rgb(theme["bg"])) < 0.35 else "light"
