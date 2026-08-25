#!/usr/bin/env python3
"""Onboard a brand theme from a website URL.

Renders the page in headless Chromium, samples computed styles (body, h1,
code, links, buttons, muted text) and :root CSS custom properties, falls back
to a screenshot color histogram for the accent, maps everything onto the
DiagramForge theme keys, checks WCAG contrast floors, and writes
``~/.diagramforge/themes/<slug>.json``.

Ends with a fidelity receipt: which URLs were sampled, where each role's value
came from, detected fonts (informational — the renderer uses its bundled
fonts), and every automatic adjustment made. Nothing is silently replaced.

Usage:
    python -X utf8 scripts/onboard_brand.py --url https://example.com --slug acme
    python -X utf8 scripts/onboard_brand.py --url file:///C:/brand/page.html --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import theme_loader  # noqa: E402

# Canonical semantic hues (same family as the bundled styles). The accent and
# neutrals come from the brand; these stay fixed so status semantics survive.
SEMANTIC = {
    "green": "#10b981",
    "amber": "#f59e0b",
    "pink": "#ef4444",
    "cyan": "#0891b2",
    "purple": "#6366f1",
}

_SAMPLE_JS = r"""
() => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {color: cs.color, bg: cs.backgroundColor, font: cs.fontFamily};
  };
  const vars = {};
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }  // cross-origin
    for (const rule of rules) {
      if ((rule.selectorText || "").split(",")[0].trim() === ":root" && rule.style) {
        for (const prop of rule.style) {
          if (prop.startsWith("--")) vars[prop] = rule.style.getPropertyValue(prop).trim();
        }
      }
    }
  }
  return {
    url: location.href,
    title: document.title,
    body: pick("body"),
    h1: pick("h1"),
    code: pick("code, pre"),
    link: pick("a"),
    button: pick("button, .button, .btn, [class*='btn'], [role='button']"),
    muted: pick("small, .text-muted, .muted, .caption, figcaption, footer"),
    vars,
  };
}
"""

_RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+)\s*)?\)")

ACCENT_VAR_NAMES = ("--accent", "--primary", "--brand", "--color-accent", "--color-primary", "--theme", "--link")


def parse_rgb(value):
    """'rgb(r, g, b)' / '#rrggbb' -> (r, g, b), or None for transparent/none."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("#"):
        try:
            return theme_loader.hex_to_rgb(value)
        except Exception:
            return None
    match = _RGB_RE.match(value)
    if not match:
        return None
    if match.group(4) is not None and float(match.group(4)) < 0.05:
        return None  # effectively transparent
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _mix(rgb_a, rgb_b, t):
    """t=0 -> rgb_b, t=1 -> rgb_a."""
    return tuple(a * t + b * (1 - t) for a, b in zip(rgb_a, rgb_b))


def _hex(rgb):
    return theme_loader.rgb_to_hex(rgb)


def _is_neutral(rgb, tolerance=28):
    return max(rgb) - min(rgb) <= tolerance


def _histogram_accent(png_bytes):
    """Top saturated, non-extreme color from a screenshot."""
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    img.thumbnail((240, 240))
    colors = img.getcolors(maxcolors=240 * 240) or []
    best, best_count = None, 0
    for count, rgb in colors:
        if _is_neutral(rgb) or max(rgb) > 245 or min(rgb) < 10:
            continue
        if count > best_count:
            best, best_count = rgb, count
    return best


def _pick_accent(sample, vars_colors, screenshot_rgb):
    """Priority: button bg -> link color -> known CSS var -> histogram."""
    button_bg = parse_rgb((sample.get("button") or {}).get("bg"))
    if button_bg and not _is_neutral(button_bg):
        return button_bg, "button background"
    link = parse_rgb((sample.get("link") or {}).get("color"))
    if link and not _is_neutral(link):
        return link, "link color"
    for name in ACCENT_VAR_NAMES:
        if name in vars_colors:
            rgb = parse_rgb(vars_colors[name])
            if rgb and not _is_neutral(rgb):
                return rgb, f"CSS variable {name}"
    if screenshot_rgb:
        return screenshot_rgb, "screenshot color histogram"
    return (59, 130, 246), "fallback (DiagramForge report blue); nothing brand-colored detected"


def build_theme(bg_rgb, ink_rgb, muted_rgb, accent_rgb):
    """Map the four brand anchors onto the full theme key set."""
    dark = theme_loader.relative_luminance(bg_rgb) < 0.35
    lift = (240, 248, 255) if dark else ink_rgb  # dark themes lift fills toward light

    def tint(color, t):
        return _hex(_mix(color, bg_rgb, t))

    accent = _hex(accent_rgb)
    green, amber, pink, cyan, purple = (SEMANTIC[k] for k in ("green", "amber", "pink", "cyan", "purple"))

    if dark:
        bands = [_hex(_mix(lift, bg_rgb, t)) for t in (0.08, 0.14, 0.20, 0.26)]
        lane_column, lane_border = bands[1], _hex(_mix(lift, bg_rgb, 0.34))
        core_fill = bands[0]
    else:
        bands = [_hex(_mix(ink_rgb, bg_rgb, t)) for t in (0.0, 0.04, 0.08, 0.12)]
        lane_column, lane_border = bands[2], _hex(_mix(ink_rgb, bg_rgb, 0.22))
        core_fill = _hex(bg_rgb)

    return {
        "bg": _hex(bg_rgb),
        "white": _hex(ink_rgb),
        "muted": _hex(muted_rgb),
        "frame": _hex(_mix(ink_rgb, bg_rgb, 0.25 if dark else 0.18)),
        "core_fill": core_fill,
        "core_stroke": accent,
        "green": green, "green_fill": tint(theme_loader.hex_to_rgb(green), 0.12),
        "purple": purple, "purple_fill": tint(theme_loader.hex_to_rgb(purple), 0.12),
        "cyan": cyan, "blue_fill": tint(accent_rgb, 0.10),
        "highlight": tint(accent_rgb, 0.18),
        "amber": amber, "pink": pink,
        "archive_fill": tint(theme_loader.hex_to_rgb(purple), 0.12),
        "source_fill": tint(theme_loader.hex_to_rgb(green), 0.12),
        "pack_fill": tint(theme_loader.hex_to_rgb(green), 0.12),
        "amber_fill": tint(theme_loader.hex_to_rgb(amber), 0.15),
        "sand_fill": tint(theme_loader.hex_to_rgb(amber), 0.06),
        "icon_fill": core_fill,
        "decision_fill": _hex(_mix(ink_rgb, bg_rgb, 0.05)),
        "src_card_fill": core_fill,
        "layer_card_fill": tint(theme_loader.hex_to_rgb(purple), 0.12),
        "pack_card_fill": core_fill,
        "lane_band_0": bands[0],
        "lane_band_1": bands[1],
        "lane_band_2": bands[2],
        "lane_band_3": bands[3],
        "lane_column": lane_column,
        "lane_border": lane_border,
    }


def onboard(url, slug=None, out=None, dry_run=False, timeout_ms=15000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("onboard_error:no_browser — playwright is not installed; "
              "run: python -m pip install -r requirements-browser.txt && python -m playwright install chromium",
              file=sys.stderr)
        sys.exit(2)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
        except Exception:
            pass  # sample whatever is rendered
        sample = page.evaluate(_SAMPLE_JS)
        screenshot = page.screenshot(type="png")
        browser.close()

    vars_colors = sample.get("vars", {})
    histogram_rgb = _histogram_accent(screenshot)

    bg_rgb = parse_rgb((sample.get("body") or {}).get("bg")) or (255, 255, 255)
    ink_rgb = parse_rgb((sample.get("body") or {}).get("color")) or (30, 41, 59)
    muted_rgb = parse_rgb((sample.get("muted") or {}).get("color")) or _mix(ink_rgb, bg_rgb, 0.45)
    accent_rgb, accent_source = _pick_accent(sample, vars_colors, histogram_rgb)

    theme = build_theme(bg_rgb, ink_rgb, muted_rgb, accent_rgb)

    # Contrast floors are enforced, with adjustments reported — never silent.
    adjustments = []
    for fg_key, bg_key, minimum, label in theme_loader.CONTRAST_RULES:
        fg, bg = theme_loader.hex_to_rgb(theme[fg_key]), theme_loader.hex_to_rgb(theme[bg_key])
        ratio = theme_loader.contrast_ratio(fg, bg)
        if ratio < minimum:
            fix = theme_loader.suggest_contrast_fix(fg, bg, minimum)
            if fix:
                adjustments.append(
                    {"key": fg_key, "from": theme[fg_key], "to": fix,
                     "reason": f"{label} was {ratio:.2f}:1 (min {minimum}:1)"}
                )
                theme[fg_key] = fix

    problems = theme_loader.validate_theme(theme, _required_keys())
    if problems:
        print("onboard_error:theme_invalid —\n  " + "\n  ".join(problems), file=sys.stderr)
        sys.exit(2)

    if slug is None:
        host = re.sub(r"[^a-z0-9]+", "-", (sample.get("url") or "site").lower()).strip("-")
        slug = host or "brand"
    theme_path = Path(out) if out else theme_loader.themes_dir() / f"{slug}.json"

    receipt = {
        "ok": True,
        "slug": slug,
        "dry_run": bool(dry_run),
        "theme_path": None if dry_run else str(theme_path),
        "sampled_urls": [sample.get("url")],
        "roles": {
            "bg": {"value": theme["bg"], "source": "body background-color"},
            "white": {"value": theme["white"], "source": "body text color"},
            "muted": {"value": theme["muted"], "source": "muted/caption text color or derived blend"},
            "core_stroke": {"value": theme["core_stroke"], "source": accent_source},
        },
        "fonts": {
            "title": (sample.get("h1") or {}).get("font"),
            "body": (sample.get("body") or {}).get("font"),
            "mono": (sample.get("code") or {}).get("font"),
            "note": "informational only — the renderer keeps its bundled fonts in this version",
        },
        "contrast": {
            f"{fg}_on_{bg}": round(theme_loader.contrast_ratio(
                theme_loader.hex_to_rgb(theme[fg]), theme_loader.hex_to_rgb(theme[bg])), 2)
            for fg, bg, _min, _label in theme_loader.CONTRAST_RULES
        },
        "adjustments": adjustments,
    }

    if not dry_run:
        theme_path.parent.mkdir(parents=True, exist_ok=True)
        theme_path.write_text(json.dumps(theme, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def _required_keys():
    """The renderer's _THEME_KEYS, imported lazily so this script stays light."""
    spec_dir = _SCRIPTS_DIR
    import importlib.util

    spec = importlib.util.spec_from_file_location("render_animated_diagram", Path(spec_dir) / "render_animated_diagram.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._THEME_KEYS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="page to sample (https://… or file:///…)")
    parser.add_argument("--slug", default=None, help="theme name (default: derived from the URL)")
    parser.add_argument("--out", default=None, help="theme JSON path (default: ~/.diagramforge/themes/<slug>.json)")
    parser.add_argument("--dry-run", action="store_true", help="print the receipt without writing the theme")
    parser.add_argument("--timeout-ms", type=int, default=15000)
    args = parser.parse_args(argv)
    return onboard(args.url, slug=args.slug, out=args.out, dry_run=args.dry_run, timeout_ms=args.timeout_ms)


if __name__ == "__main__":
    sys.exit(main())
