#!/usr/bin/env python3
"""Build the example gallery: every spec in assets/examples/ rendered as a
static PNG in two styles (report + slate), browsable in gallery/index.html,
with a sha256 manifest.

Requires Chromium (the browser renderer). ``--verify`` re-renders everything
and fails when a digest drifts from the manifest — the freshness gate for
"screenshots no longer match the shipped examples".

Usage:
    python -X utf8 scripts/build_gallery.py            # build
    python -X utf8 scripts/build_gallery.py --verify   # freshness gate
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"
GALLERY = ROOT / "gallery"
STYLES = ("report", "slate")

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _load_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(_SCRIPTS_DIR) / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_all(outdir=GALLERY, only=None):
    """Render every example (or the stems in *only*) in every gallery style.

    Returns {example_stem: {"layout": ..., "styles": {style: sha256}}}.
    """
    svg_renderer = _load_module("svg_renderer")
    if not svg_renderer.is_available():
        print("gallery_error:no_browser — the gallery needs Chromium "
              "(python -m playwright install chromium)", file=sys.stderr)
        sys.exit(2)
    renderer = _load_module("render_animated_diagram")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for spec_path in sorted(EXAMPLES.glob("*.json")):
        if only and spec_path.stem not in only:
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        entry = {}
        for style in STYLES:
            renderer.apply_style(style)
            result = renderer.write_outputs_browser(spec, outdir, f"{spec_path.stem}.{style}", formats=("png",))
            entry[style] = _sha256(result["png"])
        manifest[spec_path.stem] = {"layout": spec.get("layout"), "styles": entry}
        print(f"rendered {spec_path.stem}", file=sys.stderr)
    return manifest


def build_index(manifest, examples_dir=EXAMPLES):
    """A static, self-contained-enough gallery page (relative image refs)."""
    cards = []
    for stem in sorted(manifest):
        info = manifest[stem]
        cards.append(f"""
      <figure class="card" data-layout="{info['layout']}">
        <img class="v-report" src="{stem}.report.png" alt="{stem} (report)" loading="lazy">
        <img class="v-slate" src="{stem}.slate.png" alt="{stem} (slate)" loading="lazy" hidden>
        <figcaption><code>{stem}</code> · {info['layout']}</figcaption>
      </figure>""")
    return f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>DiagramForge example gallery</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8fafc; color: #0f172a; }}
  header {{ display: flex; align-items: baseline; gap: 1rem; }}
  .toggle button {{ margin-right: .5rem; padding: .3rem .9rem; border: 1px solid #cbd5e1;
    background: #fff; border-radius: 6px; cursor: pointer; }}
  .toggle button[aria-pressed="true"] {{ background: #0f172a; color: #fff; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 1.25rem; margin-top: 1.5rem; }}
  .card {{ margin: 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem; }}
  .card img {{ width: 100%; height: auto; display: block; }}
  figcaption {{ margin-top: .5rem; color: #64748b; font-size: .85rem; }}
</style>
</head>
<body>
  <header>
    <h1>DiagramForge examples</h1>
    <div class="toggle" role="group" aria-label="style">
      <button id="btn-report" aria-pressed="true">report</button>
      <button id="btn-slate" aria-pressed="false">slate</button>
    </div>
  </header>
  <main class="grid">{''.join(cards)}
  </main>
  <script>
  (() => {{
    const set = (style) => {{
      document.querySelectorAll(".v-report").forEach((el) => (el.hidden = style !== "report"));
      document.querySelectorAll(".v-slate").forEach((el) => (el.hidden = style !== "slate"));
      document.getElementById("btn-report").setAttribute("aria-pressed", style === "report");
      document.getElementById("btn-slate").setAttribute("aria-pressed", style === "slate");
    }};
    document.getElementById("btn-report").addEventListener("click", () => set("report"));
    document.getElementById("btn-slate").addEventListener("click", () => set("slate"));
  }})();
  </script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true", help="re-render and compare digests with the manifest")
    parser.add_argument("--outdir", default=str(GALLERY))
    parser.add_argument("--only", default=None, help="comma-separated example stems to render (debug/tests)")
    args = parser.parse_args(argv)

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    manifest_path = Path(args.outdir) / "manifest.json"
    if args.verify and not manifest_path.is_file():
        print("gallery_error:no_manifest — build the gallery first", file=sys.stderr)
        return 2
    manifest = render_all(Path(args.outdir), only=only)

    if args.verify:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        drift = []
        for stem in sorted(set(old) | set(manifest)):
            if stem not in old:
                drift.append(f"{stem}: new example not in manifest")
                continue
            if stem not in manifest:
                drift.append(f"{stem}: in manifest but example removed")
                continue
            for style in STYLES:
                if old[stem]["styles"].get(style) != manifest[stem]["styles"].get(style):
                    drift.append(f"{stem}.{style}: digest drifted")
        if drift:
            print(json.dumps({"ok": False, "drift": drift}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"ok": True, "examples": len(manifest)}, ensure_ascii=False))
        return 0

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (Path(args.outdir) / "index.html").write_text(build_index(manifest), encoding="utf-8")
    print(json.dumps({"ok": True, "examples": len(manifest), "outdir": args.outdir}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
