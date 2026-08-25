#!/usr/bin/env python3
"""Synchronize the DiagramForge version across pyproject.toml and every
host plugin manifest (.claude-plugin, .codex-plugin, .agents marketplace).

Usage:
    python -X utf8 scripts/bump_version.py 2.2.0     # write everywhere
    python -X utf8 scripts/bump_version.py --check   # CI gate: fail on drift
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
MANIFESTS = (
    ROOT / ".claude-plugin" / "plugin.json",
    ROOT / ".claude-plugin" / "marketplace.json",
    ROOT / ".codex-plugin" / "plugin.json",
    ROOT / ".agents" / "plugins" / "marketplace.json",
)

VERSION_RE = re.compile(r'^version = "([^"]+)"', re.MULTILINE)


def pyproject_version():
    match = VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("no version field in pyproject.toml")
    return match.group(1)


def manifest_versions():
    """path -> list of versions found (plugin manifests nest under plugins[])."""
    found = {}
    for path in MANIFESTS:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions = []
        if "version" in data:
            versions.append(data["version"])
        for plugin in data.get("plugins", []):
            if "version" in plugin:
                versions.append(plugin["version"])
        found[path] = versions
    return found


def set_version(path, version):
    data = json.loads(path.read_text(encoding="utf-8"))
    if "version" in data:
        data["version"] = version
    for plugin in data.get("plugins", []):
        if "version" in plugin:
            plugin["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help="new semver, e.g. 2.2.0")
    parser.add_argument("--check", action="store_true", help="fail (exit 1) if any manifest drifts from pyproject")
    args = parser.parse_args(argv)

    if args.check:
        base = pyproject_version()
        drift = []
        for path, versions in manifest_versions().items():
            for found in versions:
                if found != base:
                    drift.append(f"{path.relative_to(ROOT)}: {found} != pyproject {base}")
        if drift:
            print(json.dumps({"ok": False, "drift": drift}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"ok": True, "version": base}, ensure_ascii=False))
        return 0

    if not args.version:
        parser.error("give a version, or --check")
    if not re.match(r"^\d+\.\d+\.\d+$", args.version):
        parser.error(f"not a semver: {args.version}")

    text = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(VERSION_RE.sub(f'version = "{args.version}"', text, count=1), encoding="utf-8")
    for path in MANIFESTS:
        set_version(path, args.version)
    print(json.dumps({"ok": True, "version": args.version,
                      "updated": [str(p.relative_to(ROOT)) for p in (PYPROJECT, *MANIFESTS)]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
