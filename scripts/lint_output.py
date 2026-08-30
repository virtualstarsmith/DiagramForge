#!/usr/bin/env python3
"""Lint generated DiagramForge artifacts (.svg / .html) against the output
security contract.

The renderer never emits active or remote content; finding any of it in a
deliverable means a spec field or a bug smuggled it in. Categories:

- ``remote-asset``    src/href/xlink:href/poster/data pointing at http(s)://,
                      protocol-relative //, or a non-fragment local reference
                      (artifacts must be self-contained)
- ``js-url``          javascript: in any URL-bearing attribute
- ``css-import``      @import anywhere
- ``css-url``         url(...) that is neither a #fragment nor a data: URI
- ``executable-attr`` inline event handlers (on*), srcdoc, formaction
- ``active-element``  <iframe> <object> <embed> <form> <base>

Inline <script> is allowed: the interactive HTML ships one IIFE by design.
``data:`` URIs are allowed (embedded fonts/icons/custom images).

CLI: ``python -X utf8 scripts/lint_output.py <file...>`` prints a JSON report;
exit 0 when clean, 1 on violations, 2 on usage errors (missing/unreadable
file, unsupported extension).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

IMPORT_ANY_RE = re.compile(r"@import\b", re.IGNORECASE)
URL_ANY_RE = re.compile(r"url\(\s*(['\"]?)(?P<url>[^)'\"]+?)\1\s*\)", re.IGNORECASE)

REMOTE_PREFIXES = ("http://", "https://", "//")
URL_ATTRS = {"src", "href", "xlink:href", "poster", "data", "action", "formaction"}
EXECUTABLE_ATTRS = {"srcdoc", "formaction"}
ACTIVE_ELEMENTS = {"iframe", "object", "embed", "form", "base"}

SUPPORTED_SUFFIXES = {".svg", ".html", ".htm"}


def _line_col(text, offset):
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset + 1 if last_nl < 0 else offset - last_nl
    return line, col


def _snippet(text, offset, radius=40):
    start = max(0, offset - radius)
    end = min(len(text), offset + radius)
    return " ".join(text[start:end].split())


class _TagScanner(HTMLParser):
    """Collect attribute/element violations; works for HTML and SVG sources."""

    def __init__(self, text, name):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.name = name
        self.violations = []

    def _add(self, category, message, pos=None):
        line, col = pos if pos is not None else self.getpos()
        self.violations.append(
            {
                "file": self.name,
                "line": line,
                "col": col,
                "category": category,
                "message": message,
                "snippet": _snippet(self.text, self.getpos()[1] if pos is None else 0),
            }
        )

    def handle_starttag(self, tag, attrs):
        if tag in ACTIVE_ELEMENTS:
            self._add("active-element", f"<{tag}> is not allowed in a self-contained artifact")
        for attr, value in attrs:
            if attr.startswith("on"):
                self._add("executable-attr", f"inline event handler '{attr}' is not allowed")
            if attr in EXECUTABLE_ATTRS:
                self._add("executable-attr", f"attribute '{attr}' is not allowed")
            if attr in URL_ATTRS and value:
                self._check_url_attr(attr, value)

    def _check_url_attr(self, attr, value):
        v = value.strip()
        low = v.lower()
        if low.startswith("javascript:"):
            self._add("js-url", f"{attr}='javascript:…' is not allowed")
        elif low.startswith(REMOTE_PREFIXES):
            self._add("remote-asset", f"{attr} references a remote URL: {v[:80]}")
        elif low.startswith(("data:", "#", "mailto:")):
            pass
        elif v:
            self._add(
                "remote-asset",
                f"{attr} references an external file ({v[:80]}); artifacts must be self-contained",
            )


def _scan_css(text, name, violations):
    for match in IMPORT_ANY_RE.finditer(text):
        line, col = _line_col(text, match.start())
        violations.append(
            {
                "file": name,
                "line": line,
                "col": col,
                "category": "css-import",
                "message": "CSS @import is not allowed",
                "snippet": _snippet(text, match.start()),
            }
        )
    for match in URL_ANY_RE.finditer(text):
        # A `url(` glued to an identifier (createObjectURL(, revokeObjectURL()
        # is a JavaScript member call, not a CSS resource reference.
        if match.start() > 0 and (text[match.start() - 1].isalnum() or text[match.start() - 1] in "_$"):
            continue
        url = match.group("url").strip()
        low = url.lower()
        if low.startswith(("#", "data:")):
            continue
        line, col = _line_col(text, match.start())
        violations.append(
            {
                "file": name,
                "line": line,
                "col": col,
                "category": "css-url",
                "message": f"non-fragment CSS url() is not allowed: {url[:80]}",
                "snippet": _snippet(text, match.start()),
            }
        )


def lint_text(text, name="<string>"):
    """Return the list of contract violations found in *text*."""
    violations = []
    scanner = _TagScanner(text, name)
    try:
        scanner.feed(text)
        scanner.close()
    except Exception:
        # Malformed markup is not this linter's concern; keep CSS findings.
        pass
    violations.extend(scanner.violations)
    _scan_css(text, name, violations)
    violations.sort(key=lambda v: (v["line"], v["col"]))
    return violations


def lint_file(path):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file type: {path} (expected .svg/.html)")
    return lint_text(path.read_text(encoding="utf-8"), str(path))


def lint_files(paths):
    violations = []
    for path in paths:
        violations.extend(lint_file(path))
    return {"ok": not violations, "violations": violations}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lint generated .svg/.html artifacts against the output security contract.")
    parser.add_argument("files", nargs="+", help="artifact files to lint")
    args = parser.parse_args(argv)

    try:
        report = lint_files(args.files)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
