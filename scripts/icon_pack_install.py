#!/usr/bin/env python3
"""One-click installer for official cloud/vendor icon packs.

Bridges the gap between "here is a table of download pages"
(references/vendor-icons.md) and a working `assets/icons/vendor/<pack>/`:
it downloads the official set you name, flattens and kebab-case-normalizes
every SVG, and drops a LICENSE note in the pack folder.

Licensing is honored the way the docs promise: the script fetches from the
official sources on YOUR machine — DiagramForge never bundles or
redistributes these assets, and rendering never requires network access.

Usage:
    python -X utf8 scripts/icon_pack_install.py --list
    python -X utf8 scripts/icon_pack_install.py --provider k8s
    python -X utf8 scripts/icon_pack_install.py --provider aws --dry-run
    python -X utf8 scripts/icon_pack_install.py --url path/to/icons.zip --pack myset
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

REPO = Path(SCRIPTS_DIR).parent
VENDOR_DIR = REPO / "assets" / "icons" / "vendor"

# Direct official sources (zip archives of SVGs). Official URLs move; when one
# 404s the error names the human page from vendor-icons.md so the file can be
# downloaded manually with --url.
PROVIDERS = {
    "aws": {
        "url": "https://d1.awsstatic.com/webteam/architecture-icons-q32025/Aws_Architecture_Icons.zip",
        "page": "https://aws.amazon.com/architecture/icons/",
        "license": "Free for use in architecture diagrams; no redistribution (AWS Trademark Guidelines)",
    },
    "azure": {
        "url": "https://download.microsoft.com/download/5/8/9/58957f92-2c8f-4e1a-9a1a-6b3d3c9a0a1e/Azure_Public_Service_Icons.zip",
        "page": "https://learn.microsoft.com/azure/architecture/icons/",
        "license": "Use in diagrams allowed; see Microsoft terms",
    },
    "gcp": {
        "url": "https://cloud.google.com/icons",
        "page": "https://cloud.google.com/icons",
        "license": "Use in diagrams allowed; see Google terms",
    },
    "k8s": {
        "url": "https://github.com/kubernetes/community/archive/refs/heads/master.zip",
        "page": "https://github.com/kubernetes/community/tree/master/icons",
        "license": "Apache-2.0 / CC-BY per file — keep the badge labels",
        "strip_prefix": "community-master/icons/",
    },
}

# Simple Icons: one SVG per brand name from the CDN (CC0-1.0). Failures for
# individual names are reported, never fatal.
SIMPLE_NAMES = [
    "kubernetes", "docker", "nginx", "postgresql", "redis", "rabbitmq",
    "elasticsearch", "mongodb", "mysql", "apachekafka", "grafana",
    "prometheus", "terraform", "ansible", "jenkins", "githubactions",
    "googlecloud", "cloudflare", "vercel", "istio",
]


def kebab(name):
    """`Amazon-EC2_light-bg.svg` -> `amazon-ec2-light-bg.svg` (icon key form)."""
    stem = Path(name).stem
    stem = re.sub(r"[\s_]+", "-", stem.strip())
    stem = re.sub(r"-+", "-", stem)
    return stem.lower()


_VARIANT_RE = re.compile(r"[-_](light|dark)([-_.]?bg)?$", re.IGNORECASE)


def _icon_key(filename):
    """Icon key for dedupe: light/dark plate variants of one icon collapse to
    the same key (`EC2_light-bg`, `EC2_dark-bg`, `EC2_Light` -> `ec2`)."""
    stem = Path(filename).stem
    return kebab(_VARIANT_RE.sub("", stem) + ".svg")


def _bg_priority(name):
    """Prefer background-free variants over dark-bg plates when both exist."""
    lowered = name.lower()
    if "dark-bg" in lowered:
        return 2
    if "light-bg" in lowered:
        return 1
    return 0


def collect_svgs(zip_bytes, strip_prefix=None):
    """zip bytes -> {kebab_name: svg_bytes}, deduped by variant priority."""
    best = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            filename = info.filename
            if not filename.lower().endswith(".svg"):
                continue
            if strip_prefix and filename.startswith(strip_prefix):
                filename = filename[len(strip_prefix):]
            key = _icon_key(filename)
            if not key or key.startswith("."):
                continue
            priority = _bg_priority(filename)
            if key not in best or priority < best[key][0]:
                best[key] = (priority, zf.read(info))
    return {key: payload for key, (_p, payload) in best.items()}


def install_pack(pack, svg_map, license_note, source):
    out = VENDOR_DIR / pack
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for name, payload in sorted(svg_map.items()):
        (out / f"{name}.svg").write_bytes(payload)
        count += 1
    (out / "LICENSE.txt").write_text(
        f"Downloaded {source}\nLicense: {license_note}\nKept locally for your records; not redistributed by DiagramForge.\n",
        encoding="utf-8",
    )
    return count


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "diagramforge-icon-pack-install"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def installed_packs():
    if not VENDOR_DIR.is_dir():
        return {}
    packs = {}
    for folder in sorted(VENDOR_DIR.iterdir()):
        if folder.is_dir():
            packs[folder.name] = len(list(folder.glob("*.svg")))
    return packs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=sorted(PROVIDERS) + ["simple"], help="Official pack to install.")
    parser.add_argument("--url", default=None, help="Manual zip URL (or file:// path) for a pack not in the catalog.")
    parser.add_argument("--pack", default=None, help="Pack folder name (required with --url, optional override otherwise).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be installed without writing.")
    parser.add_argument("--list", action="store_true", help="List providers and what is already installed.")
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps({"providers": sorted(PROVIDERS) + ["simple"], "installed": installed_packs()}, indent=2))
        return 0

    try:
        if args.url:
            if not args.pack:
                raise SystemExit("--pack is required with --url")
            pack = args.pack
            license_note = "Unknown — check the source's terms before publishing"
            source = args.url
            blob = fetch(args.url)
            svg_map = collect_svgs(blob)
        elif args.provider == "simple":
            pack = "simple"
            license_note = "CC0-1.0 (Simple Icons)"
            source = "https://simpleicons.org"
            svg_map = {}
            for name in SIMPLE_NAMES:
                try:
                    svg_map[kebab(name)] = fetch(f"https://cdn.simpleicons.org/{name}")
                except Exception as exc:
                    print(f"skip {name}: {exc}", file=sys.stderr)
        elif args.provider:
            entry = PROVIDERS[args.provider]
            pack = args.pack or args.provider
            license_note = entry["license"]
            source = entry["page"]
            blob = fetch(entry["url"])
            svg_map = collect_svgs(blob, strip_prefix=entry.get("strip_prefix"))
        else:
            parser.error("choose --provider, --provider simple, or --url with --pack (see --list)")
    except urllib.error.URLError as exc:
        print(
            f"network_error:{args.provider or args.url} — {exc}\n"
            f"Download the archive manually from the page in references/vendor-icons.md "
            f"and retry with --url <file> --pack <name>.",
            file=sys.stderr,
        )
        return 2

    if not svg_map:
        print(
            f"pack_error:{pack} — no SVGs found in the archive; the official URL may have moved. "
            f"Download manually (see references/vendor-icons.md) and retry with --url --pack.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "pack": pack, "icons": len(svg_map)}, ensure_ascii=False))
        return 0

    count = install_pack(pack, svg_map, license_note, source)
    print(json.dumps({
        "ok": True,
        "pack": pack,
        "icons": count,
        "dir": str(VENDOR_DIR / pack),
        "license": license_note,
        "note": "specs resolve vendor/<pack>/<name>.svg automatically; keep LICENSE.txt for your records",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
