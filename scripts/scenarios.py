#!/usr/bin/env python3
"""Scenario variants: one spec, several states of the same system.

A scenario is a named partial patch applied over the base spec before
rendering — normal / degraded / failure views of one architecture from a
single source of truth, in the spirit of d2's scenario boards.

Variants share the base layout, canvas, and visual system; patches touch
content by identity:

- item lists merge by `id` (nodes, participants, entities, classes, states, ...)
- relation lists merge by `from` + `to` (edges, transitions, relations,
  messages, flows, connections, links)
- dicts deep-merge (title, panels, ...); scalars replace; unknown lists replace
- `status` sugar on an item maps to the semantic accent: degraded -> amber,
  failed -> pink (an explicit `accent` in the same item wins)

Forbidden in patches: `layout`, `canvas`, `style`, `scenarios` — a variant
must stay the same diagram. Rendering is not part of this module; the
renderer loops over `expand()`.
"""
from __future__ import annotations

import copy
import re

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
STATUS_ACCENT = {"degraded": "amber", "failed": "pink"}
FORBIDDEN_PATCH_KEYS = {"layout", "canvas", "style", "scenarios"}
MAX_SCENARIOS = 4
SCENARIO_LAYOUTS = {"graph", "panorama", "swimlane", "dfd", "c4", "sequence"}


def _status_to_accent(value):
    """Apply status sugar recursively: any dict with a known `status` and no
    explicit `accent` gains the semantic accent for that status."""
    if isinstance(value, dict):
        out = {k: _status_to_accent(v) for k, v in value.items()}
        status = out.get("status")
        if isinstance(status, str) and status in STATUS_ACCENT and "accent" not in out:
            out["accent"] = STATUS_ACCENT[status]
        return out
    if isinstance(value, list):
        return [_status_to_accent(v) for v in value]
    return value


def _merge_item_lists(base, patch, key_fields):
    """Merge patch items into base items by identity; unmatched patch items
    are ignored by design — a variant retouches the base, it never invents
    elements that would desync the two pictures."""
    base_items = list(base)
    index = {}
    for i, item in enumerate(base_items):
        ident = tuple(item.get(f) for f in key_fields)
        index.setdefault(ident, i)
    for item in patch:
        ident = tuple(item.get(f) for f in key_fields)
        if ident in index:
            i = index[ident]
            base_items[i] = _merge_value(base_items[i], item)
    return base_items


def _merge_value(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = _merge_value(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(patch, list):
        if patch and all(isinstance(i, dict) and "id" in i for i in patch) and \
                all(isinstance(i, dict) and "id" in i for i in base):
            return _merge_item_lists(base, patch, ("id",))
        if patch and all(isinstance(i, dict) and "from" in i and "to" in i for i in patch) and \
                all(isinstance(i, dict) and "from" in i and "to" in i for i in base):
            return _merge_item_lists(base, patch, ("from", "to"))
    return copy.deepcopy(patch)


def validate(spec):
    """Scenario validation -> (errors, warnings) in the renderer's shape
    ({path, message, fix})."""
    errors, warnings = [], []
    layout = spec.get("layout", "panorama")
    if layout not in SCENARIO_LAYOUTS:
        errors.append({
            "path": "$.layout",
            "message": f"scenarios are not defined for layout '{layout}'",
            "fix": f"declare scenarios on one of: {', '.join(sorted(SCENARIO_LAYOUTS))}",
        })
        return errors, warnings
    items = spec.get("scenarios")
    if not isinstance(items, list) or not items:
        errors.append({
            "path": "$.scenarios",
            "message": "must be a non-empty list of {name, patch} objects",
            "fix": 'e.g. "scenarios": [{"name": "failure", "patch": {...}}]',
        })
        return errors, warnings
    if len(items) > MAX_SCENARIOS:
        errors.append({
            "path": "$.scenarios",
            "message": f"at most {MAX_SCENARIOS} scenarios per spec",
            "fix": "split the story across specs instead of raising the cap",
        })
    names = set()
    for i, item in enumerate(items):
        path = f"$.scenarios[{i}]"
        if not isinstance(item, dict):
            errors.append({"path": path, "message": "must be an object", "fix": 'use {"name": ..., "patch": {...}}'})
            continue
        name = item.get("name")
        patch = item.get("patch")
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append({
                "path": f"{path}.name",
                "message": f"invalid scenario name {name!r}",
                "fix": "use lowercase letters, digits, hyphens (max 24 chars)",
            })
        elif name in names:
            errors.append({"path": f"{path}.name", "message": f"duplicate scenario name '{name}'",
                           "fix": "scenario names must be unique"})
        else:
            names.add(name)
        if not isinstance(patch, dict) or not patch:
            errors.append({"path": f"{path}.patch", "message": "must be a non-empty object",
                           "fix": "patch the nodes/edges/copy that change in this scenario"})
            continue
        for key in FORBIDDEN_PATCH_KEYS:
            if key in patch:
                errors.append({
                    "path": f"{path}.patch.{key}",
                    "message": f"'{key}' cannot change in a scenario",
                    "fix": "a variant shares the base layout, canvas, and visual system; patch content only",
                })
        status = patch.get("status")
        if status is not None and not isinstance(status, str):
            errors.append({"path": f"{path}.patch.status", "message": "must be a string",
                           "fix": "use degraded or failed (mapped to the semantic accent)"})
    return errors, warnings


def expand(spec):
    """Validate (raising nothing — the renderer validates first) and return
    [(name, variant_spec), ...] with the `scenarios` key stripped from each
    variant so rendering never recurses."""
    variants = []
    for item in spec.get("scenarios", []):
        patch = _status_to_accent(item.get("patch", {}))
        variant = _merge_value(spec, patch)
        variant.pop("scenarios", None)
        variants.append((item["name"], variant))
    return variants
