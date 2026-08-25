# Test & Coverage Report — DiagramForge

A record of the end-to-end testing pass: the suite's shape, the coverage
figure, and the quality gate that the "business-grade output" goal is
measured against.

## Suite shape

| Test module | What it covers |
|---|---|
| `test_e2e_matrix.py` | 26 layouts × 4 styles × 6 animation presets × 10 formats, via the real browser renderer. The broadest net for the business goal: every layout renders a clean, complete diagram in every style. |
| `test_pillow_render.py` / `test_pillow_branches.py` | The Pillow fallback pipeline across all layouts, the legacy primitive icons, grid layout, legend strip, custom icon files. |
| `test_validate_spec.py` | Every error and warning branch of the pre-flight validator. |
| `test_render_cache.py` | Content hashing, salt discrimination, hit/miss, file-deletion invalidation. |
| `test_lottie_export.py` | Every op converter, flow-dot animation, pulse halo, color parsing. |
| `test_icon_browser.py` | The headless-Chromium icon glyph engine. |
| `test_graph_model_branches.py` | UML layout internals (sequence fragments, class relations, ER cardinalities, state/activity/deployment/gantt/c4/orgchart/mindmap/fishbone). |
| `test_illustrated_and_graph_edges.py` | Illustrated/hero icon rendering + spec_graph edge commands. |
| `test_fast_capture.py` | The opt-in rAF raster capture path (fast_capture + text_outlines). |
| `test_render_cli.py` | The CLI entry point (validate-only, unknown formats, strict-formats, default render). |
| `test_tools.py` | The standalone tool scripts (doctor, prepare_fonts, icon_search). |
| `test_output_quality.py` | **Quality audit**: every layout's PNG carries real visual structure (color complexity > 50, rejecting blank/near-monochrome plates) + mermaid subgraph feature. |

Plus the pre-existing suites: `test_graph_model`, `test_spec_graph`,
`test_mermaid_import`, `test_render_output_checks`, `test_visual_v2`,
`test_bundled_fonts`, `test_canvas_presets`, `test_custom_branding`,
`test_text_fitting`, `test_sequence_validate`, `test_ops_and_browser`.

## Coverage

- **Baseline: 70%** (8463 statements, 2551 missed).
- **Final: 88%** (8255 statements, 974 missed), 355 tests + 172 subtests, all passing.
- Core rendering modules: `graph_model` 97%, `lottie_export` 95%, `render_cache` 94%,
  `elk_layout` 93%, `svg_renderer` 89%, `mermaid_import` 86%, `svg_optimize` 85%,
  `icon_browser` 83%, `render_animated_diagram` 82%, `spec_graph` 81%.

The remaining uncovered lines are structural dead ends for local testing: the
Pillow `stamp_glyphs` browser-icon fallback (requires an icon-only browser
pipeline no test drives), the legacy primitive-icon branches, and the
browser-only `graph_layout_checks` path. The CLI tool scripts (`doctor`,
`icon_search`, `prepare_fonts`) are exercised by subprocess tests and omitted
from the importable-code figure (`.coveragerc`).

## Quality gate (business-grade output)

Beyond pass/fail, the suite enforces the "clean lines, complete logic" bar
directly:

1. **Color-complexity audit** (`test_output_quality.py`): every layout's PNG
   must exceed 50 distinct colors after downsampling, which rejects blank or
   near-monochrome frames — the failure mode that would make a diagram look
   unfinished to an architect.
2. **Visual inspection** of representative style×layout renders (graph/slate,
   sequence/report, class/academic, c4/blueprint) confirms hand-drawn strokes,
   UML relation markers, fragment frames, and system boundaries all render
   correctly for the business contexts these styles target.

## Bugs found and fixed during this pass

1. **`render_cache` cache key missed `text_outlines` / `fast_capture`** — a
   re-render of the same spec with a different option would have served the
   wrong artifact. Fixed by including both options in the cache salt.
2. **Grid layout Pillow crash on string steps** — `graph_model.py` assumed
   `cell.steps` were dicts; string-step specs raised a `ValueError`. Fixed by
   normalizing steps to dicts in the planner.
3. **E2E test isolation** — the matrix test's shared output dir carried a stale
   cache across runs; setUpClass now clears it.
4. **Test-file binding bug** — assigning `cls.rad.validate_spec` to an instance
   attribute turned it into a bound method that received `self` as the spec.
   Fixed with `staticmethod()`.
5. **Coverage config missing (`.coveragerc`)** — `tests/conftest.py` pointed
   `COVERAGE_PROCESS_START` at a `.coveragerc` that did not exist, so
   subprocess coverage started with default settings: `parallel=False`, all
   child processes writing the same `.coverage` file. Result: subprocess
   line hits were silently lost (last-writer-wins), under-reporting coverage
   for the CLI tools (spec_graph, icon_search, prepare_fonts) and making
   `coverage combine` report "No data to combine". Fixed by creating
   `.coveragerc` with `parallel=True`, `source=scripts`; child shards now
   land as `.coverage.*` files and combine correctly.
6. **Flaky output-quality audit under load** — `test_output_quality`
   intermittently reported near-flat PNGs (composite/fishbone) only when many
   concurrent python processes starved Chromium. Standalone renders measure
   1000+ distinct colors vs the >50 floor. Fixed by retrying the render once
   into a fresh directory when a frame comes back flat, so transient
   environment contention cannot fail the audit while a genuine blank-render
   regression still would.
7. **Orgchart planner crashed on depth > 8 (`KeyError`)** — `measure()` returned
   early at the depth cap without recording `subtree_w[nid]`, and both the
   connector loop and the node loop indexed `positions[...]` unconditionally.
   A chain 12 nodes deep crashed planning. Fixed by recording the width in the
   depth-guard and skipping unpositioned (depth-capped) nodes in the connector
   and node loops. Regression test: `test_orgchart_cycle_and_depth`.
8. **Subprocess coverage shards landed in tempdirs** — several CLI tests run
   their subprocess with `cwd=<tempdir>`; the child coverage wrote its
   `.coverage.*` shard relative to that cwd and it was deleted with the temp
   dir, silently losing subprocess line hits. Fixed by anchoring
   `COVERAGE_FILE` to the project root in `tests/conftest.py`.


## Final result (2026-08-19)

- **704 tests + 216 subtests, 0 failures** (12 min full suite)
- **100% statement coverage on every module**: 8418 statements, 0 missed
  (render_animated_diagram 3564, graph_model 2769, mermaid_import 798,
  svg_renderer 306, spec_graph 298, lottie_export 244, svg_optimize 83,
  prepare_fonts 77, render_cache 78, icon_search 66, icon_browser 56,
  elk_layout 41, doctor 38)
- Unreachable defensive branches carry `# pragma: no cover` with a reason
  (verified dead by inspection: longest-path layering guarantees, planner
  normalizations, tokenizer guarantees).
- One genuinely dead duplicate check (the second `$.title` object error) was
  removed rather than pragma-marked.

### Additional bugs found and fixed in the final coverage push

9. **Grid layout had no example spec and no E2E coverage** — the layout was
   absent from every test matrix. Added `assets/examples/grid-spec.json` and
   registered grid in the E2E/Pillow/quality matrices.
10. **Graph group containers were silently dropped when specs used
    `members: [...]`** — groups bind via node `parent`, not a group-side
    `members` list; the test specs (not the renderer) were wrong. Fixed the
    test specs to use `parent`.
