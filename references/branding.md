# Branding: custom themes, onboarding, and persistence

The four bundled styles (`slate` / `report` / `academic` / `blueprint`) cover
most formal contexts. When a diagram must match a specific brand, use a
**custom theme**: a JSON file mapping every theme key to a `#hex` color,
generated from a website by `scripts/onboard_brand.py` or written by hand.

## The onboarding flow

```bash
python -X utf8 scripts/onboard_brand.py --url https://yoursite.com --slug acme
```

The script renders the page in headless Chromium, samples computed styles
(body background/text, headings, links, buttons, muted text), reads `:root`
CSS custom properties, and falls back to a screenshot color histogram for the
accent. It writes `~/.diagramforge/themes/acme.json` and prints a **fidelity
receipt**: sampled URLs, the source of each role's value, detected fonts
(informational — the renderer keeps its bundled fonts), contrast ratios, and
every automatic adjustment. Nothing is silently replaced.

Contrast floors are enforced, not advisory: ink-on-background must reach
WCAG AA 4.5:1 and secondary text 3:1. When a sampled color fails, the receipt
records the adjusted value and the reason; a theme that still fails is
rejected at load time with `theme_error:contrast` and a suggested fix.

## Using a custom theme

Three ways, in resolution order:

1. **Spec field** — `"style": "custom"` + `"theme_file": "acme.json"`
   (path resolves relative to the spec file).
2. **Project marker** — a `.diagramforge` file in the project directory (or
   any parent) containing `theme: acme` selects
   `~/.diagramforge/themes/acme.json` for every `"style": "custom"` spec in
   that tree. Marker projects share the named profile without copying it.
3. Neither present → an explicit `theme_error:no_source` failure. The
   renderer never falls back to a default style silently.

A malformed marker (no valid `theme: <slug>` line) fails with
`theme_error:marker_malformed` and instructions — fix or remove it.

## Authoring a theme by hand

Start from a bundled palette (see `STYLE_THEMES` in
`scripts/render_animated_diagram.py`) and edit the anchors: `bg` (paper),
`white` (ink), `muted`, `frame` (hairline), `core_stroke` (accent). The
remaining keys are derived fills and neutral bands — keep them in the same
family. The theme must define **exactly** the required key set; loading
validates keys, hex format, and contrast (`theme_error:*`, exit 2).

The light/dark **finish** (glow beams vs clean paper) derives from `bg`
luminance; you don't set it.

## Customization persistence promise

Files **you** own — never touched by skill updates or syncs:

- your spec JSON files
- `~/.diagramforge/themes/*.json` (named brand profiles)
- `.diagramforge` project markers
- everything under `out/` and `gallery/`

Files the **package** owns — replaced when the skill is updated:

- `scripts/`, `assets/`, `references/`, `SKILL.md`

Never fork package files to hold a brand; that is what custom themes are for.
If you must edit package sources, keep a git checkout of the skill and sync
deliberately.

## Fonts

This version applies brand **colors** only. The receipt records detected
font stacks so you can see what the site uses, but rendered output keeps the
bundled Noto Sans SC / Excalifont pipeline.
