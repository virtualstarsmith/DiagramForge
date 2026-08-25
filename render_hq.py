#!/usr/bin/env python3
"""render_hq.py — DiagramForge high-quality rendering wrapper.

Forces the browser renderer (rough.js + Chromium) so every output — PNG, MP4,
SVG, HTML — is produced at full hand-drawn quality.  Prevents the silent
Pillow fallback that degrades illustrated icons and line strokes.

Quick start::

    python render_hq.py --spec spec.json --outdir out
    python render_hq.py --spec spec.json --outdir out --preset social
    python render_hq.py --spec spec.json --outdir out --quality ultra --all
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
RENDER_SCRIPT = SCRIPTS_DIR / "render_animated_diagram.py"
DOCTOR_SCRIPT = SCRIPTS_DIR / "doctor.py"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VENDOR_DIR = ASSETS_DIR / "vendor"

QUALITY_SCALE = {"standard": 1, "high": 2, "ultra": 3}

PRESETS = {
    "article": {"width": 1210, "height": 1138},
    "social":   {"width": 1080, "height": 1080},
    "story":    {"width": 1080, "height": 1350},
    "wide":     {"width": 1600, "height": 900},
    "ultra":    {"width": 2420, "height": 2276},
}


# ── Step 1: environment pre-check ──────────────────────────────────────────

def check_environment() -> list[str]:
    """Return a list of problems; empty list = all good."""
    problems = []

    # Python base packages
    try:
        import PIL  # noqa: F401
    except ImportError:
        problems.append("Pillow not installed (pip install -r requirements.txt)")
    try:
        import svg.path  # noqa: F401
    except ImportError:
        problems.append("svg.path not installed (pip install -r requirements.txt)")

    # Playwright
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        problems.append("Playwright not installed (pip install -r requirements-browser.txt)")

    # rough.js vendor asset
    if not (VENDOR_DIR / "rough.js").is_file():
        problems.append(f"rough.js missing at {VENDOR_DIR / 'rough.js'}")

    # ffmpeg (needed for MP4)
    if not shutil.which("ffmpeg"):
        problems.append("ffmpeg not found in PATH (MP4 output will be skipped)")

    # Chromium binary (launch test)
    if not problems:  # only test if deps are present
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch()
                browser.close()
        except Exception as exc:
            problems.append(f"Chromium launch failed: {exc}")

    return problems


# ── Step 2: quality preset injection ───────────────────────────────────────

def apply_preset(spec_path: Path, preset: str | None, width: int | None,
                 height: int | None) -> Path:
    """Write a temporary spec with overridden canvas dimensions.

    Returns the path to the temporary spec file."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    canvas = spec.setdefault("canvas", {})

    if preset and preset in PRESETS:
        canvas["width"] = PRESETS[preset]["width"]
        canvas["height"] = PRESETS[preset]["height"]
    if width:
        canvas["width"] = width
    if height:
        canvas["height"] = height

    # Ensure animation-friendly defaults
    canvas.setdefault("fps", 20)
    canvas.setdefault("frames", 41)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(spec, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return Path(tmp.name)


# ── Step 3: browser full-pipeline render ───────────────────────────────────

def run_render(spec_path: Path, outdir: Path, basename: str,
               formats: list[str]) -> dict:
    """Call DiagramForge's render script with forced browser renderer."""
    cmd = [
        sys.executable, "-X", "utf8", str(RENDER_SCRIPT),
        "--spec", str(spec_path),
        "--outdir", str(outdir),
        "--basename", basename,
        "--renderer", "browser",       # ← force browser, never auto/pillow
        "--icon-engine", "browser",    # ← force browser icons
        "--formats", ",".join(formats),
        "--verify", "--check", "--strict-formats",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"render failed (exit {proc.returncode})")
    return json.loads(proc.stdout)


# ── Step 4: ultra-quality PNG (3× DPI) ─────────────────────────────────────

def capture_hq_png(svg_path: Path, out_path: Path, scale: int) -> tuple[int, int]:
    """Screenshot the rendered SVG in Chromium at *scale*× DPI.

    The browser renderer's built-in PNG is supersampled from 2× then resized
    back to 1× for anti-aliasing — the final resolution is always 1×.  This
    function re-captures the already-serialized SVG at the true target DPI,
    producing a genuine 2× or 3× retina PNG with no downscale.

    Returns the actual pixel dimensions of the captured image."""
    from playwright.sync_api import sync_playwright

    svg_markup = svg_path.read_text(encoding="utf-8")
    wrapper = f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:transparent;}}</style>
</head><body>{svg_markup}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(device_scale_factor=scale)
        page = context.new_page()
        page.set_content(wrapper)
        page.evaluate("() => document.fonts.ready")
        page.wait_for_timeout(500)  # let webfonts settle
        svg_el = page.locator("svg").first
        svg_el.screenshot(path=str(out_path), type="png")
        box = svg_el.bounding_box()
        browser.close()

    actual_w = int(box["width"] * scale) if box else 0
    actual_h = int(box["height"] * scale) if box else 0
    return actual_w, actual_h


# ── Step 5: quality report ─────────────────────────────────────────────────

def print_report(result: dict, outdir: Path, basename: str, quality: str) -> None:
    """Print a human-readable quality summary."""
    scale = QUALITY_SCALE[quality]
    print()
    print("=" * 60)
    print("  RENDER HQ — QUALITY REPORT")
    print("=" * 60)
    renderer = result.get("renderer", "unknown")
    icon_engine = result.get("icon_engine", "browser" if renderer == "browser" else "?")
    print(f"  Renderer:     {renderer}")
    print(f"  Icon engine:  {icon_engine}")
    print(f"  PNG DPI:      {scale}× retina")
    print(f"  Style:        {result.get('style', '?')}")
    print("-" * 60)

    for fmt in ("png", "hq_png", "mp4", "gif", "svg", "html", "excalidraw"):
        key = fmt if fmt in result else None
        path_str = result.get(fmt) or result.get(key or "")
        if not path_str:
            continue
        path = Path(path_str)
        if path.is_file():
            size_kb = path.stat().st_size / 1024
            label = fmt.upper().replace("_", " ")
            print(f"  {label:12s}  {size_kb:>8.0f} KB  {path.name}")

    checks = result.get("checks", {})
    if checks:
        print("-" * 60)
        status = "✓ ALL CHECKS PASSED" if checks.get("ok") else "✗ CHECKS FAILED"
        print(f"  Verification: {status}")

    print("=" * 60)


# ── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DiagramForge high-quality rendering wrapper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python render_hq.py --spec spec.json --outdir out
  python render_hq.py --spec spec.json --outdir out --preset social
  python render_hq.py --spec spec.json --outdir out --quality ultra --all
""",
    )
    parser.add_argument("--spec", required=True, help="path to spec JSON")
    parser.add_argument("--outdir", required=True, help="output directory")
    parser.add_argument("--basename", default="diagram", help="output file basename")
    parser.add_argument("--preset", choices=list(PRESETS),
                        help="canvas size preset (default: use spec dimensions)")
    parser.add_argument("--quality", choices=list(QUALITY_SCALE), default="high",
                        help="PNG DPI scale: standard=1×, high=2× (default), ultra=3×")
    parser.add_argument("--width", type=int, help="override canvas width")
    parser.add_argument("--height", type=int, help="override canvas height")
    parser.add_argument("--all", action="store_true",
                        help="include GIF + Excalidraw in addition to MP4/PNG/SVG/HTML")
    parser.add_argument("--skip-check", action="store_true",
                        help="skip environment pre-check")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: environment pre-check ──────────────────────────────────
    if not args.skip_check:
        print("[1/5] Environment pre-check...")
        problems = check_environment()
        if problems:
            print("  ✗ Environment issues found:")
            for p in problems:
                print(f"    • {p}")
            raise SystemExit("Fix the issues above, or use --skip-check to bypass.")
        print("  ✓ Playwright + Chromium + rough.js + ffmpeg ready")

    # ── Step 2: quality preset ─────────────────────────────────────────
    print("[2/5] Applying quality preset...")
    tmp_spec = apply_preset(spec_path, args.preset, args.width, args.height)
    spec = json.loads(tmp_spec.read_text(encoding="utf-8"))
    canvas = spec.get("canvas", {})
    print(f"  Canvas: {canvas.get('width', '?')}×{canvas.get('height', '?')} "
          f"| Quality: {args.quality} ({QUALITY_SCALE[args.quality]}× DPI)")

    # ── Step 3: browser full-pipeline render ───────────────────────────
    print("[3/5] Rendering via browser (rough.js + Chromium)...")
    formats = ["mp4", "png", "svg", "html"]
    if args.all:
        formats += ["gif", "excalidraw"]
    result = run_render(tmp_spec, outdir, args.basename, formats)

    # Verify renderer didn't silently downgrade
    renderer = result.get("renderer", "unknown")
    if renderer != "browser":
        print(f"  ⚠ WARNING: renderer is '{renderer}', not 'browser'! "
              f"Quality may be degraded.")
    else:
        print(f"  ✓ Renderer: browser (confirmed)")

    # ── Step 4: high-DPI PNG capture ───────────────────────────────────
    scale = QUALITY_SCALE[args.quality]
    if scale > 1:
        print(f"[4/5] High-DPI PNG capture ({scale}× retina)...")
        svg_path = outdir / f"{args.basename}.svg"
        if not svg_path.is_file():
            print(f"  ⚠ SVG not found, keeping browser PNG")
        else:
            hq_path = outdir / f"{args.basename}_hq.png"
            actual_w, actual_h = capture_hq_png(svg_path, hq_path, scale)
            result["hq_png"] = str(hq_path)
            print(f"  ✓ {hq_path.name}  ({actual_w}×{actual_h} px)")
    else:
        print(f"[4/5] Standard 1× PNG (browser renderer output)")

    # ── Step 5: quality report ─────────────────────────────────────────
    print("[5/5] Quality report:")
    print_report(result, outdir, args.basename, args.quality)

    # Cleanup temp spec
    tmp_spec.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
