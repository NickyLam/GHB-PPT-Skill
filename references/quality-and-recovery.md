# Quality, Rendering, and Recovery

## Required gates

Treat a deck as deliverable only when all available gates complete:

1. Authored SVG gate: upstream SVG rules, layout diversity, and visual asset
   checks report zero errors.
2. Finalized SVG gate: embedded images/icons, geometry, text, and content load
   report zero errors.
3. PPTX structure gate: ZIP, Content Types, relationships, IDs, masters,
   layouts, themes, media, page roles, notes, fonts, brand, object bounds, full
   slide images, and planned titles pass.
4. Render gate: when LibreOffice is available, generate PDF, per-page PNGs, and
   a contact sheet and inspect every page.

Warnings are not passes by default. Explain and review every warning. The
bundled template intentionally has one cover object extending beyond the slide
for bleed. A missing Microsoft YaHei warning means geometry can be reviewed,
but Chinese visual fidelity cannot be claimed.

## Visual review

Inspect the contact sheet, then open suspicious page PNGs. Check:

- missing or repeated titles and page numbers;
- missing labels, empty cards, placeholder text, or blank pages;
- clipped text, object overflow, unintended overlap, and tiny type;
- full white rectangles hiding the template background;
- full-slide pictures used in place of editable content;
- font substitution, missing glyphs, and low contrast;
- repeated geometry that contradicts `layout_plan.json`.

Record subjective items as manual review. Never invent an aesthetic score.
人工最终批准始终独立于确定性检查和可选模型评审。

The optional adapter runs only through explicit `review` or `build --review`
after deterministic and render evidence is fresh. Its status is reported as
`skipped`, `unavailable`, `passed`, `needs-revision`, `limited`, or `error`;
these values do not rewrite deterministic findings. `completion_status` may be
`failed` when deterministic delivery failed or the optional review errored. A
missing adapter remains `skipped` in the offline default. Missing fonts force
typography review to `limited`.

Treat `needs-revision` as authored-content advice: first preserve semantics and
remove redundant wording, then choose another catalogued variant or density.
Split a page only at a semantic boundary and request user judgment before any
semantic deletion, invention, or page-count change. After a change, regenerate
the affected SVG, PPTX, render, evidence manifest, optional review, and final
reports; stale evidence cannot be reused.

## Repair loop

Use `--repair-attempts 0..3`. The pipeline only retries deterministic repairs
such as cover-font normalization or rebuilding a merge with known structural
codes. It does not auto-rewrite authored content or mask unknown failures.

After a repair, rerun the affected SVG gate, rebuild, validate, render, and
inspect again. Preserve the failed run under `.ghb/runs/` and do not delete its
intermediate evidence.

## Resume after interruption

1. Read `.ghb/state.json` and the newest `.ghb/runs/*/run.json`.
2. Confirm that checkpoint outputs still exist and match the current project.
3. Rerun the last failed or incomplete command.
4. Use `--keep-intermediate` while diagnosing.
5. Do not reuse a passing checkpoint after its inputs changed.

Run `doctor` when the template, Python dependencies, renderer, fonts, or
directory permissions may have changed.

## Evidence to retain

Keep the final PPTX, source/final SVGs, cover/content intermediates, run log,
state file, `.ghb/evidence-manifest.json`, authored/finalized SVG JSON,
`reports/visual-review.json` when present, final JSON/Markdown report, page
PNGs, contact sheet, and any known-limitations note.
