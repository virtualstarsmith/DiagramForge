# DiagramForge Design System

Codified visual rules for authoring specs. The renderer enforces geometry and
text fitting; this document is the deterministic design layer an author (human
or agent) applies when choosing layouts, colors, icons, and copy. Read it
before writing a spec from scratch.


## 1. Semantic color roles

Specs never name raw hex for meaning; they use `accent` / `color` keys that map
onto the active style's palette. Assign colors by **role**, not taste:

| Role | Accent key | Use for |
| --- | --- | --- |
| Primary / process | `core_stroke` (blue) | the main pipeline, hero concepts |
| Success / approved | `green` | happy path, passed checks, outputs |
| Warning / attention | `amber` | retries, budgets, degradations |
| Error / risk | `pink` | failures, dead ends, guards tripped |
| Secondary process | `cyan` | parallel or supporting flows |
| Alternate category | `purple` | second category in comparisons |
| Neutral / external | `muted` | third-party systems, annotations |
| Emphasis text | `white` | primary labels and titles |

All four styles (`slate`, `report`, `academic`, `blueprint`) re-map these keys automatically, so a spec
keeps its semantics when the style flips.

**60-30-10 rule**: ~60% of the canvas is empty background and neutral ink,
~30% carries the primary/process color, ~10% is highlight color (title
highlight, hero accents). If everything is colorful, nothing is.

## 1a. Hierarchical bands (enterprise scheme)

Swimlane and grid bands follow the Carbon / C4 convention for ordered
structure: **levels read through neutral-gray lightness steps, never hue
swaps**. The renderer assigns bands automatically — do not color lanes by
hand unless the lane carries a real status:

- Bands step `lane_band_0` → `lane_band_1` → `lane_band_2` → `lane_band_3`
  (lightest to deepest) by hierarchy position; the left title column sits one
  step deeper than its band.
- **External layers sink to the deepest gray** (`lane_band_3` + `lane_border`
  stroke). The planner detects lanes whose title/subtitle contains 外部 /
  第三方 / external / 3rd / third-party, or you can force it with
  `accent: "external"`. This is the C4 "external system" convention: outside
  systems are muted so the core system keeps the visual floor.
- Semantic accents (`accent: "green" | "purple" | "amber" | "blue"`) stay
  available for lanes that genuinely carry status — a passed review stage, a
  gated budget lane — but they are the exception, not the default.
- WCAG floor: band-to-canvas contrast is intentionally weak (~1.1-1.3:1);
  band borders (`frame` / `lane_border`) carry the 3:1 non-text requirement,
  and lane titles carry the level semantics in text (SC 1.4.1 redundancy).

## 2. Type hierarchy

The renderer auto-fits text downward; author copy for these five levels:

| Level | Target size (px) | Style | Use |
| --- | --- | --- | --- |
| Hero title | 44-47 | hand font, bold | `title.prefix` / `title.highlight` |
| Section title | 20-22 | hand font, bold | lane titles, panel footers, decision |
| Card title | 15-18 | bold sans | card/step/node titles (1-3 words) |
| Body | 12-14 | regular | card bodies (two short lines max) |
| Caption | 8-13 | muted | subtitles, edge labels, signatures |

Rules:

- **Rewrite, don't shrink.** If `fit_text` had to drop more than one level to
  fit, shorten the copy instead. `--validate-only` warns about long text.
- Never rely on the emergency shrink floor; it exists to avoid crashes, not
  for publishing.
- CJK glyphs are ~2x wider than Latin at the same point size — halve character
  budgets for Chinese copy.

## 3. Visual metaphor mapping

Structure carries meaning. Pick the layout element whose shape matches the
semantics:

| Meaning | Expression |
| --- | --- |
| One → many (fan-out) | `graph` node with several outgoing `flow` edges; beams diverge in topological phase order |
| Cycle / retry | `graph` edge with `kind: "loop"` (dashed return channel) or swimlane right-to-left connection |
| Comparison ("the N types of X") | `swimlane` lanes side by side with alternating tints |
| Sequence over time | `graph` with `direction: "right"`, `flow` animation |
| Gate / approval | `decision` diamond with `yes_label` |
| Whole system at a glance | `panorama` (inputs → core → decision → output + detail panels) |
| External / third party | node with `accent: "muted"` and dotted edge `style` |

## 4. Anti-pattern guardrails

Reject or rework specs that hit these:

1. **Label collisions** — two edge labels on parallel edges; spread with
   `accent` differentiation or merge the edges.
2. **Spaghetti arrows** — more than 2 edges crossing the same region; reroute
   by reordering nodes, using `kind: "loop"` lanes, or splitting the view.
3. **Zone overlap** — manual `x`/`y` pins that push nodes into panels or other
   nodes; `--check` reports graph clipping/balance issues.
4. **Wall of text** — bodies over two lines; move detail into panels, the
   interactive HTML tooltips, or the article itself.
5. **Rainbow soup** — more accent roles than content groups; re-read 60-30-10.
6. **Uniform emphasis** — every icon `hero`, every title highlighted; pick 1-3
   heroes that carry the story (`icon_style` guidance lives in SKILL.md §7).

## 5. Node-count guidance (per diagram)

| Layout | Comfortable | Hard limit | Over budget? |
| --- | --- | --- | --- |
| `panorama` | 6-15 elements | 6 inputs / 4 cards / 3 panels | group adjacent steps into one card; move detail into panels |
| `swimlane` | 3-4 lanes × 3-4 steps | 5 lanes × 5 steps | split by category into two diagrams |
| `graph` | 6-15 nodes | 24 nodes / 40 edges | split into focused views; render a neighborhood with `spec_graph.py around` |

Big systems read better as 2-3 linked diagrams than one dense one.

## 6. Motion discipline

"Static restraint, animated emphasis": the static frame must read cleanly on
its own; motion only guides the eye.

- 1-3 active flow paths at a time; more reads as noise.
- `motion_level: "subtle"` for dense diagrams, `"cinematic"` only for hero art.
- Loop length should divide the total frame count so GIFs loop seamlessly
  (the browser renderer enforces this; keep `frames` at the preset minimums).
