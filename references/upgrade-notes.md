# Upgrading & migration

**For users of an installed DiagramForge skill copy.** The development record
follows below; this section is the one you need after an update.

## What survives an update

Yours forever (the sync never touches them): your spec files,
`~/.diagramforge/themes/*.json` brand profiles, `.diagramforge` project
markers, everything under `out/` and `gallery/`. See
`references/branding.md` § Customization persistence promise.

Package-owned and replaced on update: `scripts/`, `assets/`, `references/`,
`SKILL.md`. If you edited those, keep a git checkout and rebase deliberately.

## How to update

1. Pull or re-copy the new skill source over the installed directory.
2. Re-run `python -X utf8 scripts/doctor.py` — new capabilities may need new
   optional dependencies (the report says exactly what is missing).
3. Re-run `--validate-only` on one spec per layout you use; breaking spec
   changes are always announced in the version notes below.

Versions follow semver; `pyproject.toml` is the source of truth and every
host manifest is kept in sync (`scripts/bump_version.py --check` gates it).

## What changed (user-facing)

- **2.4 (this pass)** — the deferred P2 items that earned their round:
  notation lint (`scripts/lint_notation.py`: inheritance cycles, unreachable
  states, unbalanced sequence activations — advisory, typed layouts) and
  interactive-HTML drill-down (`node.link` embeds a second spec as a
  one-level-deep sub-view). ELK beyond graph/activity and
  golden-image regression stay deferred (see §7).
- **2.3** — ecosystem round: draw.io editable export (`drawio`
  format, connectors bound to shapes), interactive-HTML export toolbar
  (copy/download PNG + print, self-contained), Excalidraw arrow bindings,
  typed-layout Mermaid exports (sequence/er/class/state render natively on
  GitHub/Notion), scenario variants (`scenarios: [{name, patch}]` —
  normal/degraded/failure siblings of one spec), one-click official cloud
  icon packs (`scripts/icon_pack_install.py`), figurative graph node kinds
  (`person` / `database` / `document`), a productized visual review loop in
  SKILL.md, and the shape-semantics law + uniform-card-grid anti-pattern in
  the design system. No breaking spec changes; `scenarios` and the three
  kinds are additive.
- **2.2** — custom brand themes (`style: "custom"` +
  `scripts/onboard_brand.py`), draw.io import (`scripts/drawio_import.py`,
  all four containers), import dials (`--detail/--audience/--size`) with a
  fidelity ledger, accessible-SVG contract on every export, output security
  linter (`scripts/lint_output.py`), and example gallery
  (`scripts/build_gallery.py`). No breaking spec changes.
- **2.1** — ELK layout engine becomes the default for graph/activity
  (`layout_engine: "legacy"` pins the old behavior), render cache, Lottie /
  PDF / WebP / AVIF outputs, text-to-outline SVG mode, subprocess-coverage
  test rig.

---

# Development history (2.x → 2.1 modernization)

A record of the 2.x → 2.1 modernization pass: what changed, the measured
impact, and the engineering decisions behind the parts that were *not* done.
Read this before touching the rendering pipeline or layout engine.

## 1. Output formats (stage 1)

| Format | Status | Notes |
| --- | --- | --- |
| `gif` | optimized | Two encoders run (ffmpeg global-palette no-dither + Pillow shared-palette); the smaller file wins. ffmpeg wins on flat-color art, Pillow occasionally wins on dense glow gradients. |
| `webp` | new | Pillow transcode of the PNG frame, quality 92. |
| `avif` | new | Pillow 11+ libavif. Falls back to `avif_skipped` when the codec is missing. |
| `pdf` | new | True vector via Chromium `page.pdf()`. Ideal for `academic` style in papers. |
| `lottie` | new | Hand-written Bodymovin JSON (`scripts/lottie_export.py`). Reconstructs the op stream as shape layers + flow-dot keyframes. Opens in lottiefiles/AE. |
| `svg` | optimized | Fonts subsetted per-spec via fontTools (`scripts/svg_optimize.py`). A typical 2.8 MB SVG drops to ~140 KB (**−95%**); the CJK woff2 shrinks from ~1 MB to tens of KB. |

`ALL_FORMATS` and `BROWSER_ONLY_FORMATS` (in `render_animated_diagram.py`)
govern validation; `check_outputs` now verifies every produced format.

## 2. Layout engine — ELK.js (stage 2)

`graph` and `activity` layouts default to **ELK Layered** (bundled
`assets/vendor/elk.min.js`, EPL-2.0). The Eclipse Layout Kernel runs inside
the same headless Chromium the renderer already uses and returns node
positions + orthogonal edge routes; `_plan_graph_elk` (graph_model.py) maps
those onto the exact same plan dict the legacy path produced, so nothing
downstream changes.

- Optimal crossing minimization for directed graphs > ~12 nodes.
- `spec.layout_engine = "legacy"` pins the old longest-path + barycenter
  heuristic (used by `test_graph_model.py` for byte-stable assertions).
- Automatic fallback to legacy when ELK/Playwright/Chromium is unavailable;
  `graph_model.py` stays stdlib-importable (ELK is imported lazily).

## 3. Animation engine (stage 3) — decision record

The plan called for a deep animation refactor: rAF self-driving frame
capture, Web Animations API for the 56 illustrated icon builders, and
OffscreenCanvas workers. **The high-value, reversible subset shipped.** The
remaining piece (full WAAPI rewrite) is documented here so the decision is
auditable.

### Shipped

- **`prefers-reduced-motion`** — interactive HTML freezes `.flowdash` and the
  illustrated-icon breathing animation when the OS asks for reduced motion.
- **Illustrated-icon CSS breathing** on interactive HTML — phase-staggered
  opacity animation gives the page life without injecting the JS engine.
- **Text-to-outline conversion** (`spec.text_outlines: true`) — bundled
  opentype.js converts every `<text>` to `<path>` glyph outlines at SVG
  serialize time (`svg_renderer.svg_text_to_path`). The exported SVG becomes
  fully font-independent: it renders identically on a machine that has neither
  Excalifont nor NotoSansSC installed, and it survives being loaded as an
  `<img>` (which Chrome's "no external resources" rule would otherwise break).
  This was the prerequisite that unblocked the rAF capture below.
- **rAF self-driving frame capture** (`spec.fast_capture: true`, opt-in) —
  the GIF/MP4 frame loop can run inside a single `page.evaluate`: per frame,
  `setProgress` → serialize the (font-free) stage → `<img>` → `<canvas>` →
  PNG. Text is pre-converted to outlines once and source fonts are subset to
  the diagram's glyphs so opentype.js parses a tiny face. The capture loop
  itself is ~2× faster than per-frame `page.screenshot`, but the upfront
  opentype.js + subset cost roughly cancels the gain at default 41 frames
  (≈23 s either way) and only pulls clearly ahead at very high frame counts.
  It therefore ships **opt-in**; the default remains the reliable
  `page.screenshot` loop. Falls back automatically when opentype.js is missing
  or any frame fails.

### Not shipped, and why

- **Web Animations API rewrite of the 56 illustrated builders** would replace
  each `update(p)` closure's per-frame `setAttribute` calls with declarative
  `element.animate(keyframes)` running on the compositor thread. The benefit
  is lower per-frame CPU, but the cost is rewriting ~1600 lines of
  procedurally-generated icon motion and re-validating every icon's seamless
  loop visually — a separate workstream with high regression surface. With the
  rAF capture already cutting animation time roughly in half and the render
  cache making re-renders near-instant, the marginal payoff no longer
  justified the risk. The existing `update(p)` API is deterministic and
  seamless-loop-correct; revisit builder-by-builder if capture CPU becomes a
  measured bottleneck again.
- **OffscreenCanvas + Web Worker** — the font-rendering blocker that used to
  gate this is now solved by the text-to-outline pass, so it is technically
  feasible, but the payoff is narrow (only the `ultra` 3× preset with very
  high frame counts) and the worker orchestration adds fragility for little
  gain over the in-page rAF path that already shipped.

## 4. Mermaid import (stage 4)

`parse_mermaid` now emits `subgraph` blocks as `groups` and attaches each
member node's `parent`. `classDef`/`class` lines map Mermaid class
memberships onto DiagramForge accent roles when the class name matches a
known role (`green`/`amber`/`pink`/`cyan`/`purple`/`muted`). The return
tuple grew from 5 to 8 values — callers and tests were updated.

Excalidraw export stamps a real `updated` timestamp per export (was a frozen
constant) and tags every element with `customData: {"_diagramforge": true}`.
`fontFamily: 5` is retained — it is now Excalidraw's own Excalifont id.

## 5. Render cache (stage 5)

`scripts/render_cache.py` keys an on-disk index on `sha256` of the
output-relevant doc fields **plus the animation preset**. A re-render of an
unchanged spec into the same `outdir` reuses every artifact still on disk and
skips Chromium — measured **~28 s → ~4 s** (the residual is doc/op generation).
Lookups verify every requested format's file still exists, so deleted files
fall through to a full render automatically.

## 6. Dependencies

`pyproject.toml` now declares the project. `Pillow>=11`, `svg.path>=7`,
`fonttools>=4.51` (runtime); `playwright>=1.49` (browser optional);
`pytest>=8` (dev). Python `>=3.10`. Bundled vendor assets gained
`elk.min.js` (EPL-2.0), `opentype.min.js` (MIT), and their license notes.

## 7. Ecosystem round (2.3) — decision record

The 2.3 ecosystem round shipped the features the changelog above lists.
Deferred, with rationale:

- **Layers (drill-down boards)** — scenario variants shipped first
  because they reuse the existing render loop untouched. Layers need a
  cross-spec linking model (node → next diagram) and an interactive-HTML
  drill-down story; worth its own round rather than a rushed subset.
- **Per-layout UML notation lint** (PlantUML-grade semantics: activation
  pairing, legal guards, fragment nesting rules) — needs per-layout rule
  tables; the structural linter (`spec_graph.py lint`) plus geometry contract
  already cover the objective failure modes.
- **ELK beyond graph/activity** — dfd/deployment/component planners are not
  the measured bottleneck; revisit when a real layout hurts.
- **Golden-image visual regression** — the
  repo explicitly rejects golden images (`tests/test_examples_fresh.py`);
  the gallery sha256 manifest + geometry ratchet cover drift where it
  matters without pinning pixels.
- **Image→diagram model pipeline** —
  out of scope for a deterministic, offline skill.
