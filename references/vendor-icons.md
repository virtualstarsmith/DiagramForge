# Vendor Icon Packs

DiagramForge renders cloud/vendor brand icons when you supply them, without

## How resolution works

For `{"icon": "<name>"}` the renderer resolves in this order:

1. `assets/icons/vendor/<pack>/<name>.svg` — your local packs, highest priority
2. `assets/icons/tabler/<name>.svg` — bundled hand-drawn-friendly outline set
3. Semantic alias table (e.g. `aws` → `world`) — portable fallback
4. Primitive hand-drawn shapes, then a plain circle

Specs stay portable: the same spec renders official icons on your machine and
generic fallbacks everywhere else.

## Getting official packs

Download these yourself into `assets/icons/vendor/<pack>/` (the folder is
git-ignored on purpose):

| Pack | Source | License note |
| --- | --- | --- |
| AWS Architecture Icons | https://aws.amazon.com/architecture/icons/ | Free for architecture diagrams; no redistribution |
| Microsoft Azure icons | https://learn.microsoft.com/azure/architecture/icons/ | Use in diagrams allowed; see terms |
| Google Cloud icons | https://cloud.google.com/icons | Use in diagrams allowed; see terms |
| Kubernetes icons | https://github.com/kubernetes/community/tree/master/icons | Apache-2.0 / CC-BY per file — check labels |
| Simple Icons (brand logos) | https://simpleicons.org/ | CC0-1.0 |
| Tabler (full set) | https://tabler.io/icons | MIT |

Tips:

- Convert to SVG, one file per icon, named after the spec key you want
  (`s3.svg` → `{"icon": "s3"}`). Stroke-style 24x24 icons blend best; colored
  logos are restroked in theme ink by the renderer.
- Keep the pack's LICENSE file inside its folder for your own records.

## Optional: search 200k+ icons online

`scripts/icon_search.py` wraps the Iconify API (requires network):

```bash
# search, with license info per collection
python -X utf8 scripts/icon_search.py search "kubernetes"

# download into a pack (pack folder defaults to the icon's prefix)
python -X utf8 scripts/icon_search.py fetch logos:kubernetes --pack k8s --name kubernetes

# see what is installed
python -X utf8 scripts/icon_search.py list
```

Check each collection's license before commercial publishing. DiagramForge never
requires network access at render time; this tool is a convenience only.
