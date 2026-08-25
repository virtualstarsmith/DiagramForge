#!/usr/bin/env python3
"""Optional online icon search/fetch for DiagramForge vendor packs.

Searches the Iconify API (https://iconify.design) and downloads chosen SVGs
into ``assets/icons/vendor/<pack>/`` so specs can reference them by bare name
(e.g. ``{"icon": "s3"}``). Vendor files take priority over the bundled Tabler
set at render time.

This tool is strictly optional: DiagramForge renders fully offline without it.
Downloaded icons keep their original licenses -- check the license info printed
by ``search`` before publishing diagrams commercially.

Usage:
    python -X utf8 scripts/icon_search.py search "aws s3"
    python -X utf8 scripts/icon_search.py fetch simple-icons:amazonaws --name aws
    python -X utf8 scripts/icon_search.py fetch logos:kubernetes --pack k8s --name kubernetes
    python -X utf8 scripts/icon_search.py list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_ICON_DIR = ROOT / "assets" / "icons" / "vendor"

ICONIFY_SEARCH = "https://api.iconify.design/search"
ICONIFY_SVG = "https://api.iconify.design/{prefix}/{name}.svg"
USER_AGENT = "diagramforge-icon-search/1.0 (+https://github.com/lazypay/DiagramForge)"
TIMEOUT = 20


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def _safe_name(value):
    name = re.sub(r"[^a-z0-9-]+", "-", str(value).strip().lower()).strip("-")
    if not name:
        raise SystemExit("icon name must contain at least one letter or digit")
    return name


def cmd_search(args):
    query = urllib.parse.urlencode({"query": args.query, "limit": args.limit})
    data = _get_json(f"{ICONIFY_SEARCH}?{query}")
    icons = data.get("icons", [])
    if not icons:
        print(json.dumps({"ok": False, "message": f"no icons found for '{args.query}'"}, ensure_ascii=False))
        return 1
    results = []
    for entry in icons:
        prefix, _, name = entry.partition(":")
        collection = (data.get("collections") or {}).get(prefix) or {}
        results.append({
            "id": entry,
            "collection": collection.get("name", prefix),
            "license": (collection.get("license") or {}).get("title", "unknown"),
            "fetch": f"python -X utf8 scripts/icon_search.py fetch {entry}",
        })
    print(json.dumps({"ok": True, "count": len(results), "results": results}, ensure_ascii=False, indent=2))
    print("\nCheck each collection's license before publishing diagrams commercially.", file=sys.stderr)
    return 0


def cmd_fetch(args):
    prefix, sep, icon_name = args.icon_id.partition(":")
    if not sep or not prefix or not icon_name:
        raise SystemExit("icon id must look like '<prefix>:<name>', e.g. simple-icons:amazonaws")
    pack = _safe_name(args.pack or prefix)
    local_name = _safe_name(args.name or icon_name)
    url = ICONIFY_SVG.format(prefix=urllib.parse.quote(prefix), name=urllib.parse.quote(icon_name))
    svg = _get_text(url)
    if "<svg" not in svg:
        raise SystemExit(f"unexpected response for {args.icon_id}: not an SVG")
    pack_dir = VENDOR_ICON_DIR / pack
    pack_dir.mkdir(parents=True, exist_ok=True)
    target = pack_dir / f"{local_name}.svg"
    target.write_text(svg, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "file": str(target.relative_to(ROOT)).replace("\\", "/"),
        "use": f'{{"icon": "{local_name}"}}',
        "note": "vendor icons are git-ignored; keep the source license with your project",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_args):
    packs = {}
    if VENDOR_ICON_DIR.is_dir():
        for pack in sorted(VENDOR_ICON_DIR.iterdir()):
            if pack.is_dir():
                packs[pack.name] = sorted(p.stem for p in pack.glob("*.svg"))
    print(json.dumps({"ok": True, "vendor_dir": str(VENDOR_ICON_DIR), "packs": packs},
                     ensure_ascii=False, indent=2))
    return 0


def main():  # pragma: no cover (CLI entry; tested via subprocess)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search Iconify for icons.")
    p_search.add_argument("query", help="Search text, e.g. 'aws s3' or 'kubernetes'.")
    p_search.add_argument("--limit", type=int, default=10, help="Max results (default 10).")
    p_search.set_defaults(func=cmd_search)

    p_fetch = sub.add_parser("fetch", help="Download an icon SVG into a vendor pack.")
    p_fetch.add_argument("icon_id", help="Iconify id '<prefix>:<name>', e.g. logos:kubernetes.")
    p_fetch.add_argument("--pack", default=None, help="Vendor pack folder (default: the icon's prefix).")
    p_fetch.add_argument("--name", default=None, help="Local icon name used in specs (default: the icon's name).")
    p_fetch.set_defaults(func=cmd_fetch)

    p_list = sub.add_parser("list", help="List installed vendor packs and icons.")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    main()
