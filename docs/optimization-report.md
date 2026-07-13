# GHB-PPT-Skill Optimization Report

Date: 2026-07-11  
Branch: `codex/goal-optimize-ghb-ppt-skill`

## Outcome

The repository now has one resumable CLI for cover generation, SVG quality
gates, editable body export, collision-safe master merge, final validation,
rendering, and reporting. The current nine-case optimized baseline passes every
structural and layout hard gate. Chinese rendering remains explicitly
unverified because Microsoft YaHei is absent from the LibreOffice environment.

## Measured before and after

| Measure | Before | Current optimized result |
|---|---:|---:|
| Automated tests | 18 passed | 55 passed |
| Deterministic fixture cases | 9 | 9 |
| Rendered baseline pages | 57 | 57 |
| Contact sheets | 9 | 9 |
| Final machine-readable reports | 0 | 9 JSON + 9 Markdown |
| `ppt_to_md` readbacks | Manual/unsaved | 9 saved; 57/57 slide sections |
| Ending decks with incomplete master-layout registration | 8 of 8 | 0 of 8 |
| Final report errors | Not available | 0 across 9 decks |
| Final report warnings | Not available | 18: 9 intentional cover bleeds + 9 missing-font warnings |
| Detected body object overflows | Not measured | 0 |
| Detected possible text overlaps | Not measured | 0 |
| Full-slide pictures | Not measured | 0 |
| Editable object evidence | Partial XML summaries | 336 text objects + 793 shapes across 57 pages |

The pre-change files all passed ZIP integrity and opened in python-pptx, but
that was insufficient: eight decks with ending slides used an ending layout
that the injected master did not register. The new graph-aware validator
detects this class of one-sided relationship defect.

## Reliability improvements

### Unified and resumable execution

`scripts/ghb_ppt.py` provides `doctor`, `init`, `analyze-template`,
`build-cover`, `check-svg`, `build-content`, `merge`, `validate`, `render`,
`report`, and `build`. Each run records stage commands, exit codes, stdout,
stderr, outputs, and duration under `.ghb/runs/`; `.ghb/state.json` records
checkpoints for recovery.

The build locates timestamped template-fill outputs deterministically, removes
SVG preview backgrounds with a validated idempotent function, keeps failed
evidence, returns non-zero exit codes, and limits deterministic repair retries
to `0..3`.

### Collision-safe OOXML merge

The merge now uses namespace-aware XML mutation and allocates IDs, part names,
theme names, media names, and relationship IDs from the destination package.
It registers cover, body, and ending layouts in the injected master, resolves
media/tag basename collisions, verifies targets, and atomically replaces the
output.

An actual compatibility failure was reproduced: LibreOffice rejected
`[Content_Types].xml` when ElementTree serialized the OPC namespace with an
`ns0:` prefix. The merge now emits the namespace as the default and the
validator enforces this wire format.

## Quality-loop improvements

The authored and finalized SVG stages now combine three deterministic gates:
upstream SVG rules, layout-plan diversity, and GHB visual asset checks. The
final PPTX report adds per-slide object counts, editability evidence, master
mounts, notes, page numbers, bounds, possible text overlap, empty text,
full-white backgrounds, and full-slide image detection.

When LibreOffice is available, `render` uses an isolated writable profile and
produces PDF, page PNGs, a contact sheet, and `render-report.json`. The final
report consumes that evidence and carries renderer warnings forward.

## Visual failures found and repaired

The optimization did not treat a successful render process as a visual pass.
Three defects were found through rendered evidence:

1. Long stress titles produced two out-of-bounds objects. Body conclusion
   titles now use an adaptive two-line 22 px treatment; the repaired 6-page
   stress build reports zero errors.
2. Fixture cards were empty because label generation was accidentally nested
   under the icon-only branch. Regression tests now require every fixture item
   to appear as visible SVG text.
3. Fixtures claimed different `data-layout` values while drawing the same card
   row. They now use actual Office-safe timeline, layered architecture,
   waterfall, matrix, pyramid, swimlane, flywheel, staircase, and iceberg
   geometry. Long component labels wrap into separate editable text nodes
   without dropping characters.

The failure and intermediate evidence is preserved locally under:

- `artifacts/baseline/after-failed-overflow/`
- `artifacts/baseline/after-failed-empty-cards/`
- `artifacts/baseline/after-fixed-labels/`

Independent post-fix visual inspection confirmed that A uses seven genuinely
different body structures and C uses four. No new component clipping, object
overlap, or cover subtitle/date collision was found.

## Baseline evidence

Pre-change evidence:

- `artifacts/baseline/before/`
- [baseline report](baseline-report.md)

Current optimized evidence:

- `artifacts/baseline/after/`
- each case contains source, plan, raw/final SVG, cover/content/final PPTX,
  OOXML summary, run log, PDF, per-page PNGs, contact sheet, authored/finalized
  SVG JSON, saved `ppt_to_md` readback, and final JSON/Markdown report.

Representative current contact sheets:

- `artifacts/baseline/after/A_technical_sharing/render/contact-sheet.png`
- `artifacts/baseline/after/B_management_plan/render/contact-sheet.png`
- `artifacts/baseline/after/C_layout_stress/render/contact-sheet.png`
- `artifacts/baseline/after/D_10_body_default_ending/render/contact-sheet.png`

Large binaries are ignored by Git; the deterministic generator and scenario
data reproduce them without network access.

## Verification commands

```bash
python3 -m pytest -q
python3 tests/fixtures/build_baseline.py \
  --output artifacts/baseline/after \
  --pipeline unified
python3 scripts/ghb_ppt.py doctor
```

Current results:

- `55 passed in 4.72s`
- nine optimized cases built successfully;
- 57/57 slide PNGs and nine contact sheets produced;
- nine final reports passed with zero errors;
- zero full-slide pictures, body-object overflows, or detected text overlaps.

## Known limitations

- Microsoft YaHei is not installed in the current LibreOffice environment.
  Chinese glyphs can disappear or render as squares, and mixed text may lose an
  adjacent Latin character. The source SVG and DrawingML contain the text, but
  this environment cannot prove Chinese visual fidelity. Re-render in the
  target enterprise PowerPoint/Office environment before release.
- The template intentionally contains one cover object outside the slide for
  bleed. It remains a warning and was visually reviewed rather than silently
  ignored.
- Automated bounds and overlap checks are conservative. Typography, hierarchy,
  intentional layering, and aesthetic balance remain page-by-page manual review
  items.
- Cover speaker notes are not copied to avoid notes-master conflicts. Body
  notes are written and validated.

## Maintainability

`SKILL.md` is now a concise execution contract. Detailed authoring, layout,
quality/recovery, OOXML, image/license, template, and vendor-sync guidance lives
in directly linked references. `requirements.txt`, `requirements-dev.txt`, and
the offline GitHub Actions workflow make dependencies and regression commands
explicit.

Vendored ppt-master changes remain narrow and regression-tested. Future syncs
must follow [the vendor policy](../references/vendor-sync-policy.md) and rerun
both the full suite and the rendered fixture matrix.
